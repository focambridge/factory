import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../hooks";
import { JobPanel } from "../components/JobPanel";
import { Crumbs, ErrorNote, Explain, Note } from "../components/ui";

const NAME = /^[A-Za-z][A-Za-z0-9_-]*$/;

export function NewProjectPage() {
  const navigate = useNavigate();
  const { data: config } = useApi<any>("/api/config");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [job, setJob] = useState<string | null>(null);
  const nameOk = NAME.test(name);
  return (
    <div>
      <Crumbs items={[["Projects", "/"], ["New project", null]]} />
      <div className="page-head">
        <div>
          <h1>New project</h1>
          <p>
            Name it and describe what you want. Claude drafts the whole project: its parts and a batch of small,
            testable tickets. Nothing is saved until you have reviewed it.
          </p>
        </div>
      </div>
      {job ? (
        <div className="card">
          <h2>Drafting {name}</h2>
          <p className="card-sub">
            Claude is planning the project and writing the tickets. This usually takes 2 to 6 minutes. You can leave
            this page; the draft will appear under Drafts to review in the menu.
          </p>
          <JobPanel
            jobId={job}
            onDone={(j) => j.result?.draft_id && navigate(`/drafts/${encodeURIComponent(j.result.draft_id)}`)}
          />
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 320px" }}>
          <div className="card">
            <label className="field">
              <span>Project name</span>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. D501_Quiz_Builder" />
              <small>
                Starts with a letter; letters, digits, _ and - only. It names the project here and its code folder.
                {name && !nameOk && <span style={{ color: "var(--bad)" }}> This name is not allowed.</span>}
              </small>
            </label>
            <label className="field">
              <span>What should it do?</span>
              <textarea rows={12} value={desc} onChange={(e) => setDesc(e.target.value)}
                placeholder="Describe it as you would to a developer: what it is for, who uses it, what they do with it, what it should produce, and any technology you want (for example React, or a Python command-line tool)." />
              <small>{desc.trim().length < 30 ? "A sentence or two at least." : `${desc.trim().split(/\s+/).length} words`}</small>
            </label>
            {config && !config.claude_installed && (
              <Note tone="warn">Claude Code is not installed on this computer, so drafting will fail. Install it and run <code>claude</code> once to sign in.</Note>
            )}
            <ErrorNote error={err} />
            <button
              className="btn btn-primary"
              disabled={!nameOk || desc.trim().length < 30}
              onClick={() => api.post("/api/drafts", { name, description: desc }).then((j) => setJob(j.id)).catch((e) => setErr(e.message))}
            >
              Draft the project with Claude
            </button>
          </div>
          <div className="card">
            <h3>Tips for a good description</h3>
            <ul className="clean small">
              <li>Say who it is for and what they do with it.</li>
              <li>Say what it should produce: a website, a command-line tool, files (PDF, JSON...).</li>
              <li>Name any technology you want; otherwise Claude chooses a simple one.</li>
              <li>Paste source material it must follow (rules, examples). Claude cannot browse the web while building.</li>
              <li>Say what you do not want (sign-in, a database, ...).</li>
            </ul>
            <Explain title="What happens next?">
              Claude replies with a draft: the project settings, its units, and tickets. The gate checks them straight
              away. You can read every ticket in plain English, edit any file, or tell Claude what to change. When you
              save, the project appears in the menu and you can create its repository and build it.
            </Explain>
          </div>
        </div>
      )}
    </div>
  );
}
