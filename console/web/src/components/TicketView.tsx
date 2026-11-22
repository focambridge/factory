import { ReactNode } from "react";
import { FIELD } from "../explain";
import { Chip, Help } from "./ui";

function Label({ children, help }: { children: ReactNode; help?: string }) {
  return (
    <div className="section-label">
      {children}
      {help && <Help text={help} />}
    </div>
  );
}

const METHOD: Record<string, string> = {
  new_test: "New test written by Claude",
  existing_test: "Existing test",
  static_check: "Command check",
  manual: "Checked by a person",
};

/** A ticket rendered for people, with each part explained. */
export function TicketView({ ticket, defaults }: { ticket: any; defaults?: any }) {
  if (!ticket) return null;
  const t = ticket;
  const scope = t.scope || {};
  const tech = t.technical || {};
  const risk = t.risk || {};
  const size = t.size || {};
  const deps = (t.dependencies || {}).blocked_by || [];
  const commands = tech.commands || {};
  return (
    <div>
      <div className="row" style={{ marginBottom: 6 }}>
        <span className="ticket-id">{t.id}</span>
        <Chip tone="muted">{t.type}</Chip>
        <Chip tone="muted" title={FIELD.size}>size {size.estimate}</Chip>
        <Chip tone={risk.level === "high" ? "bad" : risk.level === "medium" ? "warn" : "muted"} title={FIELD.risk}>
          {risk.level} risk
        </Chip>
        {risk.human_approval_required && <Chip tone="warn" title={FIELD.approval}>pauses for approval</Chip>}
      </div>
      <h2 style={{ fontSize: "1.3rem" }}>{t.title}</h2>
      <p className="muted">{t.description}</p>

      <Label help={FIELD.goal}>Why</Label>
      <dl className="kv">
        <dt>Problem</dt>
        <dd>{t.goal?.problem}</dd>
        <dt>Outcome</dt>
        <dd>{t.goal?.outcome}</dd>
      </dl>

      <div className="grid grid-2" style={{ marginTop: 4 }}>
        <div>
          <Label help={FIELD.scope_in}>Included</Label>
          <ul className="clean">{(scope.in || []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
        </div>
        <div>
          <Label help={FIELD.scope_out}>Not included</Label>
          <ul className="clean">{(scope.out || []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
        </div>
      </div>

      <Label help={FIELD.affected_paths}>Files it may change</Label>
      <div className="path-list">
        {(scope.affected_paths || []).map((p: string) => <code key={p}>{p}</code>)}
      </div>
      {(scope.protected_paths || []).length > 0 && (
        <>
          <Label help={FIELD.protected_paths}>Files it must not touch</Label>
          <div className="path-list">{scope.protected_paths.map((p: string) => <code key={p}>{p}</code>)}</div>
        </>
      )}

      <Label help={FIELD.acceptance_criteria}>How done is proven ({(t.acceptance_criteria || []).length} checks)</Label>
      {(t.acceptance_criteria || []).map((c: any) => (
        <div className="ac" key={c.id}>
          <div className="spread">
            <b className="ticket-id">{c.id}</b>
            <Chip tone={c.verification?.method === "manual" ? "warn" : "info"} title={FIELD.verification}>
              {METHOD[c.verification?.method] || c.verification?.method}
            </Chip>
          </div>
          <div className="gwt" style={{ marginTop: 4 }}>
            <b>Given</b><span>{c.given}</span>
            <b>When</b><span>{c.when}</span>
            <b>Then</b><span>{c.then}</span>
          </div>
          {c.verification?.reference && (
            <div className="verify">
              Checked by running <code>{c.verification.reference}</code>
            </div>
          )}
        </div>
      ))}

      <Label help={FIELD.technical}>Technical</Label>
      <dl className="kv">
        {tech.stack && (
          <>
            <dt>Built with</dt>
            <dd>{tech.stack.map((s: any) => `${s.name}${s.version ? " " + s.version : ""}`).join(", ")}</dd>
          </>
        )}
        {tech.target && (
          <>
            <dt>Runs on</dt>
            <dd>
              {tech.target.environment}
              {tech.target.region ? ` (${tech.target.region})` : ""}
              {tech.target.notes ? ` - ${tech.target.notes}` : ""}
            </dd>
          </>
        )}
        {(tech.interfaces || []).length > 0 && (
          <>
            <dt>Creates or changes</dt>
            <dd>
              <ul className="clean">
                {tech.interfaces.map((x: any, i: number) => (
                  <li key={i}>
                    {x.action} {x.kind} <code>{x.name}</code>
                    {x.signature && <span className="muted small"> {x.signature}</span>}
                  </li>
                ))}
              </ul>
            </dd>
          </>
        )}
        {(tech.components || []).length > 0 && (
          <>
            <dt>Infrastructure</dt>
            <dd>
              <ul className="clean">
                {tech.components.map((x: any, i: number) => (
                  <li key={i}>{x.action} {x.type} <code>{x.name}</code></li>
                ))}
              </ul>
            </dd>
          </>
        )}
        {Object.keys(commands).length > 0 && (
          <>
            <dt>Checked by <Help text={FIELD.commands} /></dt>
            <dd>
              <ul className="clean">
                {Object.entries(commands).map(([k, v]) => (
                  <li key={k}>
                    <b>{k}</b>: <code>{String(v)}</code>
                  </li>
                ))}
              </ul>
            </dd>
          </>
        )}
        {(tech.constraints || []).length > 0 && (
          <>
            <dt>Rules <Help text={FIELD.constraints} /></dt>
            <dd>
              <ul className="clean">
                {tech.constraints.map((c: any, i: number) => (
                  <li key={i}>
                    <span className="muted">{c.category}:</span> {c.statement}
                  </li>
                ))}
              </ul>
            </dd>
          </>
        )}
      </dl>

      <Label>Size, risk and order</Label>
      <dl className="kv">
        <dt>Size</dt>
        <dd>
          {size.estimate}
          {size.rationale && <span className="muted"> - {size.rationale}</span>}
        </dd>
        <dt>Risk</dt>
        <dd>
          {risk.level}
          {risk.notes && <span className="muted"> - {risk.notes}</span>}
          {risk.human_approval_required && <div className="small">The batch pauses after this ticket for your review.</div>}
        </dd>
        <dt>Waits for <Help text={FIELD.dependencies} /></dt>
        <dd>{deps.length ? deps.map((d: string) => <code key={d} style={{ marginRight: 4 }}>{d}</code>) : "nothing"}</dd>
        {t.context?.notes && (
          <>
            <dt>Notes for Claude</dt>
            <dd className="small">{t.context.notes}</dd>
          </>
        )}
      </dl>
      {defaults && Object.keys(defaults).length > 0 && (
        <p className="small muted" style={{ marginTop: 10 }}>
          Stack, target, commands and rules that this ticket does not set come from its unit's defaults (unit.yaml).
        </p>
      )}
    </div>
  );
}
