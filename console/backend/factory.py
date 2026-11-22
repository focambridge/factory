"""Read model of the factory: projects, units, batches, tickets, runs, artifacts.

Everything here reads the factory's own files and reuses the gate (core.ticket_check)
and the project model (core.project), so the console shows exactly what the
command-line tools see.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import yaml

FACTORY_ROOT = Path(__file__).resolve().parents[2]

import sys  # noqa: E402

if str(FACTORY_ROOT) not in sys.path:
    sys.path.insert(0, str(FACTORY_ROOT))

from core import project as proj  # noqa: E402
from core.ticket_check import dor_check  # noqa: E402

PROJECT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_config_lock = threading.Lock()
_config: dict | None = None


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


# ------------------------------------------------------------------ config

def config() -> dict:
    """Load config/factory.yaml once and apply it to the gate."""
    global _config
    with _config_lock:
        if _config is None:
            path = FACTORY_ROOT / "config" / "factory.yaml"
            _config = dor_check.load_config(path)
            dor_check.apply_config(_config, FACTORY_ROOT)
        return _config


def projects_dir() -> Path:
    return proj.resolve(FACTORY_ROOT, config()["paths"].get("projects", "projects"))


def public_config() -> dict:
    c = config()
    builder = c.get("builder") or {}
    claude = builder.get("claude") or {}
    return {
        "factory_root": str(FACTORY_ROOT),
        "gate": c.get("gate", {}),
        "runner": {k: v for k, v in (c.get("runner") or {}).items()
                   if k in ("builder", "max_attempts", "command_timeout_seconds", "branch_prefix",
                            "forbidden_commands", "allowed_commands", "strip_env_prefixes")},
        "builder": {
            "auth": builder.get("auth", "subscription"),
            "model": claude.get("model"),
            "max_turns": claude.get("max_turns"),
            "timeout_seconds": claude.get("timeout_seconds"),
            "max_cost_usd_per_ticket": claude.get("max_cost_usd_per_ticket"),
            "allowed_tools": claude.get("allowed_tools", []),
            "disallowed_tools": claude.get("disallowed_tools", []),
        },
        "claude_installed": shutil.which(str(claude.get("command", "claude"))) is not None,
    }


# ----------------------------------------------------------------- helpers

def _project_dir(name: str) -> Path:
    if not PROJECT_NAME.match(name or ""):
        raise NotFound(f"no project {name!r}")
    d = projects_dir() / name
    if not (d / "project.yaml").is_file():
        raise NotFound(f"no project {name!r}")
    return d


def load(name: str) -> proj.Project:
    config()
    try:
        return proj.load_project(_project_dir(name), dor_check.PROJECT_SCHEMA_PATH, dor_check.UNIT_SCHEMA_PATH)
    except proj.ProjectError as exc:
        raise BadRequest(str(exc)) from exc


def _unit(project: proj.Project, unit_name: str) -> proj.Unit:
    unit = project.units.get(unit_name)
    if unit is None:
        raise NotFound(f"no unit {unit_name!r} in {project.name}")
    return unit


def batch_dir(project: proj.Project, unit_name: str, batch: str) -> Path:
    unit = _unit(project, unit_name)
    d = unit.dir / "tickets" / batch
    if not re.match(r"^[A-Za-z0-9._-]+$", batch) or not d.is_dir():
        raise NotFound(f"no batch {batch!r} in {unit.label}")
    return d


def safe_child(root: Path, rel: str) -> Path:
    """root/rel, refusing anything that leaves root."""
    target = (root / rel).resolve()
    root = root.resolve()
    if target != root and root not in target.parents:
        raise BadRequest("path leaves its folder")
    return target


def read_text(path: Path) -> str:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return ""


def runs(project: proj.Project) -> list:
    out = []
    if project.runs.is_dir():
        for f in sorted(project.runs.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                state = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            out.append(state)
    return out


def _run_summary(state: dict) -> dict:
    return {
        "run_id": state.get("run_id"),
        "unit": state.get("unit"),
        "batch": Path(state.get("batch", "")).name,
        "status": state.get("status"),
        "branch": state.get("branch"),
        "worktree": state.get("worktree"),
        "builder": state.get("builder"),
        "started": state.get("started"),
        "finished": state.get("finished"),
        "tickets": [{k: t.get(k) for k in ("id", "status", "attempts", "commit", "cost_usd", "sequence")}
                    for t in state.get("tickets", [])],
        "warnings": state.get("warnings") or [],
    }


def _merged_ids(project: proj.Project, ids: list) -> set:
    """Ticket ids whose Factory-Ticket trailer is on the base branch (one git call)."""
    if not ids or not proj.is_git_repo(project.workspace):
        return set()
    proc = subprocess.run(["git", "-C", str(project.workspace), "log", project.base_branch, "--format=%B"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return set()
    found = set(re.findall(r"^\s*Factory-Ticket:\s*(\S+)\s*$", proc.stdout, re.M))
    return {i for i in ids if i in found}


def ticket_status(tid: str, merged: set, run_states: list) -> dict:
    """Where a ticket stands: merged, built (unmerged), waiting for approval, failed, or not built."""
    if tid in merged:
        return {"status": "merged", "label": "Merged into main"}
    for state in run_states:  # newest first
        for t in state.get("tickets", []):
            if t.get("id") != tid:
                continue
            s = t.get("status")
            if s == "done":
                return {"status": "built", "label": "Built, not merged yet", "run_id": state.get("run_id")}
            if s == "awaiting_approval":
                return {"status": "awaiting_approval", "label": "Waiting for your approval",
                        "run_id": state.get("run_id")}
            if s == "failed":
                return {"status": "failed", "label": "Failed in the last run", "run_id": state.get("run_id")}
            if s == "merged":
                return {"status": "merged", "label": "Merged into main"}
    return {"status": "not_built", "label": "Not built yet"}


def _ticket_summary(path: Path) -> dict:
    try:
        t = dor_check.load_ticket(path)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        return {"file": path.name, "id": None, "error": dor_check.describe_error(exc)}
    risk = t.get("risk") or {}
    size = t.get("size") or {}
    return {
        "file": path.name,
        "id": t.get("id"),
        "sequence": t.get("sequence"),
        "title": t.get("title"),
        "type": t.get("type"),
        "size": size.get("estimate"),
        "risk": risk.get("level"),
        "approval": bool(risk.get("human_approval_required")),
        "blocked_by": (t.get("dependencies") or {}).get("blocked_by") or [],
    }


# ------------------------------------------------------------------ views

def list_projects() -> list:
    config()
    items = []
    folder = projects_dir()
    for d in sorted(folder.iterdir(), key=lambda p: p.name.lower()) if folder.is_dir() else []:
        if not (d / "project.yaml").is_file():
            continue
        try:
            items.append(project_summary(d.name))
        except (BadRequest, NotFound) as exc:
            items.append({"name": d.name, "error": str(exc)})
    return items


def project_summary(name: str) -> dict:
    project = load(name)
    run_states = runs(project)
    ids = [s["id"] for u in project.units.values() for b in u.batches()
           for s in map(_ticket_summary, proj.ticket_files(b)) if s.get("id")]
    merged = _merged_ids(project, ids)
    return {
        "name": project.name,
        "folder": project.dir.name,
        "description": proj.load_mapping(project.source).get("description", ""),
        "workspace": str(project.workspace),
        "workspace_ready": proj.is_git_repo(project.workspace),
        "units": [{"name": u.name, "kind": u.kind, "label": u.label} for u in project.units.values()],
        "ticket_count": len(ids),
        "merged_count": len(merged),
        "last_run": _run_summary(run_states[0]) if run_states else None,
    }


def project_detail(name: str) -> dict:
    project = load(name)
    run_states = runs(project)
    all_ids = []
    units = []
    for u in project.units.values():
        batches = []
        for b in u.batches():
            tickets = [_ticket_summary(p) for p in proj.ticket_files(b)]
            tickets.sort(key=lambda t: (t.get("sequence") is None, t.get("sequence") or 0))
            all_ids += [t["id"] for t in tickets if t.get("id")]
            batches.append({"name": b.name, "path": str(b.relative_to(project.dir)), "tickets": tickets})
        units.append({
            "name": u.name, "kind": u.kind, "label": u.label,
            "repo_path": u.path or ".",
            "description": proj.load_mapping(u.source).get("description", ""),
            "packaging": u.packaging, "platform": u.platform,
            "defaults": u.defaults,
            "provides": [c.__dict__ for c in u.provides], "uses": u.uses, "services": u.services,
            "unit_yaml": read_text(u.source),
            "batches": batches,
        })
    merged = _merged_ids(project, all_ids)
    for u in units:
        for b in u["batches"]:
            for t in b["tickets"]:
                if t.get("id"):
                    t.update(ticket_status(t["id"], merged, run_states))
    errors, warnings = proj.check_project(project)
    return {
        **project_summary(name),
        "dir": str(project.dir),
        "base_branch": project.base_branch,
        "platform": project.platform,
        "stages": project.stages,
        "project_yaml": read_text(project.source),
        "readme": read_text(project.dir / "README.md"),
        "has_setup_script": (project.dir / "setup_workspace.sh").is_file(),
        "has_seed": (project.dir / "seed").is_dir(),
        "check": {"errors": errors, "warnings": warnings},
        "units": units,
        "runs": [_run_summary(s) for s in run_states],
    }


def batch_detail(name: str, unit_name: str, batch: str) -> dict:
    project = load(name)
    unit = _unit(project, unit_name)
    d = batch_dir(project, unit_name, batch)
    gate = dor_check.check_directory(d, project.workspace if proj.is_git_repo(project.workspace) else None)
    run_states = [s for s in runs(project) if Path(s.get("batch", "")).resolve() == d.resolve()]
    merged = _merged_ids(project, [t["ticket"] for t in gate["tickets"] if t.get("ticket")])
    tickets = []
    for t in gate["tickets"]:
        summary = _ticket_summary(d / t["file"])
        summary.update(gate=t)
        if summary.get("id"):
            summary.update(ticket_status(summary["id"], merged, run_states))
        tickets.append(summary)
    return {
        "project": project.name, "unit": unit.name, "unit_label": unit.label, "batch": d.name,
        "unit_repo_path": unit.path, "path": str(d), "gate": {k: gate[k] for k in ("verdict", "ticket_count", "verdict_counts",
                                                       "errors", "warnings", "skipped")},
        "tickets": tickets,
        "runs": [_run_summary(s) for s in run_states],
        "latest_run": run_states[0] if run_states else None,
        "workspace_ready": proj.is_git_repo(project.workspace),
        "command": f".venv/bin/python core/runner/run_batch.py {d.relative_to(FACTORY_ROOT)}",
    }


def ticket_detail(name: str, unit_name: str, batch: str, file: str) -> dict:
    project = load(name)
    unit = _unit(project, unit_name)
    d = batch_dir(project, unit_name, batch)
    path = safe_child(d, file)
    if not path.is_file():
        raise NotFound(f"no ticket {file!r}")
    raw = path.read_text()
    parsed, effective, error, check = None, None, None, None
    try:
        parsed = dor_check.load_ticket(path)
        effective = proj.effective_ticket(parsed, unit)
        root = unit.repo_dir(project.workspace) if proj.is_git_repo(project.workspace) else None
        report = dor_check.check_ticket(effective, root)
        check = report.as_dict(effective)
    except Exception as exc:  # noqa: BLE001
        error = dor_check.describe_error(exc)
    artifact = artifact_summary(project, parsed.get("id")) if parsed and parsed.get("id") else None
    status = None
    if parsed and parsed.get("id"):
        status = ticket_status(parsed["id"], _merged_ids(project, [parsed["id"]]), runs(project))
    return {
        "project": project.name, "unit": unit.name, "unit_label": unit.label, "batch": d.name, "file": file,
        "path": str(path), "raw": raw, "ticket": parsed, "effective": effective, "error": error,
        "check": check, "artifact": artifact, "status": status,
        "unit_defaults": unit.defaults,
    }


def save_ticket(name: str, unit_name: str, batch: str, file: str, raw: str) -> dict:
    project = load(name)
    d = batch_dir(project, unit_name, batch)
    if not re.match(r"^[A-Za-z0-9._-]+\.ya?ml$", file):
        raise BadRequest("ticket file names end in .yaml and use letters, digits, dots, dashes")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise BadRequest(dor_check.describe_error(exc)) from exc
    if not isinstance(data, dict):
        raise BadRequest("a ticket must be a YAML mapping")
    (d / file).write_text(raw if raw.endswith("\n") else raw + "\n")
    return ticket_detail(name, unit_name, batch, file)


def new_ticket(name: str, unit_name: str, batch: str) -> dict:
    """A new ticket file from the template, with the next sequence number."""
    project = load(name)
    d = batch_dir(project, unit_name, batch)
    existing = [_ticket_summary(p) for p in proj.ticket_files(d)]
    seqs = [t.get("sequence") for t in existing if isinstance(t.get("sequence"), int)]
    seq = (max(seqs) if seqs else 0) + 1
    template = (FACTORY_ROOT / "templates" / "project" / "services" / "app" / "tickets" / "batch-1"
                / "001-example.yaml")
    text = template.read_text() if template.is_file() else read_text(dor_check.resolve(
        FACTORY_ROOT, config()["paths"]["ticket_template"]))
    text = re.sub(r"^sequence: \d+", f"sequence: {seq}", text, count=1, flags=re.M)
    file = f"{seq:03d}-new-ticket.yaml"
    n = 2
    while (d / file).exists():
        file = f"{seq:03d}-new-ticket-{n}.yaml"
        n += 1
    (d / file).write_text(text)
    return {"file": file}


def new_batch(name: str, unit_name: str) -> dict:
    project = load(name)
    unit = _unit(project, unit_name)
    tickets = unit.dir / "tickets"
    tickets.mkdir(exist_ok=True)
    n = 1
    while (tickets / f"batch-{n}").exists():
        n += 1
    (tickets / f"batch-{n}").mkdir()
    return {"batch": f"batch-{n}"}


def save_config_file(name: str, which: str, raw: str, unit_name: str | None = None) -> dict:
    """Save project.yaml or a unit.yaml, refusing the save if the project no longer loads."""
    project = load(name)
    path = project.source if which == "project" else _unit(project, unit_name or "").source
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise BadRequest(dor_check.describe_error(exc)) from exc
    if not isinstance(data, dict):
        raise BadRequest("must be a YAML mapping")
    old = path.read_text()
    path.write_text(raw if raw.endswith("\n") else raw + "\n")
    try:
        load(name)
    except BadRequest as exc:
        path.write_text(old)
        raise BadRequest(f"not saved: {exc}") from exc
    return project_detail(name)


# --------------------------------------------------------------- artifacts

def artifact_summary(project: proj.Project, ticket_id: str) -> dict | None:
    d = project.artifacts / ticket_id
    if not d.is_dir():
        return None
    report = {}
    try:
        report = json.loads((d / "report.json").read_text())
    except (OSError, ValueError):
        pass
    attempts = []
    for a in report.get("attempts", []):
        build = a.get("build") or {}
        attempts.append({
            "attempt": a.get("attempt"), "result": a.get("result"),
            "message": build.get("message"), "cost_usd": build.get("cost_usd"), "turns": build.get("turns"),
            "summary": build.get("summary"),
            "scope": a.get("scope"),
            "commands": [{k: c.get(k) for k in ("name", "command", "status", "log")} for c in a.get("commands", [])],
            "criteria": [{k: c.get(k) for k in ("id", "method", "then", "status", "command", "log")}
                         for c in a.get("criteria", [])],
        })
    files = sorted(str(p.relative_to(project.dir)) for p in d.rglob("*") if p.is_file())
    return {
        "dir": str(d), "status": report.get("status"), "commit": report.get("commit"),
        "run_id": report.get("run_id"), "branch": report.get("branch"), "cost_usd": report.get("cost_usd"),
        "changed_files": report.get("changed_files", []), "attempts": attempts, "files": files,
        "stopped": report.get("stopped"),
    }


def project_file(name: str, rel: str) -> Path:
    project = load(name)
    path = safe_child(project.dir, rel)
    if not path.is_file():
        raise NotFound(f"no file {rel!r}")
    return path


# --------------------------------------------------------------- workspace

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".vite", "dist", "build",
             ".mypy_cache"}


def workspace_info(name: str) -> dict:
    project = load(name)
    ws = project.workspace
    info = {"path": str(ws), "ready": proj.is_git_repo(ws), "base_branch": project.base_branch,
            "units": [{"name": u.name, "path": str(u.repo_dir(ws))} for u in project.units.values()]}
    if not info["ready"]:
        return info

    def git(*args):
        p = subprocess.run(["git", "-C", str(ws), *args], capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else ""

    log = git("log", project.base_branch, "-n", "30", "--format=%h%x1f%s%x1f%cr")
    info["log"] = [dict(zip(("commit", "subject", "when"), line.split("\x1f"))) for line in log.splitlines() if line]
    unmerged = git("branch", "--no-merged", project.base_branch, "--format=%(refname:short)")
    info["unmerged_branches"] = [b for b in unmerged.splitlines() if b.startswith(
        str(config()["runner"].get("branch_prefix", "factory")) + "/")]
    info["current_branch"] = git("branch", "--show-current")
    info["dirty"] = bool(git("status", "--porcelain"))
    return info


def workspace_list(name: str, rel: str = "") -> dict:
    project = load(name)
    ws = project.workspace
    if not ws.is_dir():
        raise NotFound("the project repository does not exist yet")
    d = safe_child(ws, rel or ".")
    if not d.is_dir():
        raise NotFound(f"no folder {rel!r}")
    entries = []
    for p in sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if p.name in SKIP_DIRS or p.name == ".DS_Store":
            continue
        entries.append({"name": p.name, "dir": p.is_dir(), "size": p.stat().st_size if p.is_file() else None,
                        "path": str(p.relative_to(ws))})
    return {"path": str(d.relative_to(ws)) if d != ws else "", "abs": str(d), "entries": entries}


def workspace_file(name: str, rel: str) -> Path:
    project = load(name)
    path = safe_child(project.workspace, rel)
    if not path.is_file():
        raise NotFound(f"no file {rel!r}")
    return path


def allowed_to_open(path: Path) -> bool:
    path = path.resolve()
    roots = [FACTORY_ROOT.resolve()]
    for item in list_projects():
        if item.get("workspace"):
            roots.append(Path(item["workspace"]).resolve())
    return any(path == r or r in path.parents for r in roots)
