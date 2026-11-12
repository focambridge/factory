#!/usr/bin/env python3
"""Batch runner: validate a ticket directory, then build its tickets in order.

Usage:
    python core/runner/run_batch.py projects/<project>/tickets/<batch> [--builder NAME]
    python core/runner/run_batch.py projects/<project>/tickets/<batch> --resume RUN_ID [--approve TICKET-ID ...]

Workflow for one batch:
  1. Run the Definition-of-Ready gate on the directory. If it is not READY,
     nothing is processed.
  2. Create a git worktree on a new branch from the project's base branch.
     Each ticket builds on the commit the previous ticket left (shared workspace).
  3. For each ticket, in sequence order, up to runner.max_attempts times:
     reset the worktree to the last good commit, run the builder, check the
     changed files against affected_paths and protected_paths, run
     technical.commands, and check each acceptance criterion through its
     verification reference.
  4. A passing ticket is committed. Its artifact is written to
     <project>/artifacts/<ticket-id>/: report.json, changes.patch, ticket.yaml
     and logs/. A ticket that fails every attempt stops the batch.
  5. A ticket with risk.human_approval_required pauses the batch after its
     commit. Review it, then resume with --approve.

The run record <project>/runs/<run-id>.json holds the gate result, a hash of
each ticket at validation time, and each ticket's status, attempts and commit.
A resumed run refuses to continue if any ticket file has changed.

The project directory needs a project.yaml naming the workspace git repo.

Exit codes: 0 completed, 1 rejected by the gate or a ticket failed,
2 paused for approval, 3 error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

FACTORY_ROOT = Path(__file__).resolve().parents[2]
if str(FACTORY_ROOT) not in sys.path:
    sys.path.insert(0, str(FACTORY_ROOT))

from core.runner.builders import BUILDERS, BuildContext  # noqa: E402
from core.ticket_check import dor_check  # noqa: E402

PASSING_CRITERIA = {"pass", "indirect", "manual"}
LOG_TAIL_LINES = 40


class RunnerError(Exception):
    pass


# ------------------------------------------------------------------ helpers

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def as_text(value) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def tail(text: str, lines: int = LOG_TAIL_LINES) -> str:
    return "\n".join(text.rstrip().splitlines()[-lines:])


def git(repo: Path, *args: str, strip: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RunnerError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip() if strip else proc.stdout


# ------------------------------------------------------- settings and project

@dataclass
class Settings:
    worktrees: Path
    builder: str
    max_attempts: int
    command_timeout: int
    branch_prefix: str
    commit_name: str
    commit_email: str
    test_reference_command: str
    forbidden_commands: list
    strip_env_prefixes: list
    set_env: dict


def load_settings(config: dict, root: Path) -> Settings:
    try:
        runner = config["runner"]
        return Settings(
            worktrees=dor_check.resolve(root, config["paths"]["worktrees"]),
            builder=str(runner["builder"]),
            max_attempts=int(runner["max_attempts"]),
            command_timeout=int(runner["command_timeout_seconds"]),
            branch_prefix=str(runner["branch_prefix"]),
            commit_name=str(runner["commit_name"]),
            commit_email=str(runner["commit_email"]),
            test_reference_command=str(runner["test_reference_command"]),
            forbidden_commands=[re.compile(p) for p in runner.get("forbidden_commands") or []],
            strip_env_prefixes=[str(p) for p in runner.get("strip_env_prefixes") or []],
            set_env={str(k): str(v) for k, v in (runner.get("set_env") or {}).items()},
        )
    except (KeyError, TypeError, ValueError, re.error) as exc:
        raise RunnerError(f"config: runner settings missing or malformed: {exc}") from exc


@dataclass
class Project:
    name: str
    dir: Path
    workspace: Path
    base_branch: str
    fixtures: Path

    @property
    def artifacts(self) -> Path:
        return self.dir / "artifacts"

    @property
    def runs(self) -> Path:
        return self.dir / "runs"


def load_project(batch_dir: Path) -> Project:
    if batch_dir.parent.name != "tickets":
        raise RunnerError(f"{batch_dir} is not a batch: expected <project>/tickets/<batch>")
    project_dir = batch_dir.parent.parent
    path = project_dir / "project.yaml"
    if not path.is_file():
        raise RunnerError(f"{path} not found: it must name the workspace repository")
    data = yaml.safe_load(path.read_text()) or {}
    try:
        return Project(
            name=str(data.get("name") or project_dir.name),
            dir=project_dir,
            workspace=dor_check.resolve(project_dir, data["workspace"]).resolve(),
            base_branch=str(data.get("base_branch") or "main"),
            fixtures=dor_check.resolve(project_dir, data.get("fixtures") or "fixtures"),
        )
    except (KeyError, TypeError) as exc:
        raise RunnerError(f"{path}: missing or malformed key {exc}") from exc


# ------------------------------------------------------------ verification

def command_env(settings: Settings) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not any(k.startswith(p) for p in settings.strip_env_prefixes)}
    env.update(settings.set_env)
    # Commands use the same Python environment as the runner.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def run_command(name: str, command: str, cwd: Path, log: Path, log_root: Path,
                settings: Settings, cache: dict) -> dict:
    """Run one shell command in the worktree. An identical command runs once per attempt."""
    if command in cache:
        return {**cache[command], "name": name}
    result = {"name": name, "command": command}
    blocked = next((p.pattern for p in settings.forbidden_commands if p.search(command)), None)
    if blocked:
        result.update(status="forbidden", exit_code=None, seconds=0, log=None,
                      detail=f"matches runner.forbidden_commands: {blocked}")
        cache[command] = result
        return result
    start = time.monotonic()
    try:
        proc = subprocess.run(command, shell=True, cwd=cwd, env=command_env(settings),
                              capture_output=True, text=True, timeout=settings.command_timeout)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
        status = "pass" if code == 0 else "fail"
    except subprocess.TimeoutExpired as exc:
        code, out, err, status = None, as_text(exc.stdout), as_text(exc.stderr), "timeout"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"$ {command}\n\n--- stdout\n{out}\n--- stderr\n{err}\n--- exit {code}\n")
    result.update(status=status, exit_code=code, seconds=round(time.monotonic() - start, 2),
                  log=str(log.relative_to(log_root)))
    cache[command] = result
    return result


def path_matches(path: str, pattern: str) -> bool:
    pattern = pattern.strip()
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(c in pattern for c in "*?["):
        return fnmatch.fnmatchcase(path, pattern)
    return path == pattern or path.startswith(pattern + "/")


def check_scope(ticket: dict, worktree: Path) -> dict:
    git(worktree, "add", "-A")
    out = git(worktree, "diff", "--cached", "--name-only", "--no-renames", "-z", strip=False)
    changed = sorted(p for p in out.split("\0") if p)
    scope = ticket.get("scope") or {}
    affected = [str(p) for p in scope.get("affected_paths") or []]
    protected = [str(p) for p in scope.get("protected_paths") or []]
    problems = [] if changed else ["the builder changed no files"]
    problems += [f"{p} is outside affected_paths" for p in changed
                 if not any(path_matches(p, a) for a in affected)]
    problems += [f"{p} is a protected path" for p in changed
                 if any(path_matches(p, x) for x in protected)]
    return {"status": "fail" if problems else "pass", "changed": changed, "problems": problems}


def criterion_command(criterion: dict, settings: Settings) -> str | None:
    verification = criterion.get("verification") or {}
    method = verification.get("method")
    ref = str(verification.get("reference") or "").strip()
    if not ref:
        return None
    if method == "static_check" or re.search(r"\s", ref):
        return ref  # already a command
    return settings.test_reference_command.format(python=shlex.quote(sys.executable), ref=shlex.quote(ref))


def check_criteria(ticket: dict, worktree: Path, settings: Settings, log_dir: Path,
                   log_root: Path, cache: dict, commands: list) -> list:
    test_passed = any(c["name"] == "test" and c["status"] == "pass" for c in commands)
    results = []
    for c in ticket.get("acceptance_criteria") or []:
        cid = str(c.get("id", "?"))
        method = (c.get("verification") or {}).get("method")
        entry = {"id": cid, "method": method, "then": " ".join(str(c.get("then", "")).split())}
        if method == "manual":
            entry.update(status="manual", detail="checked by a human at approval")
        else:
            command = criterion_command(c, settings)
            if command is None:
                entry.update(status="indirect" if test_passed else "fail",
                             detail="no reference: relies on the 'test' command")
            else:
                r = run_command(cid, command, worktree, log_dir / f"{cid}.log", log_root, settings, cache)
                entry.update(status="pass" if r["status"] == "pass" else "fail", command=command,
                             exit_code=r.get("exit_code"), log=r.get("log"))
                if r["status"] in ("forbidden", "timeout"):
                    entry["detail"] = r.get("detail") or r["status"]
        results.append(entry)
    return results


def failure_feedback(outcome, scope: dict, commands: list, criteria: list, log_root: Path) -> list:
    """Plain-language reasons the attempt failed, for the builder's next attempt."""
    if not outcome.ok:
        return [f"build failed: {outcome.message}"]
    notes = list(scope["problems"])
    seen = set()
    for item in commands + criteria:
        if item["status"] in ("pass", "indirect", "manual"):
            continue
        label = f"{item.get('name') or item.get('id')}: {item['status']}"
        if item.get("command"):
            label += f" ({item['command']})"
        if item.get("detail"):
            label += f": {item['detail']}"
        log = item.get("log")
        if log and log not in seen:
            seen.add(log)
            label += "\n" + tail((log_root / log).read_text())
        notes.append(label)
    return notes


# ------------------------------------------------------------- one ticket

def reset_worktree(worktree: Path) -> None:
    git(worktree, "reset", "-q", "--hard", "HEAD")
    git(worktree, "clean", "-f", "-d", "-q")


def fresh_artifact_dir(artifacts: Path, ticket_id: str) -> Path:
    """artifacts/<ticket-id>/, created if needed. An earlier one moves to artifacts/.history/."""
    target = artifacts / ticket_id
    if target.exists():
        try:
            old_run = json.loads((target / "report.json").read_text()).get("run_id") or "unknown"
        except (OSError, ValueError):
            old_run = "unknown"
        dest = artifacts / ".history" / ticket_id / old_run
        n = 2
        while dest.exists():
            dest = dest.with_name(f"{old_run}-{n}")
            n += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(dest))
    target.mkdir(parents=True)
    return target


def commit_ticket(worktree: Path, ticket: dict, run_id: str, settings: Settings) -> str:
    """Commit the index: exactly the builder's changes that check_scope staged.

    Files that commands created or changed afterwards (caches, build output,
    formatter rewrites) are not committed; the next reset discards them.
    """
    description = " ".join(str(ticket.get("description", "")).split())
    message = (f"{ticket['id']}: {ticket['title']}\n\n{description}\n\n"
               f"Factory-Ticket: {ticket['id']}\nFactory-Run: {run_id}\n")
    git(worktree, "-c", f"user.name={settings.commit_name}", "-c", f"user.email={settings.commit_email}",
        "commit", "-q", "-m", message)
    return git(worktree, "rev-parse", "HEAD")


def process_ticket(state: dict, entry: dict, batch_dir: Path, project: Project,
                   settings: Settings, builder) -> str:
    path = batch_dir / entry["file"]
    if not path.is_file() or sha256(path) != entry["sha256"]:
        raise RunnerError(f"{entry['file']} has changed since validation: start a new run")
    ticket = dor_check.load_ticket(path)
    worktree = Path(state["worktree"])
    art = fresh_artifact_dir(project.artifacts, entry["id"])
    shutil.copy2(path, art / "ticket.yaml")
    parent = git(worktree, "rev-parse", "HEAD")
    commands_spec = (ticket.get("technical") or {}).get("commands") or {}
    report = {
        "ticket": entry["id"], "title": ticket.get("title"), "sequence": entry["sequence"],
        "run_id": state["run_id"], "branch": state["branch"], "parent_commit": parent,
        "builder": builder.name, "status": None, "commit": None, "changed_files": [], "not_committed": [],
        "started": now(), "finished": None, "attempts": [],
    }
    print(f"\n{entry['id']} (sequence {entry['sequence']}): {ticket.get('title')}")
    feedback: list = []
    status = "failed"
    for n in range(1, settings.max_attempts + 1):
        reset_worktree(worktree)
        log_dir = art / "logs" / f"attempt-{n}"
        log_dir.mkdir(parents=True, exist_ok=True)
        attempt = {"attempt": n, "started": now()}
        outcome = builder.build(BuildContext(
            ticket=ticket, ticket_path=path, worktree=worktree, project_dir=project.dir,
            fixtures_dir=project.fixtures, attempt=n, log_dir=log_dir, feedback=feedback))
        scope = {"status": "skipped", "changed": [], "problems": []}
        commands: list = []
        criteria: list = []
        if outcome.ok:
            scope = check_scope(ticket, worktree)
            if scope["status"] == "pass":
                cache: dict = {}
                commands = [run_command(name, str(cmd), worktree, log_dir / f"{name}.log", art, settings, cache)
                            for name, cmd in commands_spec.items()]
                criteria = check_criteria(ticket, worktree, settings, log_dir, art, cache, commands)
        passed = (outcome.ok and scope["status"] == "pass"
                  and all(c["status"] == "pass" for c in commands)
                  and all(c["status"] in PASSING_CRITERIA for c in criteria))
        attempt.update(build={"ok": outcome.ok, "message": outcome.message}, scope=scope,
                       commands=commands, criteria=criteria, result="pass" if passed else "fail",
                       finished=now())
        report["attempts"].append(attempt)
        entry["attempts"] = n
        if passed:
            commit = commit_ticket(worktree, ticket, state["run_id"], settings)
            (art / "changes.patch").write_text(git(worktree, "diff", "--binary", parent, commit, strip=False))
            entry["commit"] = commit
            status = "awaiting_approval" if entry["approval_required"] else "done"
            leftovers = [line[3:] for line in git(worktree, "status", "--porcelain", "-uall").splitlines()]
            report.update(commit=commit, changed_files=scope["changed"], not_committed=leftovers)
            print(f"  attempt {n}: pass, committed {commit[:8]}")
            break
        feedback = failure_feedback(outcome, scope, commands, criteria, art)
        print(f"  attempt {n}: fail: {feedback[0].splitlines()[0] if feedback else 'unknown'}")
    else:
        reset_worktree(worktree)
    report.update(status=status, finished=now())
    write_json(art / "report.json", report)
    return status


# --------------------------------------------------------------- the batch

def save_state(project: Project, state: dict) -> None:
    write_json(project.runs / f"{state['run_id']}.json", state)


def ticket_files(batch_dir: Path) -> list:
    return sorted(p.name for p in batch_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in dor_check.YAML_SUFFIXES
                  and not p.name.startswith(("_", ".")))


def start_run(batch_dir: Path, project: Project, settings: Settings, builder) -> dict | None:
    try:
        git(project.workspace, "rev-parse", "--is-inside-work-tree")
    except RunnerError:
        raise RunnerError(f"workspace {project.workspace} is not a git repository") from None
    base_commit = git(project.workspace, "rev-parse", "--verify", f"{project.base_branch}^{{commit}}")

    hashes = {name: sha256(batch_dir / name) for name in ticket_files(batch_dir)}
    gate = dor_check.check_directory(batch_dir, project.workspace)
    dor_check.print_directory(gate)
    if gate["verdict"] != "READY":
        print("\nBatch rejected by the gate: nothing processed.")
        return None

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{batch_dir.name}-{stamp}"
    branch = f"{settings.branch_prefix}/{batch_dir.name}/{stamp}"
    worktree = settings.worktrees / project.name / run_id
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(project.workspace, "worktree", "add", "-q", "-b", branch, str(worktree), base_commit)

    tickets = []
    for t in gate["tickets"]:
        ticket = dor_check.load_ticket(batch_dir / t["file"])
        tickets.append({
            "id": t["ticket"], "file": t["file"], "sequence": t["sequence"], "sha256": hashes[t["file"]],
            "approval_required": bool((ticket.get("risk") or {}).get("human_approval_required")),
            "status": "pending", "attempts": 0, "commit": None,
        })
    state = {
        "run_id": run_id, "project": project.name, "batch": str(batch_dir),
        "workspace": str(project.workspace), "base_branch": project.base_branch,
        "base_commit": base_commit, "branch": branch, "worktree": str(worktree),
        "builder": builder.name, "status": "running", "started": now(), "finished": None,
        "gate": {k: gate[k] for k in ("verdict", "ticket_count", "warnings", "skipped")},
        "tickets": tickets,
    }
    save_state(project, state)
    print(f"\nRun {run_id}\n  branch   {branch}\n  worktree {worktree}")
    return state


def resume_run(run_id: str, batch_dir: Path, project: Project) -> dict:
    path = project.runs / f"{run_id}.json"
    if not path.is_file():
        raise RunnerError(f"run record {path} not found")
    state = json.loads(path.read_text())
    if Path(state["batch"]) != batch_dir:
        raise RunnerError(f"run {run_id} belongs to {state['batch']}, not {batch_dir}")
    if ticket_files(batch_dir) != sorted(t["file"] for t in state["tickets"]):
        raise RunnerError("ticket files were added or removed since validation: start a new run")
    for t in state["tickets"]:
        if sha256(batch_dir / t["file"]) != t["sha256"]:
            raise RunnerError(f"{t['file']} has changed since validation: start a new run")
    worktree = Path(state["worktree"])
    if not worktree.is_dir():
        raise RunnerError(f"worktree {worktree} no longer exists: start a new run")
    checkpoint = next((t["commit"] for t in reversed(state["tickets"]) if t["commit"]), state["base_commit"])
    head = git(worktree, "rev-parse", "HEAD")
    if head != checkpoint:
        raise RunnerError(f"worktree HEAD {head[:8]} is not the last checkpoint {checkpoint[:8]}: start a new run")
    print(f"Resuming run {run_id}")
    return state


def print_summary(state: dict) -> None:
    print(f"\nRun {state['run_id']}: {state['status']}")
    for t in state["tickets"]:
        commit = (t["commit"] or "")[:8]
        print(f"  {t['sequence']:>4}  {t['id']:<10} {t['status']:<18} attempts {t['attempts']}  {commit}")
    print(f"  branch   {state['branch']}")
    print(f"  worktree {state['worktree']}")
    print(f"  review   git -C {shlex.quote(state['workspace'])} log --oneline "
          f"{state['base_commit'][:8]}..{state['branch']}")


def process_batch(state: dict, batch_dir: Path, project: Project, settings: Settings,
                  builder, approvals: set) -> int:
    state["status"] = "running"
    try:
        for entry in state["tickets"]:
            if entry["status"] == "done":
                continue
            if entry["status"] == "awaiting_approval":
                if entry["id"] not in approvals:
                    return pause(state, project, entry)
                entry.update(status="done", approved=now())
                save_state(project, state)
                print(f"{entry['id']}: approved")
                continue
            entry["status"] = process_ticket(state, entry, batch_dir, project, settings, builder)
            save_state(project, state)
            if entry["status"] == "failed":
                state.update(status="failed", finished=now())
                save_state(project, state)
                print_summary(state)
                print(f"\n{entry['id']} failed {entry['attempts']} attempts; see "
                      f"{project.artifacts / entry['id'] / 'report.json'}")
                return 1
            if entry["status"] == "awaiting_approval":
                return pause(state, project, entry)
    except Exception:
        state["status"] = "error"
        save_state(project, state)
        raise
    state.update(status="completed", finished=now())
    save_state(project, state)
    print_summary(state)
    return 0


def pause(state: dict, project: Project, entry: dict) -> int:
    state["status"] = "paused"
    save_state(project, state)
    print_summary(state)
    print(f"\n{entry['id']} needs human approval. Review commit {(entry['commit'] or '')[:8]}, then run:\n"
          f"  python core/runner/run_batch.py {shlex.quote(state['batch'])} "
          f"--resume {state['run_id']} --approve {entry['id']}")
    return 2


# -------------------------------------------------------------------- main

def run(args) -> int:
    config_path = (args.config or Path(os.environ.get("FACTORY_CONFIG", dor_check.DEFAULT_CONFIG))).resolve()
    root = config_path.parent.parent
    try:
        config = dor_check.load_config(config_path)
        dor_check.apply_config(config, root)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise RunnerError(f"config {config_path}: {dor_check.describe_error(exc)}") from exc
    settings = load_settings(config, root)
    if args.max_attempts:
        settings.max_attempts = args.max_attempts

    batch_dir = args.batch.resolve()
    if not batch_dir.is_dir():
        raise RunnerError(f"{batch_dir} is not a directory")
    project = load_project(batch_dir)
    name = args.builder or settings.builder
    if name not in BUILDERS:
        raise RunnerError(f"unknown builder {name!r}; available: {', '.join(sorted(BUILDERS))}")
    builder = BUILDERS[name]

    if args.resume:
        state = resume_run(args.resume, batch_dir, project)
    else:
        state = start_run(batch_dir, project, settings, builder)
        if state is None:
            return 1
    return process_batch(state, batch_dir, project, settings, builder, set(args.approve))


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", type=Path, help="ticket directory: projects/<project>/tickets/<batch>")
    parser.add_argument("--resume", metavar="RUN_ID", help="continue a paused or failed run")
    parser.add_argument("--approve", action="append", default=[], metavar="TICKET_ID",
                        help="approve a ticket awaiting approval (with --resume; repeatable)")
    parser.add_argument("--builder", help=f"override runner.builder ({', '.join(sorted(BUILDERS))})")
    parser.add_argument("--max-attempts", type=int, help="override runner.max_attempts")
    parser.add_argument("--config", type=Path, help="factory config file (default: config/factory.yaml)")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except RunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
