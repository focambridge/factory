"""Claude-drafted projects and batches, held in work/drafts until the person saves them.

A draft is a folder shaped like a factory project. Claude writes its files from a
name and a description (or, for a new batch, from an existing project and a
description); the gate checks it; the person reviews, edits or asks for a
revision, then saves it into projects/.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import yaml

from . import factory as fx
from .factory import BadRequest, FACTORY_ROOT, NotFound, dor_check, proj

GUIDE = Path(__file__).with_name("planning_guide.md")
DRAFT_TIMEOUT = 1200
PROJECT_FILES = re.compile(
    r"^(project\.yaml|README\.md|(services|integrations)/[a-z][a-z0-9-]*/unit\.yaml|"
    r"(services|integrations)/[a-z][a-z0-9-]*/tickets/batch-[0-9]+/[A-Za-z0-9._-]+\.ya?ml|"
    r"seed/[A-Za-z0-9._/-]+)$")
BATCH_FILES = re.compile(
    r"^((services|integrations)/[a-z][a-z0-9-]*/unit\.yaml|"
    r"(services|integrations)/[a-z][a-z0-9-]*/tickets/batch-[0-9]+/[A-Za-z0-9._-]+\.ya?ml)$")
SKIP_COPY = {"artifacts", "runs", "fixtures", ".DS_Store"}


def drafts_dir() -> Path:
    d = FACTORY_ROOT / "work" / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _draft_dir(draft_id: str) -> Path:
    if not re.match(r"^[A-Za-z0-9_-]+$", draft_id or ""):
        raise NotFound("no such draft")
    d = drafts_dir() / draft_id
    if not (d / "draft.json").is_file():
        raise NotFound("no such draft")
    return d


def _meta(d: Path) -> dict:
    return json.loads((d / "draft.json").read_text())


def _save_meta(d: Path, meta: dict) -> None:
    (d / "draft.json").write_text(json.dumps(meta, indent=2))


def default_workspace(name: str) -> str:
    target = FACTORY_ROOT.parent / name
    home = Path.home()
    try:
        return "~/" + str(target.relative_to(home))
    except ValueError:
        return str(target)


# ------------------------------------------------------------------ prompt

def _read(path: Path) -> str:
    return fx.read_text(path)


def _example_ticket() -> str:
    """A gate-passing ticket shipped with the console, as a style example."""
    return _read(Path(__file__).with_name("example_ticket.yaml"))


def build_prompt(mode: str, name: str, description: str, existing: dict | None = None,
                 current: dict | None = None, gate: dict | None = None, feedback: str = "") -> str:
    fx.config()
    parts = [
        "You are the planner for a software factory. Do not use any tools. Reply with one JSON object only.",
        "", _read(GUIDE), "",
        "## The ticket JSON Schema", "```json", _read(dor_check.SCHEMA_PATH), "```",
        "## The unit JSON Schema", "```json", _read(dor_check.UNIT_SCHEMA_PATH), "```",
        "## The project JSON Schema", "```json", _read(dor_check.PROJECT_SCHEMA_PATH), "```",
        "## An example ticket that passes the gate (style only; do not copy its content)",
        "```yaml", _example_ticket(), "```",
    ]
    if mode == "project":
        parts += ["", "## The request", f"Project name: {name}",
                  f"Workspace (use exactly): {default_workspace(name)}",
                  "Description from the person:", description.strip()]
    else:
        parts += ["", "## The existing project (do not rewrite these files)"]
        for path, text in (existing or {}).items():
            parts += [f"### {path}", "```", text, "```"]
        parts += ["", "## The request: a new batch of tickets for this project",
                  f"Write files only under services/<unit>/tickets/{(existing or {}).get('__next_batch__', 'batch-N')}/ "
                  "(and a new services/<unit>/unit.yaml only if a new unit is needed). Ticket ids must not "
                  "repeat existing ids; earlier tickets are merged, so blocked_by may name them.",
                  "Description from the person:", description.strip()]
    if current is not None:
        parts += ["", "## Your previous draft"]
        for path, text in current.items():
            parts += [f"### {path}", "```", text, "```"]
        if gate:
            parts += ["", "## The gate's findings on that draft", "```json", json.dumps(gate, indent=1), "```"]
        parts += ["", "## What the person wants changed", feedback.strip() or "(fix the gate's findings)",
                  "", "Return the complete set of files again (all of them, revised), in the same JSON format."]
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------------ claude

def _claude_env() -> tuple:
    from core.runner.builders import ClaudeBuilder
    options = dict(fx.config().get("builder") or {})
    builder = ClaudeBuilder(options, (fx.config().get("runner") or {}).get("strip_env_prefixes"))
    builder.preflight()
    env = builder._env()
    env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = env.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "64000")
    return builder, env


def call_claude(prompt: str, job) -> str:
    """Send a prompt to Claude Code headless and return the reply text."""
    if os.environ.get("FACTORY_CONSOLE_FAKE_CLAUDE"):
        cmd = [os.environ["FACTORY_CONSOLE_FAKE_CLAUDE"]]
        env = dict(os.environ)
    else:
        builder, env = _claude_env()
        cmd = [builder.command, "-p", "--output-format", "json", "--max-turns", "2"]
        if builder.model:
            cmd += ["--model", str(builder.model)]
    job.log("Asking Claude to draft the plan. This usually takes 2 to 6 minutes.")
    start = time.time()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env, cwd=FACTORY_ROOT)
    proc.stdin.write(prompt)
    proc.stdin.close()
    while proc.poll() is None:
        time.sleep(5)
        elapsed = int(time.time() - start)
        if elapsed % 30 < 5:
            job.log(f"  still working ({elapsed // 60}m {elapsed % 60:02d}s)")
        if elapsed > DRAFT_TIMEOUT:
            proc.kill()
            raise BadRequest(f"Claude did not finish within {DRAFT_TIMEOUT // 60} minutes")
    out, err = proc.stdout.read(), proc.stderr.read()
    if proc.returncode != 0 and not out.strip():
        raise BadRequest(f"Claude exited with code {proc.returncode}: {err.strip()[-500:]}")
    try:
        envelope = json.loads(out)
        if isinstance(envelope, dict) and "result" in envelope:
            if envelope.get("is_error"):
                raise BadRequest(f"Claude reported an error: {str(envelope.get('result'))[:500]}")
            cost = envelope.get("total_cost_usd")
            job.log(f"Claude replied after {int(time.time() - start)}s" + (f" (${cost:.2f})" if cost else ""))
            return str(envelope["result"])
    except ValueError:
        pass
    return out


def extract_json(text: str) -> dict:
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    candidate = fence.group(1) if fence else text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(candidate)
    except ValueError as exc:
        raise BadRequest(f"Claude's reply was not valid JSON ({exc}); it may have been cut off") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise BadRequest("Claude's reply had no files")
    return data


# ------------------------------------------------------------------ drafts

def _write_files(d: Path, files: dict, pattern: re.Pattern) -> list:
    written, rejected = [], []
    for rel, text in files.items():
        rel = str(rel).strip().lstrip("./") if str(rel).startswith("./") else str(rel).strip()
        if not pattern.match(rel) or proj.escapes(rel) or ".git/" in rel:
            rejected.append(rel)
            continue
        target = fx.safe_child(d, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(text) if str(text).endswith("\n") else str(text) + "\n")
        written.append(rel)
    if rejected:
        (d / "rejected-files.txt").write_text("\n".join(rejected) + "\n")
    return sorted(written)


def _force_project_identity(d: Path, name: str) -> None:
    path = d / "project.yaml"
    if not path.is_file():
        path.write_text(f"name: {name}\ndescription: \"\"\nworkspace: {default_workspace(name)}\nbase_branch: main\n")
        return
    text = path.read_text()
    text = re.sub(r"^name:.*$", f"name: {name}", text, count=1, flags=re.M)
    if re.search(r"^workspace:", text, re.M):
        text = re.sub(r"^workspace:.*$", f"workspace: {default_workspace(name)}", text, count=1, flags=re.M)
    else:
        text += f"workspace: {default_workspace(name)}\n"
    path.write_text(text)


def check_draft(d: Path) -> dict:
    """The gate on every batch in the draft, plus project-level problems."""
    fx.config()
    result = {"project_error": None, "batches": [], "ready": False}
    try:
        project = proj.load_project(d, dor_check.PROJECT_SCHEMA_PATH, dor_check.UNIT_SCHEMA_PATH)
    except proj.ProjectError as exc:
        result["project_error"] = str(exc)
        return result
    meta = _meta(d)
    only = set(meta.get("files", [])) if meta.get("mode") == "batch" else None
    for unit in project.units.values():
        for b in unit.batches():
            rel_batch = str(b.relative_to(d))
            if only is not None and not any(f.startswith(rel_batch + "/") for f in only):
                continue
            gate = dor_check.check_directory(b, None)
            result["batches"].append({
                "unit": unit.name, "batch": b.name, "path": rel_batch,
                "verdict": gate["verdict"], "errors": gate["errors"],
                "warnings": [w for w in gate["warnings"] if "not a git repository yet" not in w],
                "tickets": gate["tickets"],
            })
    result["ready"] = bool(result["batches"]) and all(b["verdict"] == "READY" for b in result["batches"])
    return result


def _files_of(d: Path, meta: dict) -> dict:
    return {rel: fx.read_text(d / rel) for rel in meta.get("files", []) if (d / rel).is_file()}


def start_project_draft(name: str, description: str):
    from . import jobs
    if not fx.PROJECT_NAME.match(name or ""):
        raise BadRequest("Project names start with a letter and use letters, digits, _ or - (e.g. D501_Quiz_Builder)")
    if (fx.projects_dir() / name).exists():
        raise BadRequest(f"a project called {name} already exists")
    if len(description.strip()) < 30:
        raise BadRequest("Please describe the project in at least a sentence or two")
    draft_id = f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"

    def work(job):
        d = drafts_dir() / draft_id
        d.mkdir(parents=True)
        meta = {"id": draft_id, "mode": "project", "name": name, "description": description,
                "created": time.time(), "status": "drafting", "files": [], "history": []}
        _save_meta(d, meta)
        reply = extract_json(call_claude(build_prompt("project", name, description), job))
        files = _write_files(d, reply["files"], PROJECT_FILES)
        _force_project_identity(d, name)
        if "project.yaml" not in files:
            files.append("project.yaml")
        meta.update(status="ready", files=sorted(set(files)), summary=reply.get("summary", ""))
        meta["history"].append({"at": time.time(), "action": "drafted"})
        _save_meta(d, meta)
        meta["check"] = check_draft(d)
        _save_meta(d, meta)
        job.log(f"Draft ready: {len(files)} files. Gate: "
                + ("all batches READY" if meta["check"]["ready"] else "needs attention"))
        return {"draft_id": draft_id}

    return jobs.start_callable("draft", f"Draft project {name}", None, work, {"draft_id": draft_id, "name": name})


def start_batch_draft(project_name: str, description: str):
    from . import jobs
    project = fx.load(project_name)
    if len(description.strip()) < 30:
        raise BadRequest("Please describe the new work in at least a sentence or two")
    draft_id = f"{project.name}-batch-{time.strftime('%Y%m%d-%H%M%S')}"

    def work(job):
        d = drafts_dir() / draft_id
        shutil.copytree(project.dir, d, ignore=shutil.ignore_patterns(*SKIP_COPY))
        existing = {}
        for p in sorted(d.rglob("*")):
            rel = str(p.relative_to(d))
            if p.is_file() and (rel in ("project.yaml", "README.md") or rel.endswith("unit.yaml")
                                or "/tickets/" in rel) and not rel.startswith("seed/"):
                existing[rel] = fx.read_text(p)
        numbers = [int(m.group(1)) for rel in existing for m in [re.search(r"/tickets/batch-(\d+)/", rel)] if m]
        existing["__next_batch__"] = f"batch-{(max(numbers) if numbers else 0) + 1}"
        meta = {"id": draft_id, "mode": "batch", "name": project.name, "description": description,
                "created": time.time(), "status": "drafting", "files": [], "history": [],
                "next_batch": existing["__next_batch__"]}
        _save_meta(d, meta)
        reply = extract_json(call_claude(build_prompt("batch", project.name, description, existing), job))
        new_files = {k: v for k, v in reply["files"].items() if k not in existing or k.endswith("unit.yaml")}
        files = _write_files(d, new_files, BATCH_FILES)
        meta.update(status="ready", files=files, summary=reply.get("summary", ""))
        meta["history"].append({"at": time.time(), "action": "drafted"})
        _save_meta(d, meta)
        meta["check"] = check_draft(d)
        _save_meta(d, meta)
        job.log(f"Draft ready: {len(files)} files.")
        return {"draft_id": draft_id}

    return jobs.start_callable("draft", f"Draft a new batch for {project.name}", project.name, work,
                               {"draft_id": draft_id, "name": project.name})


def start_revision(draft_id: str, feedback: str):
    from . import jobs
    d = _draft_dir(draft_id)
    meta = _meta(d)

    def work(job):
        current = _files_of(d, meta)
        existing = None
        if meta["mode"] == "batch":
            existing = {str(p.relative_to(d)): fx.read_text(p) for p in sorted(d.rglob("*.yaml"))
                        if str(p.relative_to(d)) not in meta["files"] and not str(p.relative_to(d)).startswith("seed/")}
            existing["__next_batch__"] = meta.get("next_batch", "batch-N")
        prompt = build_prompt(meta["mode"], meta["name"], meta["description"], existing, current,
                              meta.get("check"), feedback)
        reply = extract_json(call_claude(prompt, job))
        pattern = PROJECT_FILES if meta["mode"] == "project" else BATCH_FILES
        for rel in meta["files"]:
            if rel not in reply["files"] and rel != "project.yaml" and (d / rel).is_file():
                (d / rel).unlink()
        files = _write_files(d, reply["files"], pattern)
        if meta["mode"] == "project":
            _force_project_identity(d, meta["name"])
            files = sorted(set(files) | {"project.yaml"})
        meta.update(files=files, summary=reply.get("summary", meta.get("summary", "")))
        meta["history"].append({"at": time.time(), "action": "revised", "feedback": feedback})
        _save_meta(d, meta)
        meta["check"] = check_draft(d)
        _save_meta(d, meta)
        job.log("Revision ready.")
        return {"draft_id": draft_id}

    return jobs.start_callable("draft", f"Revise draft {meta['name']}", meta["name"] if meta["mode"] == "batch"
                               else None, work, {"draft_id": draft_id, "name": meta["name"]})


def list_drafts() -> list:
    items = []
    for d in sorted(drafts_dir().iterdir(), reverse=True):
        if (d / "draft.json").is_file():
            m = _meta(d)
            items.append({k: m.get(k) for k in ("id", "mode", "name", "status", "created", "saved")}
                         | {"ready": (m.get("check") or {}).get("ready")})
    return items


def draft_detail(draft_id: str) -> dict:
    d = _draft_dir(draft_id)
    meta = _meta(d)
    files = {}
    for rel in meta.get("files", []):
        p = d / rel
        if p.is_file():
            entry = {"path": rel, "raw": fx.read_text(p)}
            if "/tickets/" in rel:
                try:
                    entry["ticket"] = dor_check.load_ticket(p)
                except Exception as exc:  # noqa: BLE001
                    entry["error"] = dor_check.describe_error(exc)
            files[rel] = entry
    rejected = fx.read_text(d / "rejected-files.txt").split()
    return {**meta, "dir": str(d), "files": files, "rejected": rejected}


def save_draft_file(draft_id: str, rel: str, raw: str) -> dict:
    d = _draft_dir(draft_id)
    meta = _meta(d)
    if rel not in meta.get("files", []):
        raise BadRequest("only files in the draft can be edited here")
    if rel.endswith((".yaml", ".yml")):
        try:
            yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise BadRequest(dor_check.describe_error(exc)) from exc
    (d / rel).write_text(raw if raw.endswith("\n") else raw + "\n")
    if meta["mode"] == "project" and rel == "project.yaml":
        _force_project_identity(d, meta["name"])
    meta["check"] = check_draft(d)
    meta["history"].append({"at": time.time(), "action": "edited", "file": rel})
    _save_meta(d, meta)
    return draft_detail(draft_id)


def save_draft(draft_id: str) -> dict:
    """Copy the draft into projects/. Returns the project name."""
    d = _draft_dir(draft_id)
    meta = _meta(d)
    if meta.get("saved"):
        raise BadRequest("this draft has already been saved")
    if meta["mode"] == "project":
        target = fx.projects_dir() / meta["name"]
        if target.exists():
            raise BadRequest(f"a project called {meta['name']} already exists")
        shutil.copytree(d, target, ignore=shutil.ignore_patterns("draft.json", "rejected-files.txt"))
    else:
        target = fx.projects_dir() / meta["name"]
        for rel in meta["files"]:
            dest = fx.safe_child(target, rel)
            if dest.exists() and not rel.endswith("unit.yaml"):
                raise BadRequest(f"{rel} already exists in the project")
        for rel in meta["files"]:
            dest = fx.safe_child(target, rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(d / rel, dest)
    meta["saved"] = time.time()
    meta["history"].append({"at": time.time(), "action": "saved"})
    _save_meta(d, meta)
    return {"project": meta["name"]}


def discard_draft(draft_id: str) -> dict:
    d = _draft_dir(draft_id)
    shutil.rmtree(d)
    return {"discarded": draft_id}
