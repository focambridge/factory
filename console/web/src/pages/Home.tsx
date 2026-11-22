import { Link } from "react-router-dom";
import { useApi } from "../hooks";
import { Explain, Loading, Note, RunChip, when } from "../components/ui";

export function Flow() {
  const steps: [string, string][] = [
    ["Describe", "Give the project a name and say what you want built, in your own words."],
    ["Plan", "Claude drafts the project: its parts (units) and a batch of small, testable tickets. You review and edit."],
    ["Check", "The gate checks every ticket is complete, small enough and testable before anything is built."],
    ["Build", "Claude builds the tickets one by one. The factory checks each one with its tests before committing it."],
    ["Review & merge", "You look at the result at pauses and at the end, then merge it into the project's code."],
  ];
  return (
    <div className="flow">
      {steps.map(([t, d], i) => (
        <div className="flow-step" key={t}>
          <span className="num">{i + 1}</span>
          <b>{t}</b>
          <p>{d}</p>
        </div>
      ))}
    </div>
  );
}

export function HomePage() {
  const { data, error } = useApi<any[]>("/api/projects");
  const { data: config } = useApi<any>("/api/config");
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Factory console</h1>
          <p>
            You write what you want; the factory turns it into small tickets, has Claude build them, and checks every
            one with tests before it counts. This console lets you do all of it from one place.
          </p>
        </div>
        <Link className="btn btn-primary" to="/new">
          + New project
        </Link>
      </div>
      <div className="card">
        <h2>How it works</h2>
        <Flow />
        <Explain title="Where does everything live?">
          <p>
            The <b>factory folder</b> ({config?.factory_root}) holds what you write and what the factory records:
            each project's tickets, settings, run records and the evidence for every ticket (artifacts).
          </p>
          <p>
            Each project's <b>code</b> lives in its own git repository (the workspace), usually next to the factory
            folder. Claude works on a separate copy (a worktree) for each run, so your code only changes when you
            merge. The <Link to="/guide">guide</Link> explains everything in more detail.
          </p>
        </Explain>
      </div>
      {config && !config.claude_installed && (
        <Note tone="warn">
          Claude Code (the <code>claude</code> command) was not found on this computer. Drafting and building need it:
          install it and sign in once by running <code>claude</code> in Terminal.
        </Note>
      )}
      <h2>Projects</h2>
      {error && <Note tone="bad">{error}</Note>}
      {!data && !error && <Loading />}
      {data && data.length === 0 && (
        <div className="card empty">
          <h3 style={{ color: "var(--text)" }}>No projects yet</h3>
          <p>Describe what you want built and Claude drafts your first project for you to review.</p>
          <Link className="btn btn-primary" to="/new">+ Create your first project</Link>
        </div>
      )}
      <div className="grid grid-2">
        {(data || []).map((p) => (
          <Link className="card project-card" to={`/p/${encodeURIComponent(p.name)}`} key={p.name}>
            <div className="spread">
              <h3 style={{ margin: 0 }}>{p.name}</h3>
              {p.last_run && <RunChip status={p.last_run.status} />}
            </div>
            {p.error ? (
              <Note tone="bad">{p.error}</Note>
            ) : (
              <>
                <p className="muted small" style={{ margin: "6px 0 10px" }}>
                  {p.description || "No description"}
                </p>
                <div className="row small">
                  <span>
                    <b>{p.merged_count}</b> of <b>{p.ticket_count}</b> tickets merged
                  </span>
                  <span className="muted">·</span>
                  <span>{p.units.map((u: any) => u.name).join(", ")}</span>
                  {p.last_run && (
                    <>
                      <span className="muted">·</span>
                      <span className="muted">last run {when(p.last_run.finished || p.last_run.started)}</span>
                    </>
                  )}
                </div>
                {!p.workspace_ready && <div className="small muted" style={{ marginTop: 6 }}>Repository not created yet</div>}
              </>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
