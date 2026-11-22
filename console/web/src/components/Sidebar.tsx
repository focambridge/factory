import { NavLink, useNavigate } from "react-router-dom";
import { useApi } from "../hooks";

export function Sidebar() {
  const { data: projects } = useApi<any[]>("/api/projects", 5000);
  const { data: jobs } = useApi<any[]>("/api/jobs", 3000);
  const { data: drafts } = useApi<any[]>("/api/drafts", 8000);
  const navigate = useNavigate();
  const running = (jobs || []).filter((j) => j.status === "running").length;
  const openDrafts = (drafts || []).filter((d) => !d.saved);
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark" aria-hidden>
          ⚙
        </div>
        Factory console
      </div>
      <nav className="nav">
        <NavLink to="/" end>
          Home
        </NavLink>
        <NavLink to="/guide">How the factory works</NavLink>
        <NavLink to="/jobs">
          Activity {running > 0 && <span className="chip tone-info">{running} running</span>}
        </NavLink>

        <div className="nav-section">Projects</div>
        <button className="btn btn-primary new-btn" onClick={() => navigate("/new")}>
          + New project
        </button>
        {(projects || []).map((p) => (
          <NavLink key={p.name} to={`/p/${encodeURIComponent(p.name)}`}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</span>
            {p.ticket_count ? (
              <span className="count">
                {p.merged_count}/{p.ticket_count}
              </span>
            ) : null}
          </NavLink>
        ))}
        {openDrafts.length > 0 && (
          <>
            <div className="nav-section">Drafts to review</div>
            {openDrafts.map((d) => (
              <NavLink key={d.id} to={`/drafts/${encodeURIComponent(d.id)}`}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                  {d.name}
                  {d.mode === "batch" ? " (new batch)" : ""}
                </span>
                <span className="count">{d.status === "drafting" ? "drafting" : d.ready ? "ready" : "check"}</span>
              </NavLink>
            ))}
          </>
        )}
      </nav>
    </aside>
  );
}
