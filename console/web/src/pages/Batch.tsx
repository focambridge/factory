import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, batchPath, projectFileUrl, projectPath } from "../api";
import { Job, useApi } from "../hooks";
import { GateReport, TicketFindings } from "../components/GateReport";
import { JobPanel } from "../components/JobPanel";
import { FileViewer } from "../components/FileViewer";
import {
  CommandBox, Crumbs, ErrorNote, Explain, Loading, money, Note, PathRow, RunChip, StatusChip, VerdictChip,
} from "../components/ui";

export function BatchPage() {
  const { project = "", unit = "", batch = "" } = useParams();
  const navigate = useNavigate();
  const path = batchPath(project, unit, batch);
  const [jobId, setJobId] = useState<string | null>(null);
  const { data: b, error, reload } = useApi<any>(path, jobId ? 3000 : 0);
  const { data: config } = useApi<any>("/api/config");
  const { data: ws, reload: reloadWs } = useApi<any>(`${projectPath(project)}/workspace`);
  const [builder, setBuilder] = useState("");
  const [auth, setAuth] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const base = `/p/${encodeURIComponent(project)}`;
  const here = `${base}/u/${encodeURIComponent(unit)}/b/${encodeURIComponent(batch)}`;

  // Re-attach to a run that is already going (e.g. after a page reload).
  useEffect(() => {
    api.get<any[]>("/api/jobs").then((jobs) => {
      const live = jobs.find((j) => j.status === "running" && j.project === project && j.meta?.unit === unit && j.meta?.batch === batch);
      if (live) setJobId(live.id);
    });
  }, [project, unit, batch]);

  if (error) return <ErrorNote error={error} />;
  if (!b) return <Loading />;

  const run = b.latest_run;
  const opts = { builder: builder || undefined, auth: auth || undefined };
  const start = () =>
    api.post(`${path}/run`, opts).then((j) => { setErr(null); setJobId(j.id); }).catch((e) => setErr(e.message));
  const resume = (approve: string[]) =>
    api.post(`${path}/resume`, { run_id: run.run_id, approve, ...opts }).then((j) => setJobId(j.id)).catch((e) => setErr(e.message));
  const done = (_j: Job) => { reload(); reloadWs(); };
  const branchUnmerged = run?.branch && (ws?.unmerged_branches || []).includes(run.branch);
  const awaiting = b.tickets.find((t: any) => t.status === "awaiting_approval" && t.run_id === run?.run_id);
  const failed = run?.status === "failed" ? b.tickets.find((t: any) => t.status === "failed") : null;
  const running = !!jobId;

  const options = (
    <div className="row" style={{ marginBottom: 10 }}>
      <label className="small">
        Builder{" "}
        <select value={builder} onChange={(e) => setBuilder(e.target.value)}>
          <option value="">Claude (default)</option>
          <option value="fixture">fixture (prepared files, for testing)</option>
          <option value="noop">noop (changes nothing, for testing)</option>
        </select>
      </label>
      <label className="small">
        Sign-in{" "}
        <select value={auth} onChange={(e) => setAuth(e.target.value)}>
          <option value="">{config?.builder?.auth === "api_key" ? "API key (default)" : "My Claude login (default)"}</option>
          <option value="subscription">My Claude login</option>
          <option value="api_key">Anthropic API key</option>
        </select>
      </label>
    </div>
  );

  return (
    <div>
      <Crumbs items={[["Projects", "/"], [project, base], ["Tickets", `${base}/tickets`], [`${unit} / ${batch}`, null]]} />
      <div className="page-head">
        <div>
          <h1>{unit} / {batch}</h1>
          <p>{b.tickets.length} tickets, built in order. Check them, build them, review the result, then merge.</p>
        </div>
        <VerdictChip verdict={b.gate.verdict} />
      </div>

      {/* ---------- what to do next ---------- */}
      <div className="card">
        {running ? (
          <>
            <h2>Building</h2>
            <p className="card-sub">
              You can leave this page; the run carries on. Ticket statuses below update as each one finishes.
            </p>
            <JobPanel jobId={jobId} onDone={(j) => { done(j); setJobId(null); }} />
          </>
        ) : !b.workspace_ready ? (
          <>
            <h2>Create the repository first</h2>
            <p className="card-sub">This project's repository does not exist yet.</p>
            <Link className="btn btn-primary" to={base}>Go to the project to create it</Link>
          </>
        ) : run?.status === "paused" && awaiting ? (
          <Approval b={b} t={awaiting} run={run} project={project} here={here} onApprove={() => resume([awaiting.id])} options={options} />
        ) : failed ? (
          <Failure b={b} t={failed} project={project} unit={unit} batch={batch} here={here}
            branchUnmerged={branchUnmerged} run={run} onRetry={start} onMerged={done} options={options} />
        ) : run?.status === "completed" && branchUnmerged ? (
          <MergeCard project={project} branch={run.branch} onDone={done} />
        ) : b.gate.verdict !== "READY" ? (
          <>
            <h2>Fix the tickets before building</h2>
            <p className="card-sub">The gate found problems (listed below). Open a ticket to edit it; the check reruns when you save.</p>
          </>
        ) : b.tickets.every((t: any) => t.status === "merged") ? (
          <>
            <h2>All done</h2>
            <p className="card-sub">Every ticket in this batch is built and merged. See the results on the project's Outputs tab.</p>
            <Link className="btn" to={`${base}/outputs`}>Go to outputs</Link>
          </>
        ) : (
          <>
            <h2>Build this batch</h2>
            <p className="card-sub">
              Claude builds each ticket in order on a separate copy of the code, and the factory checks every one with
              its tests. Tickets already merged are skipped.
              {b.tickets.some((t: any) => t.approval) && " The run pauses for your review where a ticket asks for it."}
            </p>
            {options}
            <button className="btn btn-primary" onClick={start}>Build this batch</button>
            <Explain title="Prefer the terminal?">
              <CommandBox command={b.command} label="From the factory folder:" />
            </Explain>
          </>
        )}
        <ErrorNote error={err} />
      </div>

      {/* ---------- tickets ---------- */}
      <div className="card">
        <div className="spread">
          <h2>Tickets</h2>
          <button
            className="btn btn-sm"
            onClick={() => api.post(`${path}/tickets`).then((r) => navigate(`${here}/t/${encodeURIComponent(r.file)}?edit=1`))}
          >
            + Add a ticket
          </button>
        </div>
        <table>
          <thead>
            <tr><th style={{ width: 40 }}>#</th><th style={{ width: 80 }}>Id</th><th>Ticket and gate findings</th><th style={{ width: 130 }}>Gate</th><th style={{ width: 170 }}>Status</th></tr>
          </thead>
          <tbody>
            {b.tickets.map((t: any) => (
              <tr key={t.file} className="clickable" onClick={() => navigate(`${here}/t/${encodeURIComponent(t.file)}`)}>
                <td className="muted">{t.sequence}</td>
                <td className="ticket-id">{t.id}</td>
                <td>
                  {t.title}
                  {t.approval && <span className="chip tone-warn" style={{ marginLeft: 8 }}>pauses for review</span>}
                  <TicketFindings gate={t.gate} />
                </td>
                <td><VerdictChip verdict={t.gate?.verdict} /></td>
                <td><StatusChip status={t.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Gate check</h2>
        <GateReport gate={b.gate} />
      </div>

      {b.runs.length > 0 && (
        <div className="card">
          <h2>Runs of this batch</h2>
          <table>
            <tbody>
              {b.runs.map((r: any) => (
                <tr key={r.run_id}>
                  <td className="small">{r.run_id}</td>
                  <td><RunChip status={r.status} /></td>
                  <td className="small muted">{r.builder}</td>
                  <td className="small">{money(r.tickets.reduce((s: number, t: any) => s + (t.cost_usd || 0), 0))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Approval({ b, t, run, project, here, onApprove, options }: any) {
  const patch = `artifacts/${t.id}/changes.patch`;
  const code = run?.worktree ? (b.unit_repo_path ? `${run.worktree}/${b.unit_repo_path}` : run.worktree) : null;
  return (
    <div>
      <h2>Your review is needed: {t.id}</h2>
      <p className="card-sub">
        <b>{t.title}</b> is built and passed every automatic check. It asks for a person to look before the batch goes
        on. Read the changes below, and if it has a running app, try it (see the ticket's acceptance criteria for what
        to look for).
      </p>
      <div className="row" style={{ margin: "10px 0" }}>
        <Link className="btn" to={`${here}/t/${encodeURIComponent(t.file)}`}>Open the ticket and its report</Link>
      </div>
      {code && (
        <Explain title="Try the result before approving">
          <p>
            This run's copy of the code (with everything built so far) is here. Your own copy of the project is not
            changed until you merge.
          </p>
          <PathRow path={code} />
          <div style={{ marginTop: 8 }}>
            <CommandBox label="To go there in Terminal:" command={`cd "${code}"`} />
          </div>
          <p className="small muted" style={{ marginTop: 8 }}>
            Then start it the usual way for this project, for example <code>npm install && npm run dev</code> for a web
            app, or the project's README instructions.
          </p>
        </Explain>
      )}
      <FileViewer url={projectFileUrl(project, patch)} name="changes.patch" />
      <div className="divider" />
      {options}
      <div className="row">
        <button className="btn btn-good" onClick={onApprove}>Approve and continue the batch</button>
        <span className="small muted">Not happy? Leave it paused, edit the next tickets, or ask for help. Nothing is merged until you merge.</span>
      </div>
    </div>
  );
}

function Failure({ t, project, unit, batch, here, branchUnmerged, run, onRetry, onMerged, options }: any) {
  const { data: detail } = useApi<any>(`${batchPath(project, unit, batch)}/tickets/${encodeURIComponent(t.file)}`);
  const attempts = detail?.artifact?.attempts || [];
  const last = attempts[attempts.length - 1];
  const builtBefore = run.tickets.filter((x: any) => x.status === "done").map((x: any) => x.id);
  return (
    <div>
      <h2>The run stopped at {t.id}</h2>
      <p className="card-sub">
        <b>{t.title}</b> did not pass its checks after {attempts.length} attempt{attempts.length === 1 ? "" : "s"}.
      </p>
      {last?.summary && (
        <Note tone="warn">
          <b>Claude's explanation (last attempt):</b>
          <div style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{last.summary.slice(0, 1600)}</div>
        </Note>
      )}
      {last && (
        <div className="small" style={{ marginBottom: 10 }}>
          Failed checks:{" "}
          {[...(last.scope?.problems || []), ...last.commands.filter((c: any) => c.status !== "pass").map((c: any) => `${c.name} (${c.command})`),
            ...last.criteria.filter((c: any) => c.status === "fail").map((c: any) => c.id)].join("; ") || "see the report"}
        </div>
      )}
      <ol className="clean small">
        {builtBefore.length > 0 && branchUnmerged && (
          <li>
            Keep the work that passed ({builtBefore.join(", ")}): merge its branch first, so the next run skips it.
            <div style={{ margin: "6px 0" }}><MergeButton project={project} branch={run.branch} onDone={onMerged} /></div>
          </li>
        )}
        <li>
          Fix the ticket: often a file it needs is missing from "Files it may change", or a check is too strict.{" "}
          <Link to={`${here}/t/${encodeURIComponent(t.file)}?edit=1`}>Edit {t.id}</Link>
        </li>
        <li>Run the batch again.</li>
      </ol>
      {options}
      <button className="btn btn-primary" onClick={onRetry}>Run again</button>
    </div>
  );
}

function MergeButton({ project, branch, onDone }: { project: string; branch: string; onDone: (j: Job) => void }) {
  const [job, setJob] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (job) return <JobPanel jobId={job} onDone={onDone} />;
  return (
    <>
      <button className="btn btn-good btn-sm" onClick={() => api.post(`${projectPath(project)}/merge`, { branch }).then((j) => setJob(j.id)).catch((e) => setErr(e.message))}>
        Merge {branch}
      </button>
      <ErrorNote error={err} />
    </>
  );
}

function MergeCard({ project, branch, onDone }: { project: string; branch: string; onDone: (j: Job) => void }) {
  return (
    <div>
      <h2>Built: review and merge</h2>
      <p className="card-sub">
        Every ticket passed. The work is on the branch <code>{branch}</code>. Look at the result (each ticket's report and
        changes, or the code on the Outputs tab), then merge it into main. Merged tickets count as done.
      </p>
      <MergeButton project={project} branch={branch} onDone={onDone} />
    </div>
  );
}
