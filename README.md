# factory

A software factory driven by tickets. You describe what you want built; the
factory turns it into small, testable tickets, has Claude Code build them one at
a time, and checks every ticket with its own tests before it counts. You review
and merge the result. Everything can be done from a web console.

## Quick start

**You need:** a Mac or Linux machine, `git`, Python 3.10 or later, and
[Claude Code](https://docs.claude.com/en/docs/claude-code) signed in (run
`claude` once in Terminal and sign in with your Claude account). Node is not
needed to use the factory; only the projects it builds may need it.

```
git clone https://github.com/focambridge/factory.git
cd factory
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python console/server.py
```

The console opens at http://localhost:8765. Leave that Terminal window open
while you use it; Ctrl+C stops it.

The factory starts with no projects. **Make your first one:** click
**+ New project**, give it a name and describe what you want. Claude drafts the
project and its tickets (2 to 6 minutes); review, edit or ask for changes, save,
create its repository, and build it.

**Your projects are yours:** the `projects/` folder is not shared through git,
so the projects you make stay on your machine.

**Where things go:** each project's code is created in its own git repository
next to the factory folder (for example `../My_Project`). The factory folder
keeps the tickets, settings, run records and the evidence for every ticket.
The console's **How the factory works** page explains everything in detail.

## Factory console

The web interface for everything below: projects, tickets, drafting new projects
with Claude, building, approving, merging and outputs. See `console/README.md`.

## Projects, services and integrations

A project is **one git repository** made of units:

- **services**: largely self-contained pieces (a React front end, an AWS datastore, a messaging system)
- **integrations**: the wiring that connects services (docker compose, Kubernetes, or something else)

A project can be as small as a single service with no integration and no
containers, or many linked services. The factory mirrors the repository:

```
projects/<project>/
  project.yaml                     workspace repo, base branch, default platform, optional stages
  services/<unit>/unit.yaml        kind, packaging, technical defaults, contracts
  services/<unit>/tickets/<batch>/
  integrations/<unit>/unit.yaml    kind, the services it connects, platform
  integrations/<unit>/tickets/<batch>/
  artifacts/<ticket-id>/           report.json, changes.patch, ticket.yaml, logs/
  runs/<run-id>.json               run record
```

A unit's code lives in the same folder of the repository (`services/<unit>/`)
unless `unit.yaml` sets `path`. `path: .` lets a single-unit project use the
repository root. Ticket paths are relative to the unit folder, and a ticket can
never change files outside its unit.

**Contracts.** A service lists the contracts it `provides` (an OpenAPI spec, a
JSON Schema, an event schema...) and the ones it `uses` from other services.
Services never depend on each other's code, only on contracts. The gate refuses
a `uses` that nothing provides, warns when a service uses another but no
integration connects them, and warns when a ticket may change a contract that
other units use.

**Done means merged.** The factory never merges. A ticket counts as done for
other batches once its commit (trailer `Factory-Ticket: <id>`) is in the base
branch, whether by merge, fast-forward, rebase or squash. A ticket blocked by
one outside its batch is refused until that one is merged.

**Stages** (optional) give a build order, e.g. services first, then
integrations. The gate warns when an earlier stage has unmerged tickets.

## Starting a new project

```
cp -R templates/project projects/<project-name>
```

Then follow `projects/<project-name>/README.md`: point `project.yaml` at a git repo,
name the first unit, and write tickets from the example ticket in its `batch-1`.

## Layout of the factory

```
config/factory.yaml     paths, gate limits, runner settings
schema/                 ticket, project and unit JSON Schemas; ticket template
templates/project/      a project to copy for new projects
core/project.py         project model shared by the gate and the runner
core/ticket_check/      Definition-of-Ready gate (dor_check.py)
core/runner/            batch runner (run_batch.py) and builders
work/                   run worktrees and demo workspaces (git-ignored)
```

## Setup

See Quick start above. The terminal tools below do the same as the console.

The default builder is Claude, through the Claude Code CLI (`claude`). Install it
(https://docs.claude.com/en/docs/claude-code), then choose how it signs in, per run:

- `--auth subscription` (the default, `builder.auth` in config): run `claude` once
  and sign in with your Claude account. Usage counts against your plan.
- `--auth api_key`: set `ANTHROPIC_API_KEY` in your shell, or store the key in the
  macOS Keychain and name the item in `builder.claude.api_key_keychain_service`.
  Each ticket's report shows its cost.

The key never goes in the factory's files, and project commands never see it.

## Check a batch

```
.venv/bin/python core/ticket_check/dor_check.py projects/<project>/services/<unit>/tickets/<batch>
```

## Run a batch

```
.venv/bin/python core/runner/run_batch.py projects/<project>/services/<unit>/tickets/<batch>
```

1. The gate validates the batch and the project. If anything fails, nothing runs.
2. A git worktree is created on `factory/<unit>/<batch>/<timestamp>` from the
   base branch. Your own checkout is not touched.
3. Tickets run in sequence order, each building on the previous ticket's commit.
   Each attempt: reset to the last good commit, build, check the changed files
   stay inside the unit and its `affected_paths`, run `technical.commands` from
   the unit folder, then check every acceptance criterion.
4. A passing ticket is committed (only the builder's changes) and its artifact
   written. A ticket that fails `runner.max_attempts` attempts stops the batch.
5. A ticket with `human_approval_required: true` pauses the batch. Review it, then
   `run_batch.py <batch> --resume <run-id> --approve <ticket-id>`.
6. Review the branch and merge it into the base branch yourself.

Commands run without cloud credentials. Commands matching
`runner.forbidden_commands` (terraform apply, kubectl apply...) are never run,
except where `runner.allowed_commands` permits them, e.g. kubectl against a
local `kind-` or `k3d-` cluster context.

## Demos

The repository ships no projects. The console's tests include a small demo
project that builds with the fixture builder, without Claude. To try the
factory that way, copy it into `projects/`:

```
cp -R console/tests/fixture_project/demo projects/demo
```

Then in the console: open demo, **Create repository**, open `calc / batch-1`,
choose the **fixture** builder and **Build this batch**.

## Builders

- `claude` (default): Claude Code run headless in the unit folder of the run's
  worktree. Its prompt holds the ticket (with unit defaults), the unit's
  contracts and, on a retry, why the previous attempt failed. It may edit files
  and run the commands in `builder.claude.allowed_tools` plus the ticket's own
  commands; everything else is denied. It never commits. The prompt, Claude's
  output stream, turns and cost are saved in each attempt's logs and report.
  `max_cost_usd_per_ticket` stops further attempts once spent.
- `fixture`: copies prepared files from `<project>/fixtures/<ticket-id>/` into the
  unit folder (with optional `attempt-N/` subdirectories). For testing the factory.
- `noop`: changes nothing.

Whatever the builder, the runner verifies the result itself: scope, commands and
every acceptance criterion.
