import { useEffect, useState } from "react";
import { Markdown } from "./ui";

const TEXT = /\.(md|txt|patch|log|ya?ml|json|jsonl|py|tsx?|jsx?|css|html|toml|cfg|sh|csv|gitignore)$/i;

/** Shows a file from the API: Markdown rendered, PDFs and images embedded, text as code. */
export function FileViewer({ url, name, onClose }: { url: string; name: string; onClose?: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);
  const isPdf = /\.pdf$/i.test(name);
  const isImage = /\.(png|jpe?g|gif|svg|webp)$/i.test(name);
  const isText = TEXT.test(name) || !/\.[a-z0-9]+$/i.test(name);
  useEffect(() => {
    setText(null);
    if (isText) fetch(url).then((r) => r.text()).then(setText);
  }, [url, isText]);
  let body;
  if (isPdf) body = <iframe src={url} title={name} />;
  else if (isImage) body = <img src={url} alt={name} style={{ maxWidth: "100%", display: "block", margin: 10 }} />;
  else if (!isText) body = <div className="empty">This file type cannot be shown here. Use Open to view it.</div>;
  else if (text === null) body = <div className="empty">Loading...</div>;
  else if (/\.md$/i.test(name) && !raw) body = <div style={{ padding: "8px 16px" }}><Markdown text={text} /></div>;
  else if (/\.json$/i.test(name)) {
    let pretty = text;
    try {
      pretty = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      /* show as is */
    }
    body = <pre>{pretty}</pre>;
  } else body = <pre>{text}</pre>;
  return (
    <div className="viewer">
      <div className="viewer-head">
        <code style={{ background: "none" }}>{name}</code>
        <div className="row" style={{ gap: 6 }}>
          {/\.md$/i.test(name) && (
            <button className="btn btn-sm" onClick={() => setRaw(!raw)}>
              {raw ? "Formatted" : "Plain text"}
            </button>
          )}
          <a className="btn btn-sm" href={url} target="_blank" rel="noreferrer">
            Open in new tab
          </a>
          {onClose && (
            <button className="btn btn-sm" onClick={onClose}>
              Close
            </button>
          )}
        </div>
      </div>
      {body}
    </div>
  );
}
