import { Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { ToastProvider } from "./components/ui";
import { HomePage } from "./pages/Home";
import { GuidePage } from "./pages/Guide";
import { JobsPage } from "./pages/Jobs";
import { NewProjectPage } from "./pages/NewProject";
import { DraftPage } from "./pages/Draft";
import { ProjectPage } from "./pages/Project";
import { BatchPage } from "./pages/Batch";
import { TicketPage } from "./pages/Ticket";

export default function App() {
  return (
    <ToastProvider>
      <div className="layout">
        <Sidebar />
        <main className="main">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/guide" element={<GuidePage />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/new" element={<NewProjectPage />} />
            <Route path="/drafts/:draftId" element={<DraftPage />} />
            <Route path="/p/:project" element={<ProjectPage />} />
            <Route path="/p/:project/:tab" element={<ProjectPage />} />
            <Route path="/p/:project/u/:unit/b/:batch" element={<BatchPage />} />
            <Route path="/p/:project/u/:unit/b/:batch/t/:file" element={<TicketPage />} />
            <Route path="*" element={<div className="empty">Page not found.</div>} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}
