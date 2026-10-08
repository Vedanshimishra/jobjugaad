import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { EligibilityPill, ErrorBanner, JobLink, ScoreBadge, Spinner, useAsync } from "../components/ui";

const SUGGESTED_GOALS = [
  "Find the 5 best new-grad or entry-level roles for me right now and explain why each fits.",
  "Find remote AI/ML internships I'm eligible for, research the top company, and draft a referral request.",
  "Review my applications, tell me which need follow-ups, and draft them for my approval.",
  "Pick my strongest match, tailor my resume for it and prepare me for the interview.",
];

export default function Dashboard() {
  const nav = useNavigate();
  const profile = useAsync(() => api.profile(), []);
  const recs = useAsync(() => api.recommendations(), []);
  const approvals = useAsync(() => api.approvals(), []);
  const [goal, setGoal] = useState("");
  const [error, setError] = useState<string | null>(null);

  const start = async (g: string) => {
    try {
      const run = await api.startRun(g);
      nav(`/agent/${run.id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const p = profile.data;
  const incomplete = p && (!p.skills.length || !p.graduation_year || !p.preferred_roles.length || p.work_authorization?.needs_sponsorship == null);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{p?.full_name ? `Hi, ${p.full_name.split(" ")[0]}` : "Welcome to JobJugaad"}</h1>
          <div className="subtitle">Your AI job-search agent. Give it a goal; it plans, uses tools and asks before acting.</div>
        </div>
      </div>
      <ErrorBanner error={error} />
      {incomplete && (
        <div className="banner warn">
          Your profile is incomplete, so eligibility and match scores will be less accurate.{" "}
          <Link to="/profile">Upload a resume and set your preferences →</Link>
        </div>
      )}

      <div className="card">
        <h2>What should the agent do?</h2>
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (goal.trim()) void start(goal); }}>
          <input style={{ flex: 1 }} value={goal} onChange={(e) => setGoal(e.target.value)}
            placeholder="e.g. Find backend new-grad roles in NYC that sponsor visas and draft recruiter notes" />
          <button className="primary" disabled={!goal.trim()}>Run agent</button>
        </form>
        <div className="tags mt">
          {SUGGESTED_GOALS.map((g) => (
            <button key={g} className="small" onClick={() => void start(g)}>{g}</button>
          ))}
        </div>
      </div>

      <div className="grid grid-2 mt">
        <div className="card">
          <div className="spread"><h2>Apply next</h2><Link to="/jobs" className="small">All jobs →</Link></div>
          {recs.loading ? <Spinner /> : recs.data?.apply_next.length ? recs.data.apply_next.map((r) => (
            <div className="job-row" key={r.job_id}>
              <ScoreBadge score={r.score} />
              <div className="info">
                <JobLink id={r.job_id}><span className="title">{r.title}</span></JobLink>
                <div className="meta">{r.company} · {r.reasons.join(" · ")}</div>
              </div>
              <EligibilityPill value={r.eligibility} />
            </div>
          )) : <div className="empty">No scored jobs yet. <Link to="/jobs">Discover jobs</Link> or ask the agent.</div>}
        </div>

        <div className="stack">
          <div className="card">
            <div className="spread"><h2>Waiting for your approval</h2><Link to="/approvals" className="small">Inbox →</Link></div>
            {approvals.data?.length ? approvals.data.slice(0, 4).map((a) => (
              <p key={a.id} className="small">• {a.summary}</p>
            )) : <p className="muted">Nothing pending. The agent never sends anything without you.</p>}
          </div>
          <div className="card">
            <h2>Follow-ups due</h2>
            {recs.data?.follow_ups.length ? recs.data.follow_ups.map((f) => (
              <p key={f.job_id} className="small">
                <JobLink id={f.job_id}>{f.company} — {f.title}</JobLink>: {f.action}
              </p>
            )) : <p className="muted">No follow-ups due.</p>}
          </div>
        </div>
      </div>
    </>
  );
}
