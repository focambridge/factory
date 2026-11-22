"""End-to-end tests for the console API.

Each test session copies the factory into a temporary folder, starts the console
there on a free port with a stand-in for Claude (fake_claude.py), and talks to
it over HTTP. Your real projects are never touched.

Run from the factory folder:  .venv/bin/python -m pytest -q console/tests
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FACTORY = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).with_name("fake_claude.py")


@pytest.fixture(scope="session")
def console(tmp_path_factory):
    root = tmp_path_factory.mktemp("factory")
    for name in ("config", "core", "schema", "templates", "console", "requirements.txt"):
        src = FACTORY / name
        if src.is_dir():
            shutil.copytree(src, root / name, ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
        else:
            shutil.copy2(src, root / name)
    (root / "projects").mkdir()
    shutil.copytree(Path(__file__).with_name("fixture_project") / "demo", root / "projects" / "demo")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "FACTORY_CONSOLE_FAKE_CLAUDE": str(FAKE), "HOME": str(root / "home")}
    (root / "home").mkdir()
    proc = subprocess.Popen([sys.executable, str(root / "console" / "server.py"), "--no-browser", "--port", str(port)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/api/config")
            break
        except OSError:
            time.sleep(0.1)
    yield base, root
    proc.terminate()


def call(base, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait(base, job_id, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        _, job = call(base, "GET", f"/api/jobs/{job_id}")
        if job["status"] != "running":
            return job
        time.sleep(0.3)
    raise AssertionError("job did not finish")


def test_lists_projects(console):
    base, _ = console
    status, projects = call(base, "GET", "/api/projects")
    assert status == 200
    assert [p["name"] for p in projects] == ["demo"]
    assert projects[0]["ticket_count"] == 3


def test_ticket_detail_and_gate(console):
    base, _ = console
    status, t = call(base, "GET", "/api/projects/demo/units/calc/batches/batch-1/tickets/001-subtract.yaml")
    assert status == 200 and t["check"]["verdict"] == "READY"
    assert t["effective"]["technical"]["commands"]["test"] == "python -m pytest -q"


def test_edit_ticket_reruns_gate(console):
    base, root = console
    path = "/api/projects/demo/units/calc/batches/batch-1/tickets/003-value-range.yaml"
    _, t = call(base, "GET", path)
    status, saved = call(base, "PUT", path, {"raw": t["raw"].replace("estimate: XS", "estimate: XL")})
    assert status == 200 and saved["check"]["verdict"] == "DECOMPOSE"
    call(base, "PUT", path, {"raw": t["raw"]})
    status, bad = call(base, "PUT", path, {"raw": "id: [unclosed"})
    assert status == 400


def test_path_traversal_refused(console):
    base, _ = console
    status, _ = call(base, "GET", "/api/projects/demo/file?path=../../config/factory.yaml")
    assert status == 400


def test_build_approve_merge(console):
    base, _ = console
    job = wait(base, call(base, "POST", "/api/projects/demo/setup")[1]["id"])
    assert job["status"] == "succeeded"
    job = wait(base, call(base, "POST", "/api/projects/demo/units/calc/batches/batch-1/run", {"builder": "fixture"})[1]["id"])
    assert job["status"] == "paused" and job["exit_code"] == 2
    _, batch = call(base, "GET", "/api/projects/demo/units/calc/batches/batch-1")
    assert [t["status"] for t in batch["tickets"]] == ["built", "awaiting_approval", "not_built"]
    run_id = batch["latest_run"]["run_id"]
    job = wait(base, call(base, "POST", "/api/projects/demo/units/calc/batches/batch-1/resume",
                          {"run_id": run_id, "approve": ["DEMO-2"], "builder": "fixture"})[1]["id"])
    assert job["status"] == "succeeded"
    _, ws = call(base, "GET", "/api/projects/demo/workspace")
    assert len(ws["unmerged_branches"]) == 1
    job = wait(base, call(base, "POST", "/api/projects/demo/merge", {"branch": ws["unmerged_branches"][0]})[1]["id"])
    assert job["status"] == "succeeded"
    _, project = call(base, "GET", "/api/projects/demo")
    assert project["merged_count"] == 3


def test_draft_review_save(console):
    base, root = console
    status, err = call(base, "POST", "/api/drafts", {"name": "9bad", "description": "x" * 40})
    assert status == 400
    job = wait(base, call(base, "POST", "/api/drafts", {"name": "D900_Quiz",
                                                        "description": "A tiny quiz tool that greets people politely."})[1]["id"])
    assert job["status"] == "succeeded", job["lines"]
    draft_id = job["result"]["draft_id"]
    _, d = call(base, "GET", f"/api/drafts/{draft_id}")
    assert d["check"]["ready"] is True
    assert "../escape.txt" in d["rejected"]
    status, saved = call(base, "POST", f"/api/drafts/{draft_id}/save")
    assert status == 200 and saved["project"] == "D900_Quiz"
    assert (root / "projects" / "D900_Quiz" / "services" / "tool" / "unit.yaml").is_file()
    status, _ = call(base, "POST", f"/api/drafts/{draft_id}/save")
    assert status == 400


def test_open_refuses_outside(console):
    base, _ = console
    status, _ = call(base, "POST", "/api/open", {"path": "/etc"})
    assert status == 400


def test_empty_factory_starts(tmp_path):
    """With no projects folder at all, the console still starts and lists nothing."""
    root = tmp_path / "factory"
    for name in ("config", "core", "schema", "templates", "console"):
        shutil.copytree(FACTORY / name, root / name, ignore=shutil.ignore_patterns("node_modules", "__pycache__",
                                                                                    "fixture_project"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, str(root / "console" / "server.py"), "--no-browser", "--port", str(port)],
                            env={**os.environ, "FACTORY_CONSOLE_FAKE_CLAUDE": str(FAKE), "HOME": str(tmp_path)},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/api/config")
                break
            except OSError:
                time.sleep(0.1)
        assert call(base, "GET", "/api/projects") == (200, [])
        assert call(base, "GET", "/api/drafts")[0] == 200
        job = wait(base, call(base, "POST", "/api/drafts", {"name": "First_Project",
                                                            "description": "A tiny quiz tool that greets people politely."})[1]["id"])
        assert job["status"] == "succeeded", job["lines"]
        status, saved = call(base, "POST", f"/api/drafts/{job['result']['draft_id']}/save")
        assert status == 200 and (root / "projects" / "First_Project" / "project.yaml").is_file()
        assert [p["name"] for p in call(base, "GET", "/api/projects")[1]] == ["First_Project"]
    finally:
        proc.terminate()
