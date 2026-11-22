import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../hooks";
import { TicketView } from "../components/TicketView";
import { TicketFindings } from "../components/GateReport";
import { JobPanel } from "../components/JobPanel";
import { Chip, Crumbs, ErrorNote, Explain, Loading, Markdown, Note, useToast, VerdictChip } from "../components/ui";

export function DraftPage() {
  const { draftId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const path = `/api/drafts/${encodeURIComponent(draftId)}`;
  const [job, setJob] = useState<string | null>(null);
  const { data: d, error, reload, setData } = useApi<any>(path);
  const [feedback, setFeedback] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  // If a draft or revision is still being written, follow its job.
  useEffect(() => {
    api.get<any[]>("/api/jobs").then((jobs) => {
      const live = jobs.find((j) => j.status === "running" && j.meta?.draft_id === draftId);
      if (live) setJob(live.id);
    });
  }, [draftId]);

  if (error) return <ErrorNote error={error} />;
  if (!d) return <Loading />;
  const tickets = Object.values(d.files).filter((f: any) => f.ticket || f.path.includes("/tickets/"))
    .sort((a: any, b: any) => a.path.localeCompare(b.path)) as any[];
  const others = Object.values(d.files).filter((f: any) => !f.path.includes("/tickets/")) as any[];
  const verdictOf = (rel: string) => {
    for (const b of d.check?.batches || []) {
      for (const t of b.tickets) if (`${b.path}/${t.file}` === rel) return t;
    }
    return null;
  };
  const ready = d.check?.ready;

  return (
    <div>
      <Crumbs items={[["Projects", "/"], [`Draft: ${d.name}${d.mode === "batch" ? " (new batch)" : ""}`, null]]} />
      <div className="page-head">
        <div>
          <h1>{d.mode === "batch" ? `New batch for ${d.name}` : `Draft: ${d.name}`}</h1>
          <p>
            Review what Claude planned. Read each ticket, edit anything, or tell Claude what to change. Nothing is added
            to the factory until you save.
          </p>
        </div>
        {d.saved ? <Chip tone="good">Saved</Chip> : <Chip tone={ready ? "good" : "warn"}>{ready ? "Passes the gate" : "Needs attention"}</Chip>}
      </div>

      {job && (
        <div className="card">
          <JobPanel jobId={job} hint="Claude is writing the draft. This usually takes 2 to 6 minutes."
            onDone={() => { setJob(null); reload(); }} />
        </div>
      )}

      {d.status === "drafting" && !job && <Note tone="warn">This draft was not finished (Claude may have failed). Check Activity, or discard it and try again.</Note>}

      {d.summary && (
        <div className="card">
          <h2>Claude's plan</h2>
          <p>{d.summary}</p>
          {d.check?.project_error && <Note tone="bad">The project settings do not load: {d.check.project_error}</Note>}
          {(d.check?.batches || []).map((b: any) => (
            <div key={b.path} className="row small" style={{ marginBottom: 4 }}>
              <VerdictChip verdict={b.verdict} /> <code>{b.path}</code> {b.tickets.length} tickets
              {b.errors.length > 0 && <span style={{ color: "var(--bad)" }}>{b.errors.join("; ")}</span>}
            </div>
          ))}
          {d.rejected?.length > 0 && (
            <Note tone="muted">Ignored files Claude should not write: {d.rejected.join(", ")}</Note>
          )}
        </div>
      )}

      {tickets.length > 0 && <h2>Tickets ({tickets.length})</h2>}
      {tickets.map((f: any) => {
        const v = verdictOf(f.path);
        return (
          <div className="card" key={f.path}>
            <div className="spread">
              <code className="small">{f.path}</code>
              <div className="row">
                {v && <VerdictChip verdict={v.verdict} />}
                {!d.saved && <button className="btn btn-sm" onClick={() => setEditing(editing === f.path ? null : f.path)}>{editing === f.path ? "Close editor" : "Edit"}</button>}
              </div>
            </div>
            {v && v.verdict !== "READY" && <Note tone="warn">Gate findings:<TicketFindings gate={v} /></Note>}
            {editing === f.path ? (
              <FileEditor raw={f.raw} onSave={(raw) => api.put(`${path}/file`, { path: f.path, raw }).then((nd) => { setData(nd); setEditing(null); toast("Saved and checked"); })} />
            ) : f.ticket ? (
              <details>
                <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                  {f.ticket.id}: {f.ticket.title}
                </summary>
                <div style={{ marginTop: 10 }}><TicketView ticket={f.ticket} /></div>
              </details>
            ) : (
              <Note tone="bad">{f.error || "Cannot read this ticket"}</Note>
            )}
          </div>
        );
      })}

      {others.length > 0 && (
        <div className="card">
          <h2>Other files</h2>
          <p className="card-sub">Project settings, unit defaults, the README, and the files the repository starts with.</p>
          {others.map((f: any) => (
            <details key={f.path} style={{ marginBottom: 8 }}>
              <summary style={{ cursor: "pointer" }}><code>{f.path}</code></summary>
              <div style={{ marginTop: 8 }}>
                {f.path.endsWith(".md") && editing !== f.path ? (
                  <div className="card" style={{ boxShadow: "none" }}><Markdown text={f.raw} /></div>
                ) : editing !== f.path ? (
                  <pre>{f.raw}</pre>
                ) : null}
                {!d.saved && (editing === f.path ? (
                  <FileEditor raw={f.raw} onSave={(raw) => api.put(`${path}/file`, { path: f.path, raw }).then((nd) => { setData(nd); setEditing(null); toast("Saved"); })} />
                ) : (
                  <button className="btn btn-sm" style={{ marginTop: 6 }} onClick={() => setEditing(f.path)}>Edit</button>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}

      {!d.saved && d.status === "ready" && !job && (
        <>
          <div className="card">
            <h2>Ask Claude to change it</h2>
            <p className="card-sub">Say what you want different. Claude revises the whole draft and the gate checks it again.</p>
            <textarea rows={4} value={feedback} onChange={(e) => setFeedback(e.target.value)}
              placeholder="e.g. Use Python instead of React; split ticket 3 into two; add a ticket for exporting to PDF." />
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn" disabled={feedback.trim().length < 5}
                onClick={() => api.post(`${path}/revise`, { feedback }).then((j) => { setJob(j.id); setFeedback(""); }).catch((e) => setErr(e.message))}>
                Revise with Claude
              </button>
            </div>
          </div>
          <div className="card">
            <h2>Save</h2>
            <p className="card-sub">
              {d.mode === "batch"
                ? `Adds the new tickets to ${d.name}.`
                : `Adds ${d.name} to the factory and the menu. Next you create its repository and build it.`}
            </p>
            {!ready && <Note tone="warn">The gate is not happy yet. You can save and fix the tickets later, but the batch will not build until they pass.</Note>}
            <ErrorNote error={err} />
            <div className="row">
              <button className="btn btn-primary"
                onClick={() => api.post(`${path}/save`).then((r) => { toast("Saved"); navigate(d.mode === "batch" ? `/p/${encodeURIComponent(r.project)}/tickets` : `/p/${encodeURIComponent(r.project)}`); }).catch((e) => setErr(e.message))}>
                {d.mode === "batch" ? "Add these tickets to the project" : "Save the project"}
              </button>
              <button className="btn btn-danger"
                onClick={() => { if (window.confirm("Discard this draft?")) api.del(path).then(() => navigate("/")); }}>
                Discard draft
              </button>
            </div>
            <Explain title="Where does it go?">
              The files are copied into the factory's <code>projects/{d.name}</code> folder. The draft itself is kept in
              <code> work/drafts</code> until you discard it.
            </Explain>
          </div>
        </>
      )}
      {d.saved && <Note tone="good">This draft has been saved. <a href={`#/p/${encodeURIComponent(d.name)}`}>Go to the project</a>.</Note>}
    </div>
  );
}

function FileEditor({ raw, onSave }: { raw: string; onSave: (raw: string) => Promise<any> }) {
  const [text, setText] = useState(raw);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div style={{ marginTop: 8 }}>
      <textarea className="code" style={{ minHeight: 320 }} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      <ErrorNote error={err} />
      <button className="btn btn-primary btn-sm" style={{ marginTop: 6 }} disabled={text === raw}
        onClick={() => onSave(text).catch((e) => setErr(e.message))}>
        Save and check
      </button>
    </div>
  );
}
