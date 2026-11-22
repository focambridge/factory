import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, batchPath, projectFileUrl } from "../api";
import { useApi } from "../hooks";
import { TicketView } from "../components/TicketView";
import { TicketFindings } from "../components/GateReport";
import { FileViewer } from "../components/FileViewer";
import { Chip, Crumbs, ErrorNote, Explain, Loading, money, Note, StatusChip, useToast, VerdictChip } from "../components/ui";
import { FIELD } from "../explain";

export function TicketPage() {
  const { project = "", unit = "", batch = "", file = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("edit") ? "edit" : params.get("tab") || "read";
  const path = `${batchPath(project, unit, batch)}/tickets/${encodeURIComponent(file)}`;
  const { data: t, error, setData } = useApi<any>(path);
  const base = `/p/${encodeURIComponent(project)}`;
  const batchUrl = `${base}/u/${encodeURIComponent(unit)}/b/${encodeURIComponent(batch)}`;
  const setTab = (name: string) => setParams(name === "read" ? {} : name === "edit" ? { edit: "1" } : { tab: name });
  if (error) return <ErrorNote error={error} />;
  if (!t) return <Loading />;
  return (
    <div>
      <Crumbs items={[["Projects", "/"], [project, base], [`${unit} / ${batch}`, batchUrl], [t.ticket?.id || file, null]]} />
      <div className="page-head">
        <div className="row">
          {t.status && <StatusChip status={t.status.status} />}
          {t.check && <VerdictChip verdict={t.check.verdict} />}
        </div>
        <Link className="btn" to={batchUrl}>Back to the batch</Link>
      </div>
      <nav className="tabs">
        {[["read", "Read"], ["edit", "Edit"], ["evidence", "Evidence from the build"]].map(([k, label]) => (
          <a key={k} href="#" className={tab === k ? "active" : ""} onClick={(e) => { e.preventDefault(); setTab(k); }}>
            {label}
            {k === "evidence" && t.artifact && <span className="muted"> ({t.artifact.attempts.length})</span>}
          </a>
        ))}
      </nav>
      {tab === "read" && (
        <div className="card">
          {t.error && <Note tone="bad">This ticket cannot be read: {t.error}. Fix it on the Edit tab.</Note>}
          {t.check && t.check.verdict !== "READY" && (
            <Note tone={t.check.verdict === "DECOMPOSE" ? "bad" : "warn"}>
              The gate says this ticket is not ready:
              <TicketFindings gate={t.check} />
            </Note>
          )}
          <TicketView ticket={t.effective} defaults={t.unit_defaults} />
        </div>
      )}
      {tab === "edit" && <Editor t={t} path={path} onSaved={setData} />}
      {tab === "evidence" && <Evidence t={t} project={project} />}
    </div>
  );
}

function Editor({ t, path, onSaved }: { t: any; path: string; onSaved: (d: any) => void }) {
  const [raw, setRaw] = useState(t.raw);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();
  useEffect(() => setRaw(t.raw), [t.raw]);
  const changed = raw !== t.raw;
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 320px" }}>
      <div className="card">
        <div className="spread" style={{ marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>Edit {t.file}</h2>
          <div className="row">
            {changed && <Chip tone="warn">Unsaved changes</Chip>}
            {t.check && <VerdictChip verdict={t.check.verdict} />}
          </div>
        </div>
        <textarea className="code" value={raw} onChange={(e) => setRaw(e.target.value)} spellCheck={false} aria-label="Ticket YAML" />
        <ErrorNote error={err} />
        {t.check && t.check.verdict !== "READY" && !changed && (
          <Note tone="warn">Gate findings after the last save:<TicketFindings gate={t.check} /></Note>
        )}
        <div className="row" style={{ marginTop: 10 }}>
          <button
            className="btn btn-primary"
            disabled={!changed}
            onClick={() =>
              api.put(path, { raw }).then((d) => {
                onSaved(d);
                setErr(null);
                toast(d.check?.verdict === "READY" ? "Saved. The gate says it is ready." : "Saved. See the gate findings.");
              }).catch((e) => setErr(e.message))
            }
          >
            Save and check
          </button>
          {changed && <button className="btn btn-ghost" onClick={() => setRaw(t.raw)}>Undo changes</button>}
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>
          The file is YAML: indentation matters, and text with a colon is safest in quotes. A ticket that has already been
          built and merged does not change the code if you edit it; to change built work, add a new ticket.
        </p>
      </div>
      <div className="card">
        <h3>What each part is for</h3>
        <dl className="small" style={{ margin: 0 }}>
          {[
            ["id / sequence", FIELD.id],
            ["title", FIELD.title],
            ["goal", FIELD.goal],
            ["scope.in / out", FIELD.scope_in + " " + FIELD.scope_out],
            ["scope.affected_paths", FIELD.affected_paths],
            ["technical", FIELD.technical],
            ["acceptance_criteria", FIELD.acceptance_criteria],
            ["verification.method", FIELD.verification],
            ["size.estimate", FIELD.size],
            ["risk", FIELD.risk],
            ["human_approval_required", FIELD.approval],
            ["dependencies.blocked_by", FIELD.dependencies],
          ].map(([k, v]) => (
            <div key={k} style={{ marginBottom: 8 }}>
              <dt><code>{k}</code></dt>
              <dd style={{ margin: "2px 0 0", color: "var(--text-2)" }}>{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

function Evidence({ t, project }: { t: any; project: string }) {
  const [file, setFile] = useState<string | null>(null);
  const a = t.artifact;
  if (!a) return <div className="card"><div className="empty">This ticket has not been built yet, so there is no evidence.</div></div>;
  return (
    <div>
      <div className="card">
        <h2>Summary</h2>
        <div className="grid grid-3">
          <div><div className="stat">{a.attempts.length}</div><div className="stat-label">attempt{a.attempts.length === 1 ? "" : "s"}</div></div>
          <div><div className="stat">{money(a.cost_usd) || "-"}</div><div className="stat-label">Claude usage</div></div>
          <div><div className="stat" style={{ fontSize: "1rem" }}>{a.commit ? <code>{a.commit.slice(0, 8)}</code> : "no commit"}</div><div className="stat-label">commit</div></div>
        </div>
        {a.stopped && <Note tone="warn">Stopped early: {a.stopped}</Note>}
        {a.changed_files.length > 0 && (
          <>
            <div className="section-label">Files changed</div>
            <div className="path-list">{a.changed_files.map((f: string) => <code key={f}>{f}</code>)}</div>
          </>
        )}
        <Explain title="What is this evidence?">
          Every attempt Claude made is recorded: the prompt it was given, what it changed, and the result of every check
          the factory ran afterwards. A ticket only counts as built when all checks pass.
        </Explain>
      </div>
      {a.attempts.map((at: any) => (
        <div className="card" key={at.attempt}>
          <div className="spread">
            <h3 style={{ margin: 0 }}>Attempt {at.attempt}</h3>
            <Chip tone={at.result === "pass" ? "good" : "bad"}>{at.result === "pass" ? "Passed" : "Failed"}</Chip>
          </div>
          <div className="small muted">{at.message}</div>
          {at.scope?.problems?.length > 0 && <Note tone="bad">{at.scope.problems.join("; ")}</Note>}
          <table style={{ marginTop: 8 }}>
            <tbody>
              {at.commands.map((c: any) => (
                <tr key={"c" + c.name}>
                  <td style={{ width: 140 }}><b>{c.name}</b></td>
                  <td><code>{c.command}</code></td>
                  <td style={{ width: 90 }}><Chip tone={c.status === "pass" ? "good" : "bad"}>{c.status}</Chip></td>
                  <td style={{ width: 80 }}>{c.log && <a href="#" onClick={(e) => { e.preventDefault(); setFile(`artifacts/${t.ticket.id}/${c.log}`); }}>log</a>}</td>
                </tr>
              ))}
              {at.criteria.map((c: any) => (
                <tr key={"a" + c.id}>
                  <td><b>{c.id}</b></td>
                  <td>{c.then}</td>
                  <td><Chip tone={c.status === "fail" ? "bad" : c.status === "manual" ? "warn" : "good"}>{c.status}</Chip></td>
                  <td>{c.log && <a href="#" onClick={(e) => { e.preventDefault(); setFile(`artifacts/${t.ticket.id}/${c.log}`); }}>log</a>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {at.summary && (
            <Explain title="Claude's own summary of this attempt">
              <div style={{ whiteSpace: "pre-wrap" }}>{at.summary}</div>
            </Explain>
          )}
        </div>
      ))}
      <div className="card">
        <h2>All files</h2>
        <div className="grid" style={{ gridTemplateColumns: "300px minmax(0,1fr)" }}>
          <div>
            {a.files.map((f: string) => (
              <div key={f} className="file-row" onClick={() => setFile(f)}>
                <span className="icon">📄</span>
                {f.replace(`artifacts/${t.ticket.id}/`, "")}
              </div>
            ))}
          </div>
          <div>{file ? <FileViewer url={projectFileUrl(project, file)} name={file.split("/").pop() || file} onClose={() => setFile(null)} /> : <div className="empty">Choose a file to view it.</div>}</div>
        </div>
      </div>
    </div>
  );
}
