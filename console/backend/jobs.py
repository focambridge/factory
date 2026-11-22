"""Background jobs: batch runs, resumes, merges, repository set-up and Claude drafts.

Each job runs in a thread, keeps its output lines, and can be polled by the
front end. Only one batch run per project runs at a time.
"""
from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import factory as fx
from .factory import BadRequest, FACTORY_ROOT, proj

EXIT_MEANING = {0: "completed", 1: "stopped: rejected by the gate or a ticket failed",
                2: "paused for your approval", 3: "error"}

_ids = itertools.count(1)
_lock = threading.Lock()
_jobs: dict = {}


@dataclass
class Job:
    id: str
    kind: str
    title: str
    project: str | None = None
    status: str = "running"            # running | succeeded | failed | paused
    lines: list = field(default_factory=list)
    started: float = field(default_factory=time.time)
    finished: float | None = None
    exit_code: int | None = None
    result: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def log(self, text: str) -> None:
        for line in str(text).splitlines() or [""]:
            self.lines.append(line)

    def view(self, since: int = 0) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "project": self.project,
            "status": self.status, "started": self.started, "finished": self.finished,
            "exit_code": self.exit_code, "exit_meaning": EXIT_MEANING.get(self.exit_code) if self.kind in
            ("run", "resume") else None,
            "lines": self.lines[since:], "line_count": len(self.lines), "result": self.result, "meta": self.meta,
        }


def get(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise fx.NotFound(f"no job {job_id}")
    return job


def recent(limit: int = 30) -> list:
    return [j.view(len(j.lines)) | {"lines": j.lines[-3:]} for j in
            sorted(_jobs.values(), key=lambda j: j.started, reverse=True)[:limit]]


def _start(kind: str, title: str, project: str | None, work: Callable[[Job], None], meta: dict | None = None) -> Job:
    with _lock:
        if kind in ("run", "resume") and project:
            busy = [j for j in _jobs.values() if j.project == project and j.kind in ("run", "resume")
                    and j.status == "running"]
            if busy:
                raise BadRequest(f"a batch is already running for {project} (job {busy[0].id})")
        job = Job(id=str(next(_ids)), kind=kind, title=title, project=project, meta=meta or {})
        _jobs[job.id] = job

    def target():
        try:
            work(job)
            if job.status == "running":
                job.status = "succeeded"
        except Exception as exc:  # noqa: BLE001 - reported to the user
            job.log(f"ERROR: {exc}")
            job.status = "failed"
        finally:
            job.finished = time.time()

    threading.Thread(target=target, daemon=True).start()
    return job


def _stream(job: Job, cmd: list, cwd: Path, env: dict | None = None) -> int:
    job.log("$ " + " ".join(str(c) for c in cmd))
    proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})})
    assert proc.stdout is not None
    for line in proc.stdout:
        job.lines.append(line.rstrip("\n"))
    return proc.wait()


# ------------------------------------------------------------------- runs

def start_run(name: str, unit: str, batch: str, builder: str | None, auth: str | None) -> Job:
    project = fx.load(name)
    d = fx.batch_dir(project, unit, batch)
    if not proj.is_git_repo(project.workspace):
        raise BadRequest("the project's repository does not exist yet: create it first")
    cmd = [sys.executable, FACTORY_ROOT / "core" / "runner" / "run_batch.py", d]
    if builder:
        cmd += ["--builder", builder]
    if auth:
        cmd += ["--auth", auth]
    return _start("run", f"Run {unit}/{batch}", name,
                  lambda job: _finish_run(job, _stream(job, cmd, FACTORY_ROOT)),
                  {"unit": unit, "batch": batch, "builder": builder, "auth": auth})


def start_resume(name: str, unit: str, batch: str, run_id: str, approve: list, builder: str | None,
                 auth: str | None) -> Job:
    project = fx.load(name)
    d = fx.batch_dir(project, unit, batch)
    cmd = [sys.executable, FACTORY_ROOT / "core" / "runner" / "run_batch.py", d, "--resume", run_id]
    for tid in approve:
        cmd += ["--approve", tid]
    if builder:
        cmd += ["--builder", builder]
    if auth:
        cmd += ["--auth", auth]
    title = f"Resume {unit}/{batch}" + (f", approving {', '.join(approve)}" if approve else "")
    return _start("resume", title, name, lambda job: _finish_run(job, _stream(job, cmd, FACTORY_ROOT)),
                  {"unit": unit, "batch": batch, "run_id": run_id, "approve": approve})


def _finish_run(job: Job, code: int) -> None:
    job.exit_code = code
    job.status = {0: "succeeded", 2: "paused"}.get(code, "failed")
    job.log(f"[{EXIT_MEANING.get(code, 'finished')}]")


# --------------------------------------------------------------- git work

def start_merge(name: str, branch: str) -> Job:
    project = fx.load(name)
    if not branch.startswith(str(fx.config()["runner"].get("branch_prefix", "factory")) + "/"):
        raise BadRequest("only factory branches can be merged from the console")

    def work(job: Job):
        code = _stream(job, ["git", "-C", project.workspace, "-c", "user.name=Factory console",
                             "-c", "user.email=factory@localhost", "merge", "--no-edit", branch], FACTORY_ROOT)
        job.exit_code = code
        if code != 0:
            job.status = "failed"
            job.log("The merge did not complete. Resolve it in the repository, or ask for help.")
        else:
            job.log("Merged. The tickets on this branch now count as done.")

    return _start("merge", f"Merge {branch}", name, work, {"branch": branch})


def start_setup(name: str) -> Job:
    project = fx.load(name)

    def work(job: Job):
        ws = project.workspace
        if proj.is_git_repo(ws):
            job.log(f"The repository already exists at {ws}")
            return
        script = project.dir / "setup_workspace.sh"
        if script.is_file() and os.access(script, os.X_OK):
            code = _stream(job, [script], project.dir)
            job.exit_code = code
            if code != 0:
                job.status = "failed"
            return
        create_workspace(project, job)

    return _start("setup", f"Create the repository for {name}", name, work)


def create_workspace(project: proj.Project, job: Job) -> None:
    """Make the project's git repo: copy seed/ if present, one commit on the base branch."""
    ws = project.workspace
    if ws.exists() and any(ws.iterdir()):
        raise BadRequest(f"{ws} already exists and is not empty")
    ws.mkdir(parents=True, exist_ok=True)
    seed = project.dir / "seed"
    if seed.is_dir():
        shutil.copytree(seed, ws, dirs_exist_ok=True)
    if not (ws / "README.md").exists():
        (ws / "README.md").write_text(f"# {project.name}\n\nBuilt ticket by ticket by the factory.\n")
    for args in (["init", "-q"], ["checkout", "-q", "-b", project.base_branch], ["add", "-A"],
                 ["-c", "user.name=Factory", "-c", "user.email=factory@localhost", "commit", "-q", "-m",
                  f"Start {project.name}"]):
        code = _stream(job, ["git", "-C", ws, *args], FACTORY_ROOT)
        if code != 0:
            raise BadRequest(f"git {' '.join(args)} failed")
    job.log(f"Repository created at {ws}")


def start_callable(kind: str, title: str, project: str | None, fn: Callable[[Job], dict], meta=None) -> Job:
    def work(job: Job):
        job.result = fn(job) or {}
    return _start(kind, title, project, work, meta)


def open_path(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        raise fx.NotFound(f"{p} does not exist")
    if not fx.allowed_to_open(p):
        raise BadRequest("only folders inside the factory or a project repository can be opened")
    opener = "open" if sys.platform == "darwin" else ("xdg-open" if shutil.which("xdg-open") else None)
    if opener is None:
        return {"opened": False, "path": str(p)}
    subprocess.Popen([opener, str(p)])
    return {"opened": True, "path": str(p)}
