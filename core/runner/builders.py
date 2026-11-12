"""Builders produce the change for one ticket inside the run's worktree.

The runner calls build() once per attempt, after resetting the worktree to the
last good commit. A builder only edits files: the runner does all checking,
committing and recording. The AI builder will be another class here.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BuildContext:
    ticket: dict
    ticket_path: Path
    worktree: Path
    project_dir: Path
    fixtures_dir: Path
    attempt: int
    log_dir: Path
    feedback: list[str] = field(default_factory=list)  # why the previous attempt failed


@dataclass
class BuildOutcome:
    ok: bool
    message: str


class NoopBuilder:
    """Changes nothing. Every ticket fails its scope check: useful to test the stop rule."""

    name = "noop"

    def build(self, ctx: BuildContext) -> BuildOutcome:
        return BuildOutcome(True, "no changes made")


class FixtureBuilder:
    """Copies a prepared file tree over the worktree, from <fixtures>/<ticket-id>/.

    If that tree has attempt-N subdirectories, attempt N uses attempt-N, or the
    highest one below N. That lets you rehearse a failure followed by a fix.
    """

    name = "fixture"

    def build(self, ctx: BuildContext) -> BuildOutcome:
        root = ctx.fixtures_dir / str(ctx.ticket.get("id"))
        if not root.is_dir():
            return BuildOutcome(False, f"no fixture at {root}")
        numbered = sorted(
            int(p.name.split("-", 1)[1]) for p in root.glob("attempt-*")
            if p.is_dir() and p.name.split("-", 1)[1].isdigit()
        )
        source = root
        if numbered:
            chosen = max([n for n in numbered if n <= ctx.attempt] or [numbered[0]])
            source = root / f"attempt-{chosen}"
        copied = 0
        for f in sorted(source.rglob("*")):
            if f.is_file():
                target = ctx.worktree / f.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
                copied += 1
        return BuildOutcome(True, f"copied {copied} files from {source}")


BUILDERS = {b.name: b for b in (NoopBuilder(), FixtureBuilder())}
