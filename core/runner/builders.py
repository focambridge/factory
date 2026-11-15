"""Builders produce the change for one ticket inside the run's worktree.

The runner calls build() once per attempt, after resetting the worktree to the
last good commit. A builder only edits files: the runner does all checking,
committing and recording, so nothing a builder says about its own work counts.

    claude    Claude Code run headless (`claude -p`) in the unit folder
    fixture   copies prepared files: for testing the factory without Claude
    noop      changes nothing: for testing the stop rule
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class BuilderError(Exception):
    """A builder cannot run at all (missing tool, missing key). Stops the run before it starts."""


@dataclass
class BuildContext:
    ticket: dict
    ticket_path: Path
    worktree: Path       # repository root of the run
    unit_dir: Path       # the unit's folder in the worktree; ticket paths are relative to it
    project_dir: Path
    fixtures_dir: Path
    attempt: int
    log_dir: Path
    feedback: list = field(default_factory=list)  # why the previous attempt failed
    unit: object = None      # core.project.Unit
    project: object = None   # core.project.Project
    commands: dict = field(default_factory=dict)  # the ticket's technical.commands


@dataclass
class BuildOutcome:
    ok: bool
    message: str
    details: dict = field(default_factory=dict)   # e.g. cost_usd, turns, session_id


class NoopBuilder:
    """Changes nothing. Every ticket fails its scope check: useful to test the stop rule."""

    name = "noop"
    max_cost_per_ticket = None

    def __init__(self, options: dict | None = None, strip_env_prefixes: list | None = None):
        pass

    def preflight(self) -> None:
        pass

    def describe(self) -> str:
        return "noop"

    def build(self, ctx: BuildContext) -> BuildOutcome:
        return BuildOutcome(True, "no changes made")


class FixtureBuilder(NoopBuilder):
    """Copies a prepared file tree into the unit folder, from <fixtures>/<ticket-id>/.

    If that tree has attempt-N subdirectories, attempt N uses attempt-N, or the
    highest one below N. That lets you rehearse a failure followed by a fix.
    """

    name = "fixture"

    def describe(self) -> str:
        return "fixture"

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
                target = ctx.unit_dir / f.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
                copied += 1
        return BuildOutcome(True, f"copied {copied} files from {source}")


# ------------------------------------------------------------------ Claude

API_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class ClaudeBuilder:
    """Claude Code, run headless (`claude -p`) in the unit folder of the run's worktree.

    Authentication is chosen per run (config builder.auth, or run_batch --auth):
      subscription  the Claude Code login on this machine (run `claude` once and
                    sign in). Any API key in the environment is hidden from it.
      api_key       an Anthropic API key, from the environment variable named by
                    builder.claude.api_key_env, or from the macOS Keychain when
                    builder.claude.api_key_keychain_service is set. Costs are reported.

    Claude may edit files and run allow-listed commands; everything else is denied
    because headless Claude Code cannot ask for permission. It never commits.
    """

    name = "claude"

    def __init__(self, options: dict | None = None, strip_env_prefixes: list | None = None):
        options = options or {}
        c = options.get("claude") or {}
        self.auth = str(options.get("auth", "subscription"))
        self.command = str(c.get("command", "claude"))
        self.model = c.get("model")
        self.max_turns = int(c.get("max_turns", 40))
        self.timeout = int(c.get("timeout_seconds", 1200))
        cap = c.get("max_cost_usd_per_ticket")
        self.max_cost_per_ticket = float(cap) if cap else None
        self.allowed = [str(t) for t in c.get("allowed_tools") or []]
        self.disallowed = [str(t) for t in c.get("disallowed_tools") or []]
        self.api_key_env = str(c.get("api_key_env", "ANTHROPIC_API_KEY"))
        self.keychain_service = c.get("api_key_keychain_service") or None
        self.strip_env_prefixes = list(strip_env_prefixes or [])
        self._key: str | None = None

    def describe(self) -> str:
        return f"claude ({self.auth}{', model ' + self.model if self.model else ''})"

    # ---------------------------------------------------------- auth

    def preflight(self) -> None:
        if self.auth not in ("subscription", "api_key"):
            raise BuilderError(f"builder.auth must be subscription or api_key, not {self.auth!r}")
        if not shutil.which(self.command):
            raise BuilderError(f"{self.command!r} not found on PATH: install Claude Code "
                               f"(see https://docs.claude.com/en/docs/claude-code) and sign in once")
        if self.auth == "api_key":
            self._key = self._find_key()
            if not self._key:
                where = f"${self.api_key_env}"
                if self.keychain_service:
                    where += f" or the Keychain item {self.keychain_service!r}"
                raise BuilderError(f"auth is api_key but no key found in {where}")

    def _find_key(self) -> str | None:
        key = os.environ.get(self.api_key_env)
        if key:
            return key
        if self.keychain_service and shutil.which("security"):
            proc = subprocess.run(["security", "find-generic-password", "-s", self.keychain_service, "-w"],
                                  capture_output=True, text=True)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        return None

    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items()
               if not any(k.startswith(p) for p in self.strip_env_prefixes) and k not in API_KEY_VARS}
        if self.auth == "api_key" and self._key:
            env["ANTHROPIC_API_KEY"] = self._key
        return env

    # ---------------------------------------------------------- prompt

    def prompt(self, ctx: BuildContext) -> str:
        t = ctx.ticket
        unit = ctx.unit
        scope = t.get("scope") or {}
        affected = "\n".join(f"   - {p}" for p in scope.get("affected_paths") or [])
        protected = "\n".join(f"   - {p}" for p in scope.get("protected_paths") or []) or "   - (none listed)"
        commands = "\n".join(f"   - {name}: `{cmd}`" for name, cmd in ctx.commands.items()) or "   - (none)"
        parts = [
            "You are the builder in a software factory. Implement exactly one ticket, then stop.",
            "",
            "## Where you are",
            f"- Your working directory is the folder of unit `{unit.label if unit else '?'}`, "
            f"at `{(unit.path or '.') if unit else '.'}` in the project repository.",
            f"- The repository root is `{ctx.worktree}`. You may read anything in it.",
            "- It is a git worktree on a branch made for this run.",
            "",
            "## Rules",
            "1. Change only files matching these paths, relative to your working directory:",
            affected,
            "   Never change:",
            protected,
            "   Anything else you change is rejected and the attempt fails.",
            "2. Write the tests named in the acceptance criteria, with exactly those file paths and test names.",
            "3. Respect scope.out, technical.constraints and the contracts below.",
            "4. Check your work with these commands, run from your working directory, and fix failures:",
            commands,
            "5. Do not commit, push, change branches or otherwise change git state. Do not deploy anything.",
            "6. Do not ask questions. If the ticket cannot be done as written, change nothing and explain why.",
            "7. End with a short summary of what you changed.",
            "",
            "Every acceptance criterion is verified independently after you finish.",
        ]
        parts += self._contracts(ctx)
        parts += ["", "## Ticket", "```yaml", yaml.safe_dump(t, sort_keys=False).rstrip(), "```"]
        if ctx.feedback:
            parts += ["", f"## Attempt {ctx.attempt}: the previous attempt failed",
                      "The worktree was reset. Fix these problems:", ""]
            parts += [f"- {note}" for note in ctx.feedback]
        return "\n".join(parts) + "\n"

    def _contracts(self, ctx: BuildContext) -> list:
        unit, project = ctx.unit, ctx.project
        if unit is None or project is None or not (unit.provides or unit.uses):
            return []
        lines = ["", "## Contracts"]
        for c in unit.provides:
            lines.append(f"- This unit provides `{c.name}` ({c.type}) at `{c.path}`. "
                         f"Keep it accurate; other units depend on it.")
            lines += _file_block(ctx.unit_dir / c.path)
        for use in unit.uses:
            provider = project.units.get(use["unit"])
            contract = next((c for c in provider.provides if c.name == use["contract"]), None) if provider else None
            if contract is None:
                continue
            path = provider.repo_dir(ctx.worktree) / contract.path
            lines.append(f"- This unit uses `{use['unit']}/{contract.name}` ({contract.type}), "
                         f"at `{provider.to_repo(contract.path)}` in the repository. "
                         f"Depend only on this contract, never on {use['unit']}'s code.")
            lines += _file_block(path)
        return lines

    # ---------------------------------------------------------- run

    def build(self, ctx: BuildContext) -> BuildOutcome:
        ctx.unit_dir.mkdir(parents=True, exist_ok=True)
        prompt = self.prompt(ctx)
        (ctx.log_dir / "claude-prompt.md").write_text(prompt)
        allowed = self.allowed + [f"Bash({cmd})" for cmd in ctx.commands.values()]
        args = [self.command, "-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "acceptEdits", "--max-turns", str(self.max_turns)]
        if self.model:
            args += ["--model", str(self.model)]
        if allowed:
            args += ["--allowedTools", *allowed]
        if self.disallowed:
            args += ["--disallowedTools", *self.disallowed]
        try:
            proc = subprocess.run(args, input=prompt, cwd=ctx.unit_dir, env=self._env(),
                                  capture_output=True, text=True, timeout=self.timeout)
            out, err, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            (ctx.log_dir / "claude-stream.jsonl").write_text(out)
            return BuildOutcome(False, f"claude timed out after {self.timeout}s")
        (ctx.log_dir / "claude-stream.jsonl").write_text(out)
        if err.strip():
            (ctx.log_dir / "claude-stderr.log").write_text(err)

        result = None
        for line in out.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                result = event
        if result is None:
            return BuildOutcome(False, f"claude exited {code} without a result: {err.strip()[-500:] or 'no output'}")

        details = {
            "auth": self.auth,
            "model": self.model,
            "subtype": result.get("subtype"),
            "turns": result.get("num_turns"),
            "duration_ms": result.get("duration_ms"),
            "cost_usd": result.get("total_cost_usd"),
            "session_id": result.get("session_id"),
            "usage": result.get("usage"),
            "summary": str(result.get("result") or "")[-2000:],
        }
        cost = f", ${details['cost_usd']:.2f}" if isinstance(details["cost_usd"], (int, float)) else ""
        message = f"claude {details['subtype']}, {details['turns']} turns{cost}"
        # Running out of turns still leaves changes worth verifying; other errors do not.
        if result.get("is_error") and details["subtype"] != "error_max_turns":
            return BuildOutcome(False, f"{message}: {details['summary'][-300:]}", details)
        return BuildOutcome(True, message, details)


def _file_block(path: Path, limit: int = 20000) -> list:
    if not path.is_file():
        return ["  (the file does not exist yet)"]
    text = path.read_text(errors="replace")
    if len(text) > limit:
        text = text[:limit] + "\n... (truncated)"
    return ["  ```", *("  " + line for line in text.splitlines()), "  ```"]


BUILDERS = {cls.name: cls for cls in (ClaudeBuilder, FixtureBuilder, NoopBuilder)}


def make_builder(name: str, options: dict | None, strip_env_prefixes: list | None = None):
    if name not in BUILDERS:
        raise BuilderError(f"unknown builder {name!r}; available: {', '.join(sorted(BUILDERS))}")
    return BUILDERS[name](options, strip_env_prefixes)
