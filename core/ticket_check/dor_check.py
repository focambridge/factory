#!/usr/bin/env python3
"""Definition-of-Ready gate for factory tickets.

Checks a single ticket file, or a ticket directory as a batch. It runs the
mechanical part of the Definition of Ready: schema validation plus content and
size rules. In directory mode it also counts the tickets and checks that
sequence numbers and ids are unique and that dependencies respect the
processing order. Gaps in the sequence are allowed: only uniqueness matters,
so the order is always definite. Judgement checks belong to a separate reviewer agent or a
human.

Usage:
    python dor_check.py TICKET.yaml       [--repo PATH] [--config PATH] [--json]
    python dor_check.py TICKET_DIRECTORY  [--repo PATH] [--config PATH] [--json]

Paths and size limits come from config/factory.yaml in the factory root. Use
--config or the FACTORY_CONFIG environment variable to point at another file.

Directory mode reads every *.yaml / *.yml file directly inside the directory
(not subdirectories). Files whose names start with "_" or "." are skipped and
reported as skipped.

Exit codes, single file:
    0 READY, 1 NEEDS_INFO, 2 DECOMPOSE, 3 ERROR (unreadable or unparsable)
Exit codes, directory:
    0 every ticket is READY and the batch is consistent: safe to process
    1 at least one ticket is not READY, or the batch has errors: process nothing
    3 ERROR (path not found)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

FACTORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = FACTORY_ROOT / "config" / "factory.yaml"
YAML_SUFFIXES = {".yaml", ".yml"}
SIZE_ORDER = ["XS", "S", "M", "L", "XL"]

# Set from the config file by apply_config() before any check runs.
SCHEMA_PATH: Path
MAX_SIZE: str
MAX_CRITERIA: int
MAX_AFFECTED_PATHS: int
MAX_FILES_ESTIMATE: int
MAX_COMPONENTS: int
MAX_INTERFACES: int

AUTOMATED_METHODS = {"new_test", "existing_test", "static_check"}

# Placeholders are errors anywhere in the ticket.
PLACEHOLDER = re.compile(r"\b(TBD|TBC|TODO|FIXME|XXX)\b|\?\?\?")

# Vague language is a warning in outcomes and criteria; the reviewer decides.
VAGUE = re.compile(
    r"\b(etc|and so on|as needed|as appropriate|appropriate(ly)?|properly|correctly|"
    r"robust(ly)?|user[- ]friendly|intuitive|seamless(ly)?|fast|quick(ly)?|"
    r"efficient(ly)?|better|improved?|optimi[sz]ed?|various|several|"
    r"where possible|if possible|ideally|gracefully)\b",
    re.IGNORECASE,
)

GLOB_CHARS = set("*?[")


# ---------------------------------------------------------------- helpers

def normalise(value):
    """YAML turns bare dates into date objects; the schema expects strings."""
    if isinstance(value, dict):
        return {k: normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def walk_strings(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk_strings(value, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def as_int(value) -> int | None:
    """A usable sequence number, or None. YAML 'true' is not a number."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return None


def load_ticket(path: Path) -> dict:
    ticket = normalise(yaml.safe_load(path.read_text()))
    if not isinstance(ticket, dict):
        raise ValueError("ticket must be a YAML mapping")
    return ticket


def describe_error(exc: Exception) -> str:
    """One-line message, with a line number for YAML syntax errors."""
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        return f"YAML syntax error at line {mark.line + 1}: {getattr(exc, 'problem', exc)}"
    return str(exc)


# ------------------------------------------------------------------ config

def load_config(path: Path) -> dict:
    config = yaml.safe_load(path.read_text())
    if not isinstance(config, dict):
        raise ValueError(f"{path}: config must be a YAML mapping")
    return config


def resolve(root: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else root / p


def apply_config(config: dict, root: Path) -> None:
    """Set the module-level paths and limits. Missing keys are an error, not a silent default."""
    global SCHEMA_PATH, MAX_SIZE, MAX_CRITERIA, MAX_AFFECTED_PATHS, MAX_FILES_ESTIMATE
    global MAX_COMPONENTS, MAX_INTERFACES
    try:
        paths, gate = config["paths"], config["gate"]
        SCHEMA_PATH = resolve(root, paths["schema"])
        MAX_SIZE = gate["max_size"]
        MAX_CRITERIA = int(gate["max_acceptance_criteria"])
        MAX_AFFECTED_PATHS = int(gate["max_affected_paths"])
        MAX_FILES_ESTIMATE = int(gate["max_files_estimate"])
        MAX_COMPONENTS = int(gate["max_components"])
        MAX_INTERFACES = int(gate["max_interfaces"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"config is missing or has a malformed key: {exc}") from exc
    if MAX_SIZE not in SIZE_ORDER:
        raise ValueError(f"gate.max_size must be one of {SIZE_ORDER}, not {MAX_SIZE!r}")
    if not SCHEMA_PATH.is_file():
        raise ValueError(f"paths.schema does not exist: {SCHEMA_PATH}")
    validator.cache_clear()


@lru_cache(maxsize=1)
def validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


# ------------------------------------------------------- single-ticket checks

class Report:
    def __init__(self) -> None:
        self.needs_info: list[str] = []
        self.decompose: list[str] = []
        self.warnings: list[str] = []

    @property
    def verdict(self) -> str:
        # Decompose first: children get re-specified anyway.
        if self.decompose:
            return "DECOMPOSE"
        if self.needs_info:
            return "NEEDS_INFO"
        return "READY"

    def as_dict(self, ticket: dict) -> dict:
        return {
            "ticket": ticket.get("id"),
            "sequence": as_int(ticket.get("sequence")),
            "verdict": self.verdict,
            "decompose": self.decompose,
            "needs_info": self.needs_info,
            "warnings": self.warnings,
        }


def check_schema(ticket: dict, report: Report) -> None:
    for err in sorted(validator().iter_errors(ticket), key=lambda e: list(map(str, e.absolute_path))):
        where = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path)
        report.needs_info.append(f"schema: {where}: {err.message}")


def check_size(ticket: dict, report: Report) -> None:
    size = ticket.get("size") or {}
    estimate = size.get("estimate")
    if estimate in SIZE_ORDER and SIZE_ORDER.index(estimate) > SIZE_ORDER.index(MAX_SIZE):
        report.decompose.append(f"size {estimate} exceeds the maximum of {MAX_SIZE}")

    files = size.get("files_estimate")
    if isinstance(files, int) and files > MAX_FILES_ESTIMATE:
        report.decompose.append(f"files_estimate {files} exceeds {MAX_FILES_ESTIMATE}")

    criteria = ticket.get("acceptance_criteria") or []
    if len(criteria) > MAX_CRITERIA:
        report.decompose.append(f"{len(criteria)} acceptance criteria exceeds {MAX_CRITERIA}")

    paths = (ticket.get("scope") or {}).get("affected_paths") or []
    if len(paths) > MAX_AFFECTED_PATHS:
        report.decompose.append(f"{len(paths)} affected paths exceeds {MAX_AFFECTED_PATHS}")

    technical = ticket.get("technical") or {}
    components = technical.get("components") or []
    if len(components) > MAX_COMPONENTS:
        report.decompose.append(f"{len(components)} infrastructure components exceeds {MAX_COMPONENTS}")
    interfaces = technical.get("interfaces") or []
    if len(interfaces) > MAX_INTERFACES:
        report.decompose.append(f"{len(interfaces)} interfaces exceeds {MAX_INTERFACES}")


def check_content(ticket: dict, report: Report) -> None:
    for path, text in walk_strings(ticket):
        if PLACEHOLDER.search(text):
            report.needs_info.append(f"placeholder text at {path}: {text.strip()!r}")

    for q in ticket.get("open_questions") or []:
        report.needs_info.append(f"open question: {q}")

    risk = ticket.get("risk") or {}
    approval = bool(risk.get("human_approval_required"))

    criteria = [c for c in ticket.get("acceptance_criteria") or [] if isinstance(c, dict)]
    seen: set[str] = set()
    for c in criteria:
        cid = c.get("id", "?")
        if cid in seen:
            report.needs_info.append(f"duplicate criterion id {cid}")
        seen.add(cid)

        verification = c.get("verification") or {}
        method = verification.get("method")
        if method == "existing_test" and not verification.get("reference"):
            report.needs_info.append(f"{cid}: existing_test needs a reference to the test")
        if method == "manual" and not approval:
            report.needs_info.append(f"{cid}: manual verification requires risk.human_approval_required: true")

        for field in ("given", "when", "then"):
            match = VAGUE.search(str(c.get(field) or ""))
            if match:
                report.warnings.append(f"{cid}.{field}: vague term {match.group(0)!r}")

    if criteria and not any((c.get("verification") or {}).get("method") in AUTOMATED_METHODS for c in criteria):
        report.needs_info.append("no acceptance criterion is machine-verifiable")

    match = VAGUE.search(str((ticket.get("goal") or {}).get("outcome") or ""))
    if match:
        report.warnings.append(f"goal.outcome: vague term {match.group(0)!r}")

    if re.search(r"\band\b", str(ticket.get("title") or ""), re.IGNORECASE):
        report.warnings.append("title contains 'and': may bundle two outcomes")

    scope = ticket.get("scope") or {}
    overlap = set(map(str, scope.get("affected_paths") or [])) & set(map(str, scope.get("protected_paths") or []))
    for p in sorted(overlap):
        report.needs_info.append(f"path is both affected and protected: {p}")

    if ticket.get("type") == "bug" and not any(
        (c.get("verification") or {}).get("method") == "new_test" for c in criteria
    ):
        report.warnings.append("bug ticket: no new test, so nothing guards against regression")

    if risk.get("level") == "high":
        report.warnings.append("high risk: routes to human approval before merge")


def check_technical(ticket: dict, report: Report) -> None:
    technical = ticket.get("technical")
    if not isinstance(technical, dict):
        return  # the schema already reports it missing
    approval = bool((ticket.get("risk") or {}).get("human_approval_required"))
    kinds = {s.get("kind") for s in technical.get("stack") or [] if isinstance(s, dict)}
    commands = technical.get("commands") or {}
    criteria = [c for c in ticket.get("acceptance_criteria") or [] if isinstance(c, dict)]
    methods = {(c.get("verification") or {}).get("method") for c in criteria}

    for comp in technical.get("components") or []:
        if isinstance(comp, dict) and comp.get("action") == "delete" and not approval:
            report.needs_info.append(
                f"component {comp.get('name')!r} is deleted: requires risk.human_approval_required: true"
            )

    for iface in technical.get("interfaces") or []:
        if isinstance(iface, dict) and iface.get("action") == "remove":
            report.warnings.append(
                f"interface {iface.get('name')!r} is removed: check for callers outside affected_paths"
            )

    if "iac" in kinds and kinds & {"language", "framework"}:
        report.decompose.append("stack mixes infrastructure-as-code with application code: split into separate tickets")

    if "iac" in kinds and not ({"plan", "validate"} & set(commands)) and "static_check" not in methods:
        report.warnings.append("infrastructure change has no plan or validate command and no static_check criterion")

    if methods & {"new_test", "existing_test"} and "test" not in commands:
        report.warnings.append("criteria rely on tests but technical.commands has no 'test' command")


def check_repo(ticket: dict, repo: Path, report: Report) -> None:
    """Every affected path must match a file, or sit in an existing directory (new file)."""
    for pattern in (ticket.get("scope") or {}).get("affected_paths") or []:
        pattern = str(pattern)
        if any(repo.glob(pattern.rstrip("/") or ".")):
            continue
        literal = pattern
        for i, ch in enumerate(pattern):
            if ch in GLOB_CHARS:
                literal = pattern[:i]
                break
        parent = (repo / literal).parent if literal else repo
        if parent.is_dir():
            report.warnings.append(f"{pattern}: no existing match; assuming a new file")
        else:
            report.needs_info.append(f"{pattern}: does not resolve in the repository")


def check_ticket(ticket: dict, repo: Path | None) -> Report:
    report = Report()
    check_schema(ticket, report)
    check_size(ticket, report)
    check_content(ticket, report)
    check_technical(ticket, report)
    if repo:
        check_repo(ticket, repo, report)
    return report


# ------------------------------------------------------------ batch checks

def check_directory(directory: Path, repo: Path | None) -> dict:
    candidates = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in YAML_SUFFIXES)
    skipped = [p.name for p in candidates if p.name.startswith(("_", "."))]
    files = [p for p in candidates if not p.name.startswith(("_", "."))]

    errors: list[str] = []
    warnings: list[str] = []
    entries: list[dict] = []

    if not files:
        errors.append("no ticket files found")

    for path in files:
        try:
            ticket = load_ticket(path)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            errors.append(f"{path.name}: cannot be read as a ticket: {describe_error(exc)}")
            continue
        entries.append({"file": path.name, "ticket": ticket, "report": check_ticket(ticket, repo)})

    # Sequence numbers: unique, so the processing order is definite. Gaps are fine.
    by_seq: dict[int, list[str]] = defaultdict(list)
    for e in entries:
        seq = as_int(e["ticket"].get("sequence"))
        if seq is not None:
            by_seq[seq].append(e["file"])
    for seq, names in sorted(by_seq.items()):
        if len(names) > 1:
            errors.append(f"duplicate sequence {seq}: {', '.join(names)}")

    # Ticket ids: unique within the directory.
    by_id: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        tid = e["ticket"].get("id")
        if isinstance(tid, str):
            by_id[tid].append(e["file"])
    for tid, names in sorted(by_id.items()):
        if len(names) > 1:
            errors.append(f"duplicate id {tid}: {', '.join(names)}")

    # Dependencies must be processed before the tickets that need them.
    seq_of: dict[str, int | None] = {}
    for e in entries:
        tid = e["ticket"].get("id")
        if isinstance(tid, str) and tid not in seq_of:
            seq_of[tid] = as_int(e["ticket"].get("sequence"))
    for e in entries:
        t = e["ticket"]
        own = as_int(t.get("sequence"))
        label = t.get("id") or e["file"]
        for dep in (t.get("dependencies") or {}).get("blocked_by") or []:
            if not isinstance(dep, str):
                continue
            if dep not in seq_of:
                warnings.append(f"{label}: blocked_by {dep} is not in this directory; confirm it is done")
            elif own is not None and seq_of[dep] is not None and seq_of[dep] >= own:
                errors.append(
                    f"{label} (sequence {own}) is blocked by {dep} (sequence {seq_of[dep]}), "
                    f"which is not processed before it"
                )

    # Processing order: by sequence; tickets without a usable sequence last.
    entries.sort(key=lambda e: (as_int(e["ticket"].get("sequence")) is None,
                                as_int(e["ticket"].get("sequence")) or 0, e["file"]))
    tickets = [{"file": e["file"], **e["report"].as_dict(e["ticket"])} for e in entries]
    counts = Counter(t["verdict"] for t in tickets)
    ready = bool(tickets) and not errors and counts.get("READY", 0) == len(files)

    return {
        "directory": str(directory),
        "verdict": "READY" if ready else "NOT_READY",
        "ticket_count": len(files),
        "verdict_counts": dict(sorted(counts.items())),
        "errors": errors,
        "warnings": warnings,
        "skipped": skipped,
        "tickets": tickets,
    }


# ------------------------------------------------------------------ output

def print_ticket(result: dict, indent: str = "") -> None:
    for label in ("decompose", "needs_info", "warnings"):
        for item in result[label]:
            print(f"{indent}[{label}] {item}")


def print_directory(result: dict) -> None:
    print(f"{result['directory']}: {result['verdict']}")
    seqs = [t["sequence"] for t in result["tickets"] if t["sequence"] is not None]
    span = f", sequence {min(seqs)}-{max(seqs)}" if seqs else ""
    counts = ", ".join(f"{n} {v}" for v, n in result["verdict_counts"].items())
    print(f"  {result['ticket_count']} tickets{span}" + (f"; {counts}" if counts else ""))
    for item in result["errors"]:
        print(f"  [batch error] {item}")
    for item in result["warnings"]:
        print(f"  [batch warning] {item}")
    for item in result["skipped"]:
        print(f"  [skipped] {item}")
    if result["tickets"]:
        print("  processing order:")
    for t in result["tickets"]:
        seq = t["sequence"] if t["sequence"] is not None else "?"
        print(f"  {seq:>4}  {t['ticket'] or '?':<10} {t['verdict']:<10} {t['file']}")
        print_ticket(t, indent="          ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path, help="a ticket file or a ticket directory")
    parser.add_argument("--repo", type=Path, help="repository root, to check affected_paths")
    parser.add_argument("--config", type=Path, help="factory config file (default: config/factory.yaml)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    config_path = args.config or Path(os.environ.get("FACTORY_CONFIG", DEFAULT_CONFIG))
    try:
        # Relative paths in the config resolve against the factory root (the parent of config/).
        apply_config(load_config(config_path), config_path.resolve().parent.parent)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"ERROR: config {config_path}: {describe_error(exc)}", file=sys.stderr)
        return 3

    if args.path.is_dir():
        result = check_directory(args.path, args.repo)
        print(json.dumps(result, indent=2)) if args.json else print_directory(result)
        return 0 if result["verdict"] == "READY" else 1

    try:
        ticket = load_ticket(args.path)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"ERROR: {describe_error(exc)}", file=sys.stderr)
        return 3

    report = check_ticket(ticket, args.repo)
    result = report.as_dict(ticket)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['ticket']}: {result['verdict']}")
        print_ticket(result, indent="  ")
    return {"READY": 0, "NEEDS_INFO": 1, "DECOMPOSE": 2}[report.verdict]


if __name__ == "__main__":
    sys.exit(main())
