"""Project model shared by the gate and the runner.

A project is one git repository (the workspace) made of units: services,
which are largely self-contained, and integrations, which connect services.
A project can be as small as one service. The factory mirrors the repository:

    projects/<project>/project.yaml
    projects/<project>/services/<unit>/unit.yaml
    projects/<project>/services/<unit>/tickets/<batch>/*.yaml
    projects/<project>/integrations/<unit>/unit.yaml
    projects/<project>/integrations/<unit>/tickets/<batch>/*.yaml
    projects/<project>/artifacts/<ticket-id>/      written by the runner
    projects/<project>/runs/<run-id>.json          written by the runner

A unit's code lives in the same relative folder of the repository
(services/<unit>/) unless unit.yaml sets `path`; `path: .` lets a single-unit
project use the repository root. Ticket paths are relative to the unit folder.

A ticket counts as done once its commit, which carries a
`Factory-Ticket: <id>` trailer, is merged into the project's base branch.
"""
from __future__ import annotations

import copy
import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft202012Validator

KIND_DIRS = {"service": "services", "integration": "integrations"}
YAML_SUFFIXES = {".yaml", ".yml"}
UNIT_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


class ProjectError(Exception):
    pass


# ------------------------------------------------------------------ helpers

def resolve(root: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else root / p


def ticket_files(batch_dir: Path) -> list:
    """Ticket files directly inside a batch directory. Names starting with _ or . are skipped."""
    return sorted(p for p in batch_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in YAML_SUFFIXES and not p.name.startswith(("_", ".")))


def path_matches(path: str, pattern: str) -> bool:
    """Does a relative file path fall under a scope pattern (file, dir/ or glob)?"""
    pattern = pattern.strip()
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(c in pattern for c in "*?["):
        return fnmatch.fnmatchcase(path, pattern)
    return path == pattern or path.startswith(pattern + "/")


def escapes(path: str) -> bool:
    """True for a path that could leave its unit folder."""
    p = PurePosixPath(path.strip())
    return p.is_absolute() or ".." in p.parts or path.strip().startswith("~")


def is_git_repo(path: Path) -> bool:
    """True only if path is the top level of a git repository (not a folder inside one)."""
    if not path.is_dir():
        return False
    proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return proc.returncode == 0 and Path(proc.stdout.strip()).resolve() == path.resolve()


def merged_commit(workspace: Path, base_branch: str, ticket_id: str) -> str | None:
    """The commit on the base branch that carries the ticket's trailer, if any.

    Matches indented trailers too, so squash merges (which indent the original
    messages) still count. Fast-forward, merge and rebase keep the trailer as is.
    """
    proc = subprocess.run(
        ["git", "-C", str(workspace), "log", base_branch, "--format=%H", "-n", "1",
         f"--grep=^[[:space:]]*Factory-Ticket: {ticket_id}[[:space:]]*$"],
        capture_output=True, text=True)
    return (proc.stdout.strip() or None) if proc.returncode == 0 else None


def load_mapping(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ProjectError(f"{path}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ProjectError(f"{path}: must be a YAML mapping")
    return data


def validate(data: dict, schema_path: Path, source: Path) -> None:
    v = Draft202012Validator(json.loads(schema_path.read_text()))
    errors = sorted(v.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        detail = "; ".join(f"{'.'.join(map(str, e.absolute_path)) or '$'}: {e.message}" for e in errors)
        raise ProjectError(f"{source}: {detail}")


# ------------------------------------------------------------------- model

@dataclass
class Contract:
    name: str
    type: str
    path: str


@dataclass
class Unit:
    name: str
    kind: str
    dir: Path            # folder in the factory
    path: str            # folder in the repository; "" is the root
    packaging: str
    platform: str | None
    defaults: dict
    provides: list
    uses: list
    services: list
    source: Path

    @property
    def label(self) -> str:
        return f"{KIND_DIRS[self.kind]}/{self.name}"

    def batches(self) -> list:
        tickets = self.dir / "tickets"
        return sorted(p for p in tickets.iterdir() if p.is_dir()) if tickets.is_dir() else []

    def repo_dir(self, repo_root: Path) -> Path:
        return repo_root / self.path if self.path else repo_root

    def to_repo(self, rel: str) -> str:
        return f"{self.path}/{rel}" if self.path else rel

    def from_repo(self, repo_path: str) -> str | None:
        """A repository path relative to this unit, or None if it is outside the unit."""
        if not self.path:
            return repo_path
        prefix = self.path + "/"
        return repo_path[len(prefix):] if repo_path.startswith(prefix) else None


@dataclass
class Project:
    name: str
    dir: Path
    workspace: Path
    base_branch: str
    fixtures: Path
    platform: str
    stages: list
    units: dict
    source: Path

    @property
    def artifacts(self) -> Path:
        return self.dir / "artifacts"

    @property
    def runs(self) -> Path:
        return self.dir / "runs"

    def stage_index(self, unit_name: str) -> int | None:
        return next((i for i, stage in enumerate(self.stages) if unit_name in stage), None)

    def ticket_index(self) -> dict:
        """Every ticket id in the project -> list of (unit, file)."""
        index: dict = {}
        for unit in self.units.values():
            for batch in unit.batches():
                for f in ticket_files(batch):
                    tid = peek_id(f)
                    if tid:
                        index.setdefault(tid, []).append((unit, f))
        return index

    def consumers(self, unit_name: str, contract: str) -> list:
        return sorted(u.name for u in self.units.values()
                      if any(x.get("unit") == unit_name and x.get("contract") == contract for x in u.uses))


def peek_id(path: Path) -> str | None:
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return None
    tid = data.get("id") if isinstance(data, dict) else None
    return tid if isinstance(tid, str) else None


def load_unit(unit_dir: Path, project_platform: str, unit_schema: Path) -> Unit:
    source = unit_dir / "unit.yaml"
    data = load_mapping(source)
    validate(data, unit_schema, source)
    name, kind = unit_dir.name, data["kind"]
    if not UNIT_NAME.match(name):
        raise ProjectError(f"{unit_dir}: unit folder names use lowercase letters, digits and hyphens")
    folder = KIND_DIRS[kind]
    if unit_dir.parent.name != folder:
        raise ProjectError(f"{source}: a {kind} belongs under {folder}/, not {unit_dir.parent.name}/")
    raw = str(data.get("path", f"{folder}/{name}")).strip()
    path = "" if raw in (".", "./") else raw.strip("/")
    if path and escapes(path):
        raise ProjectError(f"{source}: path {raw!r} must stay inside the repository")
    contracts = data.get("contracts") or {}
    return Unit(
        name=name, kind=kind, dir=unit_dir, path=path,
        packaging=data.get("packaging", "none"),
        platform=data.get("platform") or (project_platform if kind == "integration" else None),
        defaults=data.get("defaults") or {},
        provides=[Contract(c["name"], c["type"], c["path"]) for c in contracts.get("provides") or []],
        uses=list(contracts.get("uses") or []),
        services=list(data.get("services") or []),
        source=source,
    )


def load_project(project_dir: Path, project_schema: Path, unit_schema: Path) -> Project:
    source = project_dir / "project.yaml"
    if not source.is_file():
        raise ProjectError(f"{source} not found")
    data = load_mapping(source)
    validate(data, project_schema, source)
    platform = data.get("platform", "none")
    units: dict = {}
    for folder in KIND_DIRS.values():
        base = project_dir / folder
        if not base.is_dir():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            if not (d / "unit.yaml").is_file():
                raise ProjectError(f"{d}: missing unit.yaml")
            unit = load_unit(d, platform, unit_schema)
            if unit.name in units:
                raise ProjectError(f"unit name {unit.name!r} is used by both {units[unit.name].label} and {unit.label}")
            units[unit.name] = unit
    if not units:
        raise ProjectError(f"{project_dir}: no units yet; add services/<name>/unit.yaml")
    return Project(
        name=data["name"], dir=project_dir,
        workspace=resolve(project_dir, data["workspace"]).resolve(),
        base_branch=data.get("base_branch", "main"),
        fixtures=resolve(project_dir, data.get("fixtures", "fixtures")),
        platform=platform, stages=data.get("stages") or [], units=units, source=source,
    )


def find_context(batch_dir: Path, project_schema: Path, unit_schema: Path):
    """(project, unit) for a batch inside a project, or None for a loose ticket directory."""
    batch_dir = batch_dir.resolve()
    if batch_dir.parent.name != "tickets":
        return None
    unit_dir = batch_dir.parent.parent
    if not (unit_dir / "unit.yaml").is_file() or unit_dir.parent.name not in KIND_DIRS.values():
        return None
    project_dir = unit_dir.parent.parent
    if not (project_dir / "project.yaml").is_file():
        raise ProjectError(f"{unit_dir} has a unit.yaml but {project_dir} has no project.yaml")
    project = load_project(project_dir, project_schema, unit_schema)
    return project, project.units[unit_dir.name]


def check_project(project: Project) -> tuple:
    """Project-wide consistency: repo paths, contracts, integrations, stages."""
    errors: list = []
    warnings: list = []
    units = project.units

    roots = [u.name for u in units.values() if not u.path]
    if roots and len(units) > 1:
        errors.append(f"unit {roots[0]} uses the repository root (path: .), so it must be the only unit")
    placed = sorted((u.path, u.name) for u in units.values() if u.path)
    for i, (p1, n1) in enumerate(placed):
        for p2, n2 in placed[i + 1:]:
            if p2 == p1 or p2.startswith(p1 + "/"):
                errors.append(f"units {n1} and {n2} overlap in the repository ({p1}, {p2})")

    for u in units.values():
        names = [c.name for c in u.provides]
        for dup in sorted({n for n in names if names.count(n) > 1}):
            errors.append(f"{u.name} provides contract {dup} more than once")
        for c in u.provides:
            if escapes(c.path):
                errors.append(f"{u.name}: contract {c.name} path {c.path!r} must stay inside the unit")
        for s in u.services:
            if s not in units:
                errors.append(f"integration {u.name}: service {s} does not exist")
            elif units[s].kind != "service":
                errors.append(f"integration {u.name}: {s} is not a service")
        for use in u.uses:
            target = units.get(use["unit"])
            label = f"{use['unit']}/{use['contract']}"
            if target is None:
                errors.append(f"{u.name} uses {label}: there is no unit {use['unit']}")
            elif target.name == u.name:
                errors.append(f"{u.name} uses its own contract {label}")
            elif target.kind != "service":
                errors.append(f"{u.name} uses {label}: only services provide contracts")
            elif use["contract"] not in {c.name for c in target.provides}:
                errors.append(f"{u.name} uses {label}, which {target.name} does not provide")
            elif u.kind == "service" and not any(
                    i.kind == "integration" and u.name in i.services and target.name in i.services
                    for i in units.values()):
                warnings.append(f"{u.name} uses {label}, but no integration includes both {u.name} and {target.name}")
        if u.kind == "integration":
            for s in u.services:
                for use in units[s].uses if s in units else []:
                    if use["unit"] in units and use["unit"] not in u.services:
                        warnings.append(f"integration {u.name} includes {s}, which uses "
                                        f"{use['unit']}/{use['contract']}, but not {use['unit']}")

    seen: dict = {}
    for i, stage in enumerate(project.stages):
        for name in stage:
            if name not in units:
                errors.append(f"stages: unknown unit {name}")
            elif name in seen:
                errors.append(f"stages: {name} is in stage {seen[name] + 1} and stage {i + 1}")
            else:
                seen[name] = i
    return errors, warnings


def effective_ticket(ticket: dict, unit: Unit | None) -> dict:
    """The ticket with its unit's technical defaults merged in."""
    if unit is None or not unit.defaults or not isinstance(ticket, dict):
        return ticket
    t = copy.deepcopy(ticket)
    tech = t.get("technical")
    if not isinstance(tech, dict):
        tech = {}
        t["technical"] = tech
    d = unit.defaults
    for key in ("stack", "target"):
        if key in d and key not in tech:
            tech[key] = copy.deepcopy(d[key])
    if "commands" in d:
        tech["commands"] = {**d["commands"], **(tech.get("commands") or {})}
    if d.get("constraints"):
        tech["constraints"] = copy.deepcopy(d["constraints"]) + list(tech.get("constraints") or [])
    return t
