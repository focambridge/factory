import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../hooks";
import { JobPanel } from "../components/JobPanel";
import { Chip } from "../components/ui";

const TONE: Record<string, string> = { running: "info", succeeded: "good", failed: "bad", paused: "warn" };

export function JobsPage() {
  const { data } = useApi<any[]>("/api/jobs", 2000);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Activity</h1>
          <p>Everything the console has started since it was opened: drafts, runs, approvals, merges.</p>
        </div>
      </div>
      <div className="card">
        {(data || []).length === 0 && <div className="empty">Nothing has run yet in this session.</div>}
        <table>
          <tbody>
            {(data || []).map((j) => (
              <tr key={j.id} className="clickable" onClick={() => setOpen(open === j.id ? null : j.id)}>
                <td style={{ width: 160 }}>{new Date(j.started * 1000).toLocaleTimeString("en-GB")}</td>
                <td>
                  <b>{j.title}</b>
                  {j.project && (
                    <div className="small">
                      <Link to={`/p/${encodeURIComponent(j.project)}`} onClick={(e) => e.stopPropagation()}>
                        {j.project}
                      </Link>
                    </div>
                  )}
                  {open === j.id && (
                    <div style={{ marginTop: 10 }} onClick={(e) => e.stopPropagation()}>
                      <JobPanel jobId={j.id} />
                    </div>
                  )}
                </td>
                <td style={{ width: 160 }}>
                  <Chip tone={TONE[j.status]}>{j.status}</Chip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
