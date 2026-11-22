import { useState } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { api, projectPath, workspaceFileUrl } from "../api";
import { useApi } from "../hooks";
import { KIND } from "../explain";
import { JobPanel } from "../components/JobPanel";
import { FileViewer } from "../components/FileViewer";
import {
  Chip, Crumbs, ErrorNote, Explain, Loading, Markdown, money, Note, PathRow, RunChip, StatusChip, useToast, when,
} from "../components/ui";

const TABS: [string, string][] = [
  ["", "Overview"],
  ["tickets", "Tickets"],
  ["runs", "Runs"],
  ["outputs", "Outputs"],
  ["settings", "Settings"],
];

export function ProjectPage() {
  const { project = "", tab = "" } = useParams();
  const { data: p, error, reload } = useApi<any>(projectPath(project));
  const base = `/p/${encodeURIComponent(project)}`;
  if (error) return <ErrorNote error={error} />;
  if (!p) return <Loading />;
  return (
    <div>
      <Crumbs items={[["Projects", "/"], [p.name, null]]} />
      <div className="page-head">
        <div>
          <h1>{p.name}</h1>
          <p>{p.description}</p>
        </div>
        <div className="row">
          <Chip tone="muted">{p.merged_count} of {p.ticket_count} tickets merged</Chip>
          {p.last_run && <RunChip status={p.last_run.status} />}
        </div>
      </div>
      {!p.workspace_ready && <SetupCard p={p} onDone={reload} />}
      <nav className="tabs">
        {TABS.map(([t, label]) => (
          <NavLink key={t} to={t ? `${base}/${t}` : base} end className={() => (tab === t ? "active" : "")}>
            {label}
          </NavLink>
        ))}
      </nav>
      {tab === "" && <Overview p={p} />}
      {tab === "tickets" && <Tickets p={p} reload={reload} />}
      {tab === "runs" && <Runs p={p} />}
      {tab === "outputs" && <Outputs p={p} />}
      {tab === "settings" && <Settings p={p} reload={reload} />}
    </div>
  );
}

function SetupCard({ p, onDone }: { p: any; onDone: () => void }) {
  const [job, setJob] = useState<string | null>(null);
  const toast = useToast();
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="card" style={{ borderColor: "#f3d79f" }}>
      <h2>Create the project's repository</h2>
      <p className="card-sub">
        The code for this project will live in its own git repository at <code>{p.workspace}</code>. It does not exist
        yet, so nothing can be built. Creating it takes a second{p.has_seed ? " and copies in the project's starting files" : ""}.
      </p>
      <ErrorNote error={err} />
      {!job ? (
        <button
          className="btn btn-primary"
          onClick={() => api.post(`${projectPath(p.name)}/setup`).then((j) => setJob(j.id)).catch((e) => setErr(e.message))}
        >
          Create repository
        </button>
      ) : (
        <JobPanel
          jobId={job}
          onDone={(j) => {
            if (j.status === "succeeded") {
              toast("Repository created");
              setTimeout(onDone, 300);
            }
          }}
        />
      )}
    </div>
  );
}

function Overview({ p }: { p: any }) {
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 340px" }}>
      <div>
        {(p.check.errors.length > 0 || p.check.warnings.length > 0) && (
          <Note tone={p.check.errors.length ? "bad" : "warn"}>
            Project check:
            <ul>
              {[...p.check.errors, ...p.check.warnings].map((m: string) => <li key={m}>{m}</li>)}
            </ul>
          </Note>
        )}
        <div className="card">
          {p.readme ? <Markdown text={p.readme} /> : <div className="empty">This project has no README.</div>}
        </div>
      </div>
      <div>
        <div className="card">
          <h3>Units</h3>
          <p className="small muted">The parts this project is made of.</p>
          {p.units.map((u: any) => (
            <div key={u.name} style={{ marginBottom: 14 }}>
              <div className="row">
                <b>{u.name}</b>
                <Chip tone="info" title={KIND[u.kind]}>{u.kind}</Chip>
              </div>
              <div className="small">{u.description}</div>
              <div className="small muted">Code folder: <code>{u.repo_path}</code></div>
              {u.defaults?.stack && (
                <div className="small muted">
                  Built with {u.defaults.stack.map((s: any) => s.name).join(", ")}
                </div>
              )}
              {u.provides.length > 0 && (
                <div className="small muted">Provides: {u.provides.map((c: any) => c.name).join(", ")}</div>
              )}
              {u.uses.length > 0 && (
                <div className="small muted">Uses: {u.uses.map((c: any) => `${c.unit}/${c.contract}`).join(", ")}</div>
              )}
            </div>
          ))}
        </div>
        <div className="card">
          <h3>Repository</h3>
          <PathRow path={p.workspace} canOpen={p.workspace_ready} />
          <div className="small muted" style={{ marginTop: 6 }}>
            {p.workspace_ready ? `Main branch: ${p.base_branch}` : "Not created yet"}
          </div>
        </div>
      </div>
    </div>
  );
}

function Tickets({ p, reload }: { p: any; reload: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const base = `/p/${encodeURIComponent(p.name)}`;
  const [drafting, setDrafting] = useState(false);
  const [desc, setDesc] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [job, setJob] = useState<string | null>(null);
  return (
    <div>
      <Explain title="How to read this page">
        Tickets are grouped by unit and batch, in the order the factory builds them. Click a ticket to read it in
        plain English, see its checks and evidence, or edit it. Open a batch to check it with the gate and build it.
      </Explain>
      {p.units.map((u: any) => (
        <div key={u.name}>
          {u.batches.length === 0 && (
            <div className="card"><div className="empty">No batches in {u.label} yet.</div></div>
          )}
          {u.batches.map((b: any) => {
            const merged = b.tickets.filter((t: any) => t.status === "merged").length;
            return (
              <div className="card" key={b.name}>
                <div className="spread">
                  <div>
                    <h2 style={{ marginBottom: 2 }}>
                      {u.name} / {b.name}
                    </h2>
                    <div className="small muted">
                      {b.tickets.length} tickets, {merged} merged
                    </div>
                  </div>
                  <Link className="btn btn-primary" to={`${base}/u/${encodeURIComponent(u.name)}/b/${encodeURIComponent(b.name)}`}>
                    Open batch: check and build
                  </Link>
                </div>
                <table style={{ marginTop: 10 }}>
                  <thead>
                    <tr>
                      <th style={{ width: 40 }}>#</th>
                      <th style={{ width: 80 }}>Id</th>
                      <th>Ticket</th>
                      <th style={{ width: 60 }}>Size</th>
                      <th style={{ width: 170 }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {b.tickets.map((t: any) => (
                      <tr
                        key={t.file}
                        className="clickable"
                        onClick={() =>
                          navigate(`${base}/u/${encodeURIComponent(u.name)}/b/${encodeURIComponent(b.name)}/t/${encodeURIComponent(t.file)}`)
                        }
                      >
                        <td className="muted">{t.sequence}</td>
                        <td className="ticket-id">{t.id || "?"}</td>
                        <td>
                          {t.title || <span className="muted">{t.error || t.file}</span>}
                          {t.approval && <span className="chip tone-warn" style={{ marginLeft: 8 }}>pauses for review</span>}
                        </td>
                        <td>{t.size}</td>
                        <td><StatusChip status={t.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })}
        </div>
      ))}
      <div className="card">
        <h2>Add more work</h2>
        <p className="card-sub">
          Describe what you want next and Claude drafts a new batch of tickets for this project, which you review before
          it is added. Or start an empty batch and write tickets yourself.
        </p>
        {!drafting ? (
          <div className="row">
            <button className="btn btn-primary" onClick={() => setDrafting(true)}>Draft a new batch with Claude</button>
            {p.units.map((u: any) => (
              <button
                key={u.name}
                className="btn"
                onClick={() =>
                  api.post(`${projectPath(p.name)}/units/${encodeURIComponent(u.name)}/batches`).then((r) => {
                    toast(`Created ${u.name}/${r.batch}`);
                    reload();
                  })
                }
              >
                Empty batch in {u.name}
              </button>
            ))}
          </div>
        ) : job ? (
          <JobPanel
            jobId={job}
            hint="Claude is reading the project and drafting tickets. This usually takes 2 to 6 minutes."
            onDone={(j) => j.result?.draft_id && navigate(`/drafts/${encodeURIComponent(j.result.draft_id)}`)}
          />
        ) : (
          <div>
            <label className="field">
              <span>What should the new batch do?</span>
              <textarea rows={5} value={desc} onChange={(e) => setDesc(e.target.value)}
                placeholder="e.g. Add a teacher view that lists each pupil's words and how far they got with each stage." />
            </label>
            <ErrorNote error={err} />
            <div className="row">
              <button
                className="btn btn-primary"
                disabled={desc.trim().length < 30}
                onClick={() =>
                  api.post(`${projectPath(p.name)}/draft-batch`, { description: desc }).then((j) => setJob(j.id)).catch((e) => setErr(e.message))
                }
              >
                Draft it
              </button>
              <button className="btn btn-ghost" onClick={() => setDrafting(false)}>Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Runs({ p }: { p: any }) {
  const base = `/p/${encodeURIComponent(p.name)}`;
  if (!p.runs.length) return <div className="card"><div className="empty">This project has not been run yet.</div></div>;
  return (
    <div className="card">
      <Explain title="What is a run?">
        A run builds one batch. It has its own branch and copy of the code. Its record shows what happened to each
        ticket, how many attempts it took and what it cost.
      </Explain>
      <table>
        <thead>
          <tr><th>Started</th><th>Batch</th><th>Status</th><th>Tickets</th><th>Cost</th></tr>
        </thead>
        <tbody>
          {p.runs.map((r: any) => {
            const unit = (r.unit || "").split("/").pop();
            const cost = r.tickets.reduce((s: number, t: any) => s + (t.cost_usd || 0), 0);
            return (
              <tr key={r.run_id}>
                <td className="small">{when(r.started)}</td>
                <td>
                  <Link to={`${base}/u/${encodeURIComponent(unit)}/b/${encodeURIComponent(r.batch)}`}>
                    {unit} / {r.batch}
                  </Link>
                  <div className="small muted">{r.builder}</div>
                </td>
                <td><RunChip status={r.status} /></td>
                <td className="small">
                  {r.tickets.map((t: any) => (
                    <div key={t.id}>
                      <span className="ticket-id">{t.id}</span> {t.status.replace("_", " ")}
                      {t.attempts ? `, ${t.attempts} attempt${t.attempts > 1 ? "s" : ""}` : ""}
                    </div>
                  ))}
                </td>
                <td className="small">{money(cost)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Outputs({ p }: { p: any }) {
  const { data: ws, reload } = useApi<any>(`${projectPath(p.name)}/workspace`);
  const [folder, setFolder] = useState("");
  const { data: listing, error: listErr } = useApi<any>(
    p.workspace_ready ? `${projectPath(p.name)}/workspace/list?path=${encodeURIComponent(folder)}` : null,
  );
  const [file, setFile] = useState<string | null>(null);
  const [mergeJob, setMergeJob] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div>
      <div className="card">
        <h2>Where things are</h2>
        <div className="stack">
          <PathRow label="The project's code (its git repository)" path={p.workspace} canOpen={p.workspace_ready} />
          {(ws?.units || []).map((u: any) => (
            <PathRow key={u.name} label={`Code for unit ${u.name}`} path={u.path} canOpen={p.workspace_ready} />
          ))}
          <PathRow label="Evidence for every ticket (reports, changes, logs)" path={`${p.dir}/artifacts`} />
          <PathRow label="Tickets and settings" path={p.dir} />
        </div>
      </div>

      {ws?.ready && (
        <div className="card">
          <h2>Waiting to be merged</h2>
          <p className="card-sub">
            Finished runs leave their work on a factory branch. Merging it puts the work into {ws.base_branch}, and its
            tickets then count as done.
          </p>
          {ws.unmerged_branches.length === 0 ? (
            <div className="small muted">Nothing waiting. Everything built has been merged.</div>
          ) : (
            ws.unmerged_branches.map((b: string) => (
              <div className="spread" key={b} style={{ marginBottom: 8 }}>
                <code>{b}</code>
                <button
                  className="btn btn-good btn-sm"
                  disabled={!!mergeJob}
                  onClick={() => api.post(`${projectPath(p.name)}/merge`, { branch: b }).then((j) => setMergeJob(j.id)).catch((e) => setErr(e.message))}
                >
                  Merge into {ws.base_branch}
                </button>
              </div>
            ))
          )}
          <ErrorNote error={err} />
          {mergeJob && <JobPanel jobId={mergeJob} onDone={() => { reload(); setMergeJob(null); }} />}
          {ws.dirty && <Note tone="warn">The repository has uncommitted changes. Merging may fail until they are committed or removed.</Note>}
        </div>
      )}

      {p.workspace_ready && (
        <div className="card">
          <h2>Browse the code and outputs</h2>
          <p className="card-sub">
            Files in the project's repository, including anything its tools have written (for example an <code>out</code> folder).
          </p>
          <div className="grid" style={{ gridTemplateColumns: "300px minmax(0,1fr)" }}>
            <div>
              <div className="small muted" style={{ marginBottom: 6 }}>
                <a href="#" onClick={(e) => { e.preventDefault(); setFolder(""); }}>repository</a>
                {folder && folder.split("/").map((part, i, arr) => (
                  <span key={i}>
                    {" / "}
                    <a href="#" onClick={(e) => { e.preventDefault(); setFolder(arr.slice(0, i + 1).join("/")); }}>{part}</a>
                  </span>
                ))}
              </div>
              <ErrorNote error={listErr} />
              {(listing?.entries || []).map((e: any) => (
                <div key={e.path} className="file-row" onClick={() => (e.dir ? setFolder(e.path) : setFile(e.path))}>
                  <span className="icon">{e.dir ? "📁" : "📄"}</span>
                  {e.name}
                </div>
              ))}
              {listing && listing.entries.length === 0 && <div className="small muted">Empty folder</div>}
              {listing && <div style={{ marginTop: 8 }}><PathRow path={listing.abs} /></div>}
            </div>
            <div>
              {file ? (
                <FileViewer url={workspaceFileUrl(p.name, file)} name={file} onClose={() => setFile(null)} />
              ) : (
                <div className="empty">Choose a file to view it here.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {ws?.log && (
        <div className="card">
          <h2>Recent history on {ws.base_branch}</h2>
          <table>
            <tbody>
              {ws.log.map((c: any) => (
                <tr key={c.commit}>
                  <td className="ticket-id" style={{ width: 90 }}>{c.commit}</td>
                  <td>{c.subject}</td>
                  <td className="small muted" style={{ width: 140 }}>{c.when}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function YamlFileEditor({ title, help, initial, onSave }: {
  title: string; help: string; initial: string; onSave: (raw: string) => Promise<any>;
}) {
  const [raw, setRaw] = useState(initial);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();
  const changed = raw !== initial;
  return (
    <div className="card">
      <h2>{title}</h2>
      <p className="card-sub">{help}</p>
      <textarea className="code" style={{ minHeight: 300 }} value={raw} onChange={(e) => setRaw(e.target.value)} spellCheck={false} />
      <ErrorNote error={err} />
      <div className="row" style={{ marginTop: 8 }}>
        <button
          className="btn btn-primary"
          disabled={!changed}
          onClick={() => onSave(raw).then(() => { setErr(null); toast("Saved"); }).catch((e) => setErr(e.message))}
        >
          Save
        </button>
        {changed && <button className="btn btn-ghost" onClick={() => setRaw(initial)}>Undo changes</button>}
      </div>
    </div>
  );
}

function Settings({ p, reload }: { p: any; reload: () => void }) {
  return (
    <div>
      <Note tone="info">
        These files control the project. A save is refused if the result would not load, so you cannot break the
        project by accident.
      </Note>
      <YamlFileEditor
        title="project.yaml"
        help="The project's name, where its repository is, its main branch and (optionally) the build order of its units."
        initial={p.project_yaml}
        onSave={(raw) => api.put(`${projectPath(p.name)}/project-yaml`, { raw }).then(reload)}
      />
      {p.units.map((u: any) => (
        <YamlFileEditor
          key={u.name}
          title={`${u.label}/unit.yaml`}
          help="This unit's defaults, which every ticket in it inherits: what it is built with, where it runs, the commands that check every ticket, and rules all tickets follow."
          initial={u.unit_yaml}
          onSave={(raw) => api.put(`${projectPath(p.name)}/units/${encodeURIComponent(u.name)}/unit-yaml`, { raw }).then(reload)}
        />
      ))}
    </div>
  );
}
