import { Explain, Note, VerdictChip } from "./ui";
import { VERDICT } from "../explain";

/** The gate's verdict on a batch, in plain words. */
export function GateReport({ gate, compact = false }: { gate: any; compact?: boolean }) {
  if (!gate) return null;
  const ready = gate.verdict === "READY";
  const errors: string[] = gate.errors || [];
  const warnings: string[] = (gate.warnings || []).filter((w: string) => !w.includes("not a git repository yet"));
  return (
    <div>
      <div className="row">
        <VerdictChip verdict={gate.verdict} />
        <span className="small muted">
          {gate.ticket_count} tickets
          {gate.verdict_counts &&
            ": " +
              Object.entries(gate.verdict_counts)
                .map(([v, n]) => `${n} ${(VERDICT[v]?.label || v).toLowerCase()}`)
                .join(", ")}
        </span>
      </div>
      {ready ? (
        !compact && <Note tone="good">Every ticket passes the gate, so this batch can be built.</Note>
      ) : (
        <Note tone="bad">
          The gate found problems, so nothing in this batch will be built until they are fixed.
          {errors.length > 0 && (
            <ul>
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          {gate.verdict_counts && Object.keys(gate.verdict_counts).some((v) => v !== "READY") && (
            <div style={{ marginTop: 6 }}>Tickets marked other than Ready are listed below with their reasons.</div>
          )}
        </Note>
      )}
      {warnings.length > 0 && !compact && (
        <Note tone="warn">
          Warnings (worth reading, but they do not block the batch):
          <ul>
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Note>
      )}
      {!compact && (
        <Explain title="What is the gate?">
          The gate checks every ticket before anything is built: the format is right, nothing is left as a placeholder,
          the ticket is small enough (size, number of criteria and paths), every criterion can be checked by a command,
          and tickets come in an order that respects their dependencies. If any check fails, the whole batch waits.
        </Explain>
      )}
    </div>
  );
}

export function TicketFindings({ gate }: { gate: any }) {
  if (!gate) return null;
  const items: [string, string, string][] = [
    ...(gate.decompose || []).map((m: string) => ["bad", "Too big", m] as [string, string, string]),
    ...(gate.needs_info || []).map((m: string) => ["warn", "Needs information", m] as [string, string, string]),
    ...(gate.warnings || []).map((m: string) => ["muted", "Warning", m] as [string, string, string]),
  ].filter(([, , m]) => !m.includes("not in the repository yet") && !m.includes("does not exist in the repository"));
  if (!items.length) return null;
  return (
    <ul className="clean small" style={{ marginTop: 4 }}>
      {items.map(([tone, label, m], i) => (
        <li key={i}>
          <span className={`chip tone-${tone}`} style={{ marginRight: 6 }}>
            {label}
          </span>
          {m}
        </li>
      ))}
    </ul>
  );
}
