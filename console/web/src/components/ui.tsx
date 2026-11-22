import { createContext, ReactNode, useContext, useState } from "react";
import { Link } from "react-router-dom";
import { marked } from "marked";
import { openInFinder } from "../api";
import { RUN_STATUS, STATUS, VERDICT } from "../explain";

export function Chip({ tone = "muted", children, title }: { tone?: string; children: ReactNode; title?: string }) {
  return (
    <span className={`chip tone-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function StatusChip({ status }: { status?: string }) {
  const s = STATUS[status || "not_built"] || STATUS.not_built;
  return <Chip tone={s.tone} title={s.help}>{s.label}</Chip>;
}

export function VerdictChip({ verdict }: { verdict?: string }) {
  const v = VERDICT[verdict || ""] || { label: verdict || "Unknown", tone: "muted", help: "" };
  return <Chip tone={v.tone} title={v.help}>{v.label}</Chip>;
}

export function RunChip({ status }: { status?: string }) {
  const r = RUN_STATUS[status || ""] || { label: status || "Unknown", tone: "muted" };
  return <Chip tone={r.tone}>{r.label}</Chip>;
}

export function Explain({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="explain" open={open}>
      <summary>{title}</summary>
      <div>{children}</div>
    </details>
  );
}

export function Help({ text }: { text: string }) {
  return (
    <span className="help" title={text} aria-label={text} tabIndex={0}>
      ?
    </span>
  );
}

export function Note({ tone = "info", children }: { tone?: string; children: ReactNode }) {
  return <div className={`note tone-${tone}`}>{children}</div>;
}

export function ErrorNote({ error }: { error?: string | null }) {
  if (!error) return null;
  return <Note tone="bad">{error}</Note>;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="progress-line muted">
      <div className="spinner" /> {label}...
    </div>
  );
}

export function Crumbs({ items }: { items: [string, string | null][] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {items.map(([label, to], i) => (
        <span key={i}>
          {i > 0 && <span aria-hidden> / </span>}
          {to ? <Link to={to}>{label}</Link> : <span>{label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function Markdown({ text }: { text: string }) {
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: marked.parse(text || "", { async: false }) as string }} />;
}

const ToastCtx = createContext<(msg: string) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const show = (m: string) => {
    setMsg(m);
    setTimeout(() => setMsg(null), 3200);
  };
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {msg && (
        <div className="toast" role="status">
          {msg}
        </div>
      )}
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/** A path on disk with Copy and Show in Finder buttons. */
export function PathRow({ label, path, canOpen = true }: { label?: string; path: string; canOpen?: boolean }) {
  const toast = useToast();
  return (
    <div className="spread" style={{ gap: 8 }}>
      <div style={{ minWidth: 0 }}>
        {label && <div className="small muted">{label}</div>}
        <code style={{ wordBreak: "break-all" }}>{path}</code>
      </div>
      <div className="row" style={{ gap: 6 }}>
        <button
          className="btn btn-sm"
          onClick={() => {
            navigator.clipboard?.writeText(path);
            toast("Path copied");
          }}
        >
          Copy
        </button>
        {canOpen && (
          <button
            className="btn btn-sm"
            onClick={() =>
              openInFinder(path)
                .then((r) => toast(r.opened ? "Opened in Finder" : "Opening is only available on your Mac"))
                .catch((e) => toast(e.message))
            }
          >
            Show in Finder
          </button>
        )}
      </div>
    </div>
  );
}

export function CommandBox({ command, label }: { command: string; label?: string }) {
  const toast = useToast();
  return (
    <div>
      {label && <div className="small muted" style={{ marginBottom: 4 }}>{label}</div>}
      <div className="spread" style={{ background: "#0f1424", borderRadius: 8, padding: "8px 10px" }}>
        <code style={{ background: "none", color: "#dfe5f5", wordBreak: "break-all" }}>{command}</code>
        <button
          className="btn btn-sm"
          onClick={() => {
            navigator.clipboard?.writeText(command);
            toast("Command copied");
          }}
        >
          Copy
        </button>
      </div>
    </div>
  );
}

export function money(v?: number | null) {
  return typeof v === "number" && v > 0 ? `$${v.toFixed(2)}` : "";
}

export function when(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}
