import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import AgentPage from "./pages/Agent";
import ApplicationsPage from "./pages/Applications";
import ApprovalsPage from "./pages/Approvals";
import Dashboard from "./pages/Dashboard";
import JobDetailPage from "./pages/JobDetail";
import JobsPage from "./pages/Jobs";
import MemoryPage from "./pages/Memory";
import ProfilePage from "./pages/Profile";

export default function App() {
  const [pending, setPending] = useState(0);
  const [health, setHealth] = useState<{ model: string; llm_credentials_detected: boolean } | null>(null);
  const location = useLocation();

  useEffect(() => {
    api.approvals().then((a) => setPending(a.length)).catch(() => {});
  }, [location.pathname]);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const links: [string, string, number?][] = [
    ["/", "Dashboard"],
    ["/agent", "Agent"],
    ["/jobs", "Jobs"],
    ["/applications", "Applications"],
    ["/approvals", "Approvals", pending],
    ["/profile", "Profile"],
    ["/memory", "Memory"],
  ];

  return (
    <div className="layout">
      <nav className="sidebar" aria-label="Main">
        <div className="brand">Job<span>Jugaad</span></div>
        {links.map(([to, label, badge]) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            {label}
            {badge ? <span className="pill warn">{badge}</span> : null}
          </NavLink>
        ))}
        <div className="sidebar-foot">
          {health ? (
            <>
              Model: {health.model}
              {!health.llm_credentials_detected && <div style={{ color: "var(--warn)" }}>No API key detected — AI features may be unavailable.</div>}
            </>
          ) : "Backend offline"}
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/agent" element={<AgentPage />} />
          <Route path="/agent/:runId" element={<AgentPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          <Route path="/applications" element={<ApplicationsPage />} />
          <Route path="/approvals" element={<ApprovalsPage onChange={setPending} />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="*" element={<div className="empty">Page not found.</div>} />
        </Routes>
      </main>
    </div>
  );
}
