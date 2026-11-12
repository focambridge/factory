# factory

A bespoke software factory for my own uses.

## Layout

```
config/factory.yaml          paths, gate limits, runner settings
schema/                      ticket JSON Schema and template
core/ticket_check/           Definition-of-Ready gate (dor_check.py)
core/runner/                 batch runner (run_batch.py) and builders
projects/<project>/
  project.yaml               workspace git repo, base branch, fixtures dir
  tickets/<batch>/           one directory per batch of tickets
  artifacts/<ticket-id>/     report.json, changes.patch, ticket.yaml, logs/
  runs/<run-id>.json         run record: gate result, ticket hashes, status
work/                        run worktrees and the demo workspace (git-ignored)
```

## Setup

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Check a batch

```
.venv/bin/python core/ticket_check/dor_check.py projects/<project>/tickets/<batch>
```

## Run a batch

```
.venv/bin/python core/runner/run_batch.py projects/<project>/tickets/<batch>
```

1. The gate validates the batch. If any ticket is not READY, nothing runs.
2. A git worktree is created on a new branch `factory/<batch>/<timestamp>` from
   the project's base branch. Your own checkout is not touched.
3. Tickets run in sequence order, each building on the previous ticket's commit.
   Each attempt: reset to the last good commit, build, check the changed files
   against `affected_paths` / `protected_paths`, run `technical.commands`, then
   check every acceptance criterion through its verification reference.
4. A passing ticket is committed (only the builder's changes) and its artifact is
   written. A ticket that fails `runner.max_attempts` attempts stops the batch.
5. A ticket with `human_approval_required: true` pauses the batch after its
   commit. Review it, then resume:
   `run_batch.py <batch> --resume <run-id> --approve <ticket-id>`

Commands run without cloud credentials, and commands matching
`runner.forbidden_commands` (terraform apply, and so on) are never run.
The factory never merges: review the branch and merge it yourself.

## Demo

```
projects/demo/setup_workspace.sh
.venv/bin/python core/runner/run_batch.py projects/demo/tickets/batch-1
```

DEMO-1 fails its first attempt and passes on the retry, DEMO-2 pauses for
approval, and DEMO-3 builds on both once resumed.

## Builders

`fixture` copies prepared files from `<project>/fixtures/<ticket-id>/`
(with optional `attempt-N/` subdirectories); `noop` changes nothing. The AI
builder will be another class in `core/runner/builders.py`.
