# Factory console

A web interface for the factory: list projects, read and edit tickets, draft new
projects with Claude, build batches, approve, merge, and see every output.

## Start it

From the factory folder:

```
.venv/bin/python console/server.py
```

It opens http://localhost:8765 in your browser. It only listens on this computer.
Stop it with Ctrl+C in the Terminal window.

Options: `--port 9000` to use another port, `--no-browser` to not open a window.

## What it does

- **Projects**: every project in `projects/`, with its units, batches and tickets.
- **Tickets**: each ticket in plain English with every part explained; edit the
  YAML and the gate re-checks it on save; the evidence from every build attempt
  (checks, logs, Claude's summary, the code changes).
- **New project**: give a name and a description; Claude drafts the project
  (units and a batch of tickets) following `console/backend/planning_guide.md`.
  Review, edit or ask for a revision, then save. Drafts live in `work/drafts/`.
- **New batch**: describe more work for an existing project; Claude drafts the
  tickets; you review and add them.
- **Build**: create the project's repository, run a batch (Claude, or the
  fixture / noop builders for testing), follow progress, approve at pauses,
  see why a ticket failed, merge finished work.
- **Outputs**: where the code, artifacts and settings are, with Show in Finder,
  a file browser for the project repository, and its recent history.
- **Guide**: how the factory works, its limits and where everything lives.

Everything it does goes through the same files and commands as the terminal
tools (`core/ticket_check/dor_check.py`, `core/runner/run_batch.py`), so you can
mix the console and the terminal freely.

## Layout

```
console/server.py            start command
console/backend/             Python API (standard library HTTP server)
  factory.py                 reads projects, tickets, runs, artifacts; edits files
  jobs.py                    background jobs: runs, resumes, merges, repository set-up
  drafts.py                  Claude drafting of projects and batches
  planning_guide.md          the rules Claude follows when drafting
  http.py                    routes
console/web/                 React app (Vite + TypeScript); dist/ is the built app
console/tests/               end-to-end API tests with a stand-in for Claude
```

## Changing the web app

The built app in `console/web/dist` is what the server shows, so you do not need
Node to use the console. To change the app:

```
cd console/web
npm install
npm run dev
```

`npm run dev` serves the app with live reload on http://localhost:5173 and
forwards API calls to the console server, which must be running. When done:
`npm run build`.

## Tests

```
.venv/bin/python -m pytest -q console/tests
```
