"""HTTP routing for the console API, plus serving the built web app."""
from __future__ import annotations

import json
import mimetypes
import re
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import drafts, factory as fx, jobs
from .factory import BadRequest, NotFound

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
TEXT_TYPES = {".md", ".txt", ".patch", ".log", ".yaml", ".yml", ".py", ".ts", ".tsx", ".js", ".jsx", ".css",
              ".html", ".jsonl", ".toml", ".cfg", ".ini", ".sh", ".csv"}

ROUTES = []


def route(method, pattern):
    regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def deco(fn):
        ROUTES.append((method, regex, fn))
        return fn
    return deco


# ----------------------------------------------------------------- routes

@route("GET", "/api/config")
def _config(req, q, body):
    return fx.public_config()


@route("GET", "/api/guide")
def _guide(req, q, body):
    return {"planning_guide": drafts.GUIDE.read_text()}


@route("GET", "/api/projects")
def _projects(req, q, body):
    return fx.list_projects()


@route("GET", "/api/projects/{p}")
def _project(req, q, body, p):
    return fx.project_detail(p)


@route("PUT", "/api/projects/{p}/project-yaml")
def _project_yaml(req, q, body, p):
    return fx.save_config_file(p, "project", body.get("raw", ""))


@route("PUT", "/api/projects/{p}/units/{u}/unit-yaml")
def _unit_yaml(req, q, body, p, u):
    return fx.save_config_file(p, "unit", body.get("raw", ""), u)


@route("POST", "/api/projects/{p}/units/{u}/batches")
def _new_batch(req, q, body, p, u):
    return fx.new_batch(p, u)


@route("GET", "/api/projects/{p}/units/{u}/batches/{b}")
def _batch(req, q, body, p, u, b):
    return fx.batch_detail(p, u, b)


@route("POST", "/api/projects/{p}/units/{u}/batches/{b}/tickets")
def _new_ticket(req, q, body, p, u, b):
    return fx.new_ticket(p, u, b)


@route("GET", "/api/projects/{p}/units/{u}/batches/{b}/tickets/{f}")
def _ticket(req, q, body, p, u, b, f):
    return fx.ticket_detail(p, u, b, f)


@route("PUT", "/api/projects/{p}/units/{u}/batches/{b}/tickets/{f}")
def _save_ticket(req, q, body, p, u, b, f):
    return fx.save_ticket(p, u, b, f, body.get("raw", ""))


@route("POST", "/api/projects/{p}/units/{u}/batches/{b}/run")
def _run(req, q, body, p, u, b):
    return jobs.start_run(p, u, b, body.get("builder") or None, body.get("auth") or None).view()


@route("POST", "/api/projects/{p}/units/{u}/batches/{b}/resume")
def _resume(req, q, body, p, u, b):
    return jobs.start_resume(p, u, b, body["run_id"], body.get("approve") or [], body.get("builder") or None,
                             body.get("auth") or None).view()


@route("POST", "/api/projects/{p}/setup")
def _setup(req, q, body, p):
    return jobs.start_setup(p).view()


@route("POST", "/api/projects/{p}/merge")
def _merge(req, q, body, p):
    return jobs.start_merge(p, body.get("branch", "")).view()


@route("GET", "/api/projects/{p}/workspace")
def _workspace(req, q, body, p):
    return fx.workspace_info(p)


@route("GET", "/api/projects/{p}/workspace/list")
def _workspace_list(req, q, body, p):
    return fx.workspace_list(p, q.get("path", ""))


@route("GET", "/api/projects/{p}/workspace/file")
def _workspace_file(req, q, body, p):
    return fx.workspace_file(p, q.get("path", ""))


@route("GET", "/api/projects/{p}/file")
def _project_file(req, q, body, p):
    return fx.project_file(p, q.get("path", ""))


@route("POST", "/api/projects/{p}/draft-batch")
def _draft_batch(req, q, body, p):
    return drafts.start_batch_draft(p, body.get("description", "")).view()


@route("GET", "/api/jobs")
def _jobs(req, q, body):
    return jobs.recent()


@route("GET", "/api/jobs/{j}")
def _job(req, q, body, j):
    return jobs.get(j).view(int(q.get("since", 0) or 0))


@route("GET", "/api/drafts")
def _drafts(req, q, body):
    return drafts.list_drafts()


@route("POST", "/api/drafts")
def _new_draft(req, q, body):
    return drafts.start_project_draft(body.get("name", "").strip(), body.get("description", "")).view()


@route("GET", "/api/drafts/{d}")
def _draft(req, q, body, d):
    return drafts.draft_detail(d)


@route("PUT", "/api/drafts/{d}/file")
def _draft_file(req, q, body, d):
    return drafts.save_draft_file(d, body.get("path", ""), body.get("raw", ""))


@route("POST", "/api/drafts/{d}/revise")
def _revise(req, q, body, d):
    return drafts.start_revision(d, body.get("feedback", "")).view()


@route("POST", "/api/drafts/{d}/save")
def _save_draft(req, q, body, d):
    return drafts.save_draft(d)


@route("DELETE", "/api/drafts/{d}")
def _discard(req, q, body, d):
    return drafts.discard_draft(d)


@route("POST", "/api/open")
def _open(req, q, body):
    return jobs.open_path(body.get("path", ""))


# ---------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    server_version = "FactoryConsole/1.0"

    def log_message(self, fmt, *args):  # quieter console
        if not str(args[0]).startswith(("GET /api/jobs/", "GET /assets/")):
            super().log_message(fmt, *args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        url = urlparse(self.path)
        path = unquote(url.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if not path.startswith("/api/"):
            if method == "GET":
                return self._static(path)
            return self._json({"error": "not found"}, 404)
        body = {}
        if method in ("POST", "PUT"):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._json({"error": "the request body is not valid JSON"}, 400)
        for m, regex, fn in ROUTES:
            match = regex.match(path)
            if m == method and match:
                try:
                    result = fn(self, query, body, **{k: unquote(v) for k, v in match.groupdict().items()})
                except NotFound as exc:
                    return self._json({"error": str(exc)}, 404)
                except (BadRequest, KeyError) as exc:
                    return self._json({"error": str(exc).strip("'\"")}, 400)
                except Exception as exc:  # noqa: BLE001
                    traceback.print_exc()
                    return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                if isinstance(result, Path):
                    return self._file(result)
                return self._json(result)
        return self._json({"error": "not found"}, 404)

    def _json(self, data, status=200):
        payload = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _file(self, path: Path, static: bool = False):
        suffix = path.suffix.lower()
        if static:
            ctype = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8",
                     ".svg": "image/svg+xml"}.get(suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        elif suffix in TEXT_TYPES or path.name in (".gitignore",):
            ctype = "text/plain; charset=utf-8"
        else:
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path):
        if not WEB_DIST.is_dir():
            msg = b"The web app is not built. Run: cd console/web && npm install && npm run build"
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(msg)
            return
        target = (WEB_DIST / path.lstrip("/")).resolve()
        if WEB_DIST.resolve() not in target.parents or not target.is_file():
            target = WEB_DIST / "index.html"
        self._file(target, static=True)
