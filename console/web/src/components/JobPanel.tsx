import { useEffect, useRef } from "react";
import { Job, useElapsed, useJob } from "../hooks";
import { Chip } from "./ui";

function lineClass(l: string) {
  if (/attempt \d+: pass|READY|completed|Merged|Repository created|Draft ready|Revision ready/.test(l)) return "l-ok";
  if (/fail|ERROR|rejected|NOT_READY|stopping/i.test(l)) return "l-bad";
  if (/^\S+-\d+ \(sequence/.test(l) || l.startsWith("Run ") || l.startsWith("$ ")) return "l-head";
  return "";
}

const JOB_TONE: Record<string, string> = { running: "info", succeeded: "good", failed: "bad", paused: "warn" };
const JOB_LABEL: Record<string, string> = {
  running: "Running",
  succeeded: "Finished",
  failed: "Stopped",
  paused: "Paused for approval",
};

/** Live output of a background job. */
export function JobPanel({ jobId, onDone, hint }: { jobId: string | null; onDone?: (j: Job) => void; hint?: string }) {
  const { job, lines } = useJob(jobId, onDone);
  const elapsed = useElapsed(job?.started, job?.finished);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines.length]);
  if (!jobId) return null;
  const current = [...lines].reverse().find((l) => /^\S+-\d+ \(sequence/.test(l));
  return (
    <div className="stack">
      <div className="spread">
        <div className="progress-line">
          {job?.status === "running" && <div className="spinner" />}
          <b>{job?.title || "Starting"}</b>
          {job && <Chip tone={JOB_TONE[job.status]}>{JOB_LABEL[job.status]}</Chip>}
        </div>
        <span className="small muted">{elapsed}</span>
      </div>
      {job?.status === "running" && current && (
        <div className="small">
          Claude is working on <b>{current.split(" (")[0]}</b>: {current.split(": ").slice(1).join(": ")}. The log
          updates when each attempt finishes, so it can be quiet for a few minutes.
        </div>
      )}
      {job?.status === "running" && hint && !current && <div className="small muted">{hint}</div>}
      <div className="log" ref={box} aria-live="polite">
        {lines.length === 0 ? (
          <span className="muted">Waiting for output...</span>
        ) : (
          lines.map((l, i) => (
            <div key={i} className={lineClass(l)}>
              {l || " "}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
