import { useApi } from "../hooks";
import { Explain, Markdown } from "../components/ui";
import { FIELD, KIND, STATUS, VERDICT } from "../explain";
import { Flow } from "./Home";

export function GuidePage() {
  const { data: c } = useApi<any>("/api/config");
  const { data: guide } = useApi<any>("/api/guide");
  const g = c?.gate || {};
  const b = c?.builder || {};
  const r = c?.runner || {};
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>How the factory works</h1>
          <p>Everything the console shows, explained in one place.</p>
        </div>
      </div>

      <div className="card">
        <h2>The big picture</h2>
        <Flow />
      </div>

      <div className="card">
        <h2>Projects and units</h2>
        <p>
          A <b>project</b> is one piece of software with its own git repository. It is made of <b>units</b>:
        </p>
        <ul className="clean">
          <li><b>Service</b>: {KIND.service}</li>
          <li><b>Integration</b>: {KIND.integration}</li>
        </ul>
        <p style={{ marginTop: 10 }}>
          Most projects have a single service. Each unit has a <code>unit.yaml</code> with defaults that every ticket in
          it inherits: what it is built with, where it runs, and the commands that check every ticket (install, test,
          build). Work is grouped into <b>batches</b> of tickets (batch-1, batch-2, ...) that are built together.
        </p>
      </div>

      <div className="card">
        <h2>Tickets</h2>
        <p>A ticket is one small, testable piece of work. Every ticket has the same parts:</p>
        <table>
          <tbody>
            {[
              ["Id and sequence", FIELD.id + " " + FIELD.sequence],
              ["Title and description", FIELD.title + " " + FIELD.description],
              ["Goal", FIELD.goal],
              ["Scope: included / not included", FIELD.scope_in + " " + FIELD.scope_out],
              ["Files it may change", FIELD.affected_paths],
              ["Technical", FIELD.technical],
              ["Acceptance criteria", FIELD.acceptance_criteria],
              ["Verification", FIELD.verification],
              ["Size", FIELD.size],
              ["Risk and approval", FIELD.risk + " " + FIELD.approval],
              ["Dependencies", FIELD.dependencies],
            ].map(([k, v]) => (
              <tr key={k}>
                <td style={{ width: 230 }}><b>{k}</b></td>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Explain title="How new projects and tickets are generated">
          <p>
            When you create a project, the console sends your name and description to Claude together with the
            factory's rules: the ticket format, the size limits, how tests must be written so the factory can run them,
            and lessons from earlier projects. Claude replies with a complete draft. The gate checks it straight away,
            and nothing is saved until you choose Save. You can edit any file, or tell Claude what to change and it
            revises the whole draft.
          </p>
          {guide && <Markdown text={guide.planning_guide} />}
        </Explain>
      </div>

      <div className="card">
        <h2>The gate (the checks before building)</h2>
        <p>Before anything is built, every ticket in the batch is checked. A ticket gets one of three verdicts:</p>
        <ul className="clean">
          {Object.entries(VERDICT).filter(([k]) => k !== "NOT_READY").map(([k, v]) => (
            <li key={k}><b>{v.label}</b>: {v.help}</li>
          ))}
        </ul>
        <h3 style={{ marginTop: 14 }}>Limits</h3>
        <ul className="clean">
          <li>Largest size allowed: <b>{g.max_size}</b> (XS, S, M; larger must be split)</li>
          <li>At most <b>{g.max_acceptance_criteria}</b> acceptance criteria per ticket</li>
          <li>At most <b>{g.max_affected_paths}</b> paths it may change, and an estimate of at most <b>{g.max_files_estimate}</b> files</li>
          <li>At most <b>{g.max_components}</b> infrastructure components and <b>{g.max_interfaces}</b> interfaces</li>
          <li>No placeholder text (TODO, TBD), no open questions, at least one criterion checked by a command</li>
          <li>A ticket must not mix infrastructure code (such as Terraform) with application code</li>
          <li>Dependencies must come earlier in the batch, or be merged into main already</li>
        </ul>
      </div>

      <div className="card">
        <h2>Building a batch</h2>
        <ol className="clean">
          <li>The gate checks the batch. If anything fails, nothing is built.</li>
          <li>The factory makes a separate copy of the project's code on a new branch (a worktree), so your own copy is untouched.</li>
          <li>
            For each ticket, Claude makes the change. Then the factory checks it independently: only the allowed files
            changed, the unit's commands pass, and every acceptance criterion's command passes.
          </li>
          <li>A ticket that passes is committed. One that fails is retried with the failure details, up to <b>{r.max_attempts}</b> attempts; then the batch stops.</li>
          <li>Tickets marked for approval pause the batch so you can review. You approve to continue.</li>
          <li>When the batch completes, you review the branch and merge it. Merged tickets count as done.</li>
        </ol>
        <h3 style={{ marginTop: 14 }}>Limits on Claude</h3>
        <ul className="clean">
          <li>Model: <b>{b.model}</b>, at most <b>{b.max_turns}</b> steps and <b>{Math.round((b.timeout_seconds || 0) / 60)}</b> minutes per attempt</li>
          <li>Stops trying a ticket once it has cost <b>${b.max_cost_usd_per_ticket}</b></li>
          <li>Sign-in: <b>{b.auth}</b> (your Claude login), or an API key if you choose it when running</li>
          <li>Never runs: {(r.forbidden_commands || []).length} kinds of deployment commands (terraform apply, kubectl apply and similar)</li>
          <li>Never sees cloud credentials: variables starting {(r.strip_env_prefixes || []).join(", ")} are removed</li>
        </ul>
      </div>

      <div className="card">
        <h2>Where outputs are</h2>
        <table>
          <tbody>
            <tr><td style={{ width: 230 }}><b>Tickets and settings</b></td><td><code>projects/&lt;project&gt;/services/&lt;unit&gt;/tickets/&lt;batch&gt;/</code> in the factory folder</td></tr>
            <tr><td><b>Evidence for each ticket</b></td><td><code>projects/&lt;project&gt;/artifacts/&lt;ticket-id&gt;/</code>: the report (every check, pass or fail), the code changes (changes.patch), the prompt Claude got, and every log</td></tr>
            <tr><td><b>Run records</b></td><td><code>projects/&lt;project&gt;/runs/</code>: one file per run with each ticket's status, attempts and cost</td></tr>
            <tr><td><b>The code</b></td><td>The project's own repository (shown on each project's Outputs tab). Merged work is on its main branch.</td></tr>
            <tr><td><b>Work in progress</b></td><td>Factory branches (<code>factory/&lt;unit&gt;/&lt;batch&gt;/&lt;time&gt;</code>) and their worktrees in <code>work/worktrees/</code></td></tr>
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Ticket status</h2>
        <ul className="clean">
          {Object.values(STATUS).map((s) => (
            <li key={s.label}><b>{s.label}</b>: {s.help}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
