# factory

A bespoke software factory for my own uses.

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

## Layout of the factory

```
config/factory.yaml     paths, gate limits, runner settings
schema/                 ticket, project and unit JSON Schemas; ticket template
core/project.py         project model shared by the gate and the runner
core/ticket_check/      Definition-of-Ready gate (dor_check.py)
core/runner/            batch runner (run_batch.py) and builders
work/                   run worktrees and demo workspaces (git-ignored)
```

## Setup

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

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

**demo**: the smallest shape, one Python service.

```
projects/demo/setup_workspace.sh
.venv/bin/python core/runner/run_batch.py projects/demo/services/calc/tickets/batch-1 --builder fixture
```

Leave out `--builder fixture` to have Claude write the code instead of the prepared fixtures.

DEMO-1 fails its first attempt and passes on the retry, DEMO-2 pauses for
approval, and DEMO-3 builds on both once resumed.

**demo-linked**: two services and an integration.

```
projects/demo-linked/setup_workspace.sh
.venv/bin/python core/runner/run_batch.py projects/demo-linked/services/pricing/tickets/batch-1 --builder fixture
.venv/bin/python core/runner/run_batch.py projects/demo-linked/services/checkout/tickets/batch-1 --builder fixture
.venv/bin/python core/runner/run_batch.py projects/demo-linked/integrations/local/tickets/batch-1 --builder fixture   # refused: not merged
# merge the two factory/... branches into main in work/demo-linked-workspace, then:
.venv/bin/python core/runner/run_batch.py projects/demo-linked/integrations/local/tickets/batch-1 --builder fixture
```

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
