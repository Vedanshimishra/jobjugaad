import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import {
  Busy, EligibilityPill, ErrorBanner, JobLink, ScoreBadge, Spinner, StatusPill, TagInput, fmtDate, salary, useAction,
  useAsync,
} from "../components/ui";

const LEVELS = ["internship", "new_grad", "entry", "mid", "senior"];
const MODES = ["remote", "hybrid", "onsite"];

function toggle(list: string[], v: string) {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

export default function JobsPage() {
  const nav = useNavigate();
  const [filters, setFilters] = useState({ q: "", eligibility: "eligible,uncertain", min_score: 0, level: "" });
  const jobs = useAsync(() => api.jobs({ ...filters, limit: 100 }), [JSON.stringify(filters)]);
  const action = useAction();
  const [disc, setDisc] = useState({ keywords: [] as string[], companies: [] as string[], levels: ["internship", "new_grad", "entry"], work_modes: [] as string[], location: "" });
  const [discResult, setDiscResult] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [manual, setManual] = useState({ company: "", title: "", location: "", url: "", description: "" });

  const discover = async () => {
    const res = await action.run("discover", () =>
      api.discover({ ...disc, location: disc.location || null, include_ineligible: false, limit: 50 }));
    if (res) {
      setDiscResult(`Scanned ${res.fetched.toLocaleString()} postings, ${res.relevant} relevant tech roles, ${res.matches.length} shown as matches.` +
        (res.errors.length ? ` Some boards failed: ${res.errors.join(", ")}` : ""));
      jobs.reload();
    }
  };
  const addManual = async () => {
    const m = await action.run("manual", () => api.addManualJob(manual));
    if (m) nav(`/jobs/${m.job.id}`);
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Jobs</h1>
          <div className="subtitle">Scored for you: skills 40, role 20, level 15, location 10, preferences 10, pay 5 — discounted when you may not be eligible.</div>
        </div>
        <button onClick={() => setShowManual(!showManual)}>{showManual ? "Close" : "Add a job manually"}</button>
      </div>
      <ErrorBanner error={action.error} />

      {showManual && (
        <div className="card stack" style={{ marginBottom: 16 }}>
          <h2>Add a job you found elsewhere</h2>
          <div className="grid grid-2">
            <input placeholder="Company" value={manual.company} onChange={(e) => setManual({ ...manual, company: e.target.value })} />
            <input placeholder="Title" value={manual.title} onChange={(e) => setManual({ ...manual, title: e.target.value })} />
            <input placeholder="Location" value={manual.location} onChange={(e) => setManual({ ...manual, location: e.target.value })} />
            <input placeholder="Posting URL" value={manual.url} onChange={(e) => setManual({ ...manual, url: e.target.value })} />
          </div>
          <textarea rows={8} placeholder="Paste the full job description" value={manual.description}
            onChange={(e) => setManual({ ...manual, description: e.target.value })} />
          <div>
            <button className="primary" disabled={!manual.company || !manual.title || manual.description.length < 20 || !!action.busy} onClick={addManual}>
              <Busy on={action.busy === "manual"}>Add & score</Busy>
            </button>
          </div>
        </div>
      )}

      <div className="card">
        <h2>Discover new postings</h2>
        <div className="grid grid-3">
          <div><label>Keywords (any)</label><TagInput value={disc.keywords} onChange={(v) => setDisc({ ...disc, keywords: v })} placeholder="e.g. machine learning" /></div>
          <div><label>Company boards (blank = all configured)</label><TagInput value={disc.companies} onChange={(v) => setDisc({ ...disc, companies: v })} placeholder="e.g. stripe" /></div>
          <div><label>Location contains</label><input value={disc.location} onChange={(e) => setDisc({ ...disc, location: e.target.value })} placeholder="e.g. New York" /></div>
        </div>
        <div className="row mt">
          {LEVELS.map((l) => (
            <label key={l} className="checkbox"><input type="checkbox" checked={disc.levels.includes(l)} onChange={() => setDisc({ ...disc, levels: toggle(disc.levels, l) })} />{l.replace("_", " ")}</label>
          ))}
          <span className="muted">|</span>
          {MODES.map((m) => (
            <label key={m} className="checkbox"><input type="checkbox" checked={disc.work_modes.includes(m)} onChange={() => setDisc({ ...disc, work_modes: toggle(disc.work_modes, m) })} />{m}</label>
          ))}
          <button className="primary" style={{ marginLeft: "auto" }} onClick={discover} disabled={!!action.busy}>
            <Busy on={action.busy === "discover"}>Search boards</Busy>
          </button>
        </div>
        {discResult && <p className="small muted mt">{discResult}</p>}
      </div>

      <div className="card mt">
        <div className="row" style={{ marginBottom: 8 }}>
          <input style={{ flex: 2, minWidth: 180 }} placeholder="Filter by title, company, location" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
          <select style={{ flex: 1, minWidth: 150 }} value={filters.eligibility} onChange={(e) => setFilters({ ...filters, eligibility: e.target.value })}>
            <option value="eligible,uncertain">Eligible + uncertain</option>
            <option value="eligible">Eligible only</option>
            <option value="">All (incl. ineligible)</option>
          </select>
          <select style={{ flex: 1, minWidth: 130 }} value={filters.level} onChange={(e) => setFilters({ ...filters, level: e.target.value })}>
            <option value="">Any level</option>
            {LEVELS.map((l) => <option key={l} value={l}>{l.replace("_", " ")}</option>)}
          </select>
          <select style={{ flex: 1, minWidth: 120 }} value={filters.min_score} onChange={(e) => setFilters({ ...filters, min_score: Number(e.target.value) })}>
            {[0, 40, 55, 70].map((s) => <option key={s} value={s}>Score ≥ {s}</option>)}
          </select>
        </div>
        <ErrorBanner error={jobs.error} />
        {jobs.loading ? <div className="empty"><Spinner /></div> : jobs.data?.length ? jobs.data.map((m) => (
          <div className="job-row" key={m.job.id}>
            <ScoreBadge score={m.score} />
            <div className="info">
              <JobLink id={m.job.id}><span className="title">{m.job.title}</span></JobLink>
              <div className="meta">
                {m.job.company} · {m.job.location || "—"} · {m.job.work_mode} · {m.job.level.replace("_", " ")}
                {m.job.salary_max ? ` · ${salary(m.job.salary_min, m.job.salary_max, m.job.salary_currency)}` : ""}
                {m.job.posted_at ? ` · posted ${fmtDate(m.job.posted_at)}` : ""}
              </div>
              {(m.strengths[0] || m.gaps[0]) && (
                <div className="small" style={{ marginTop: 2 }}>
                  {m.strengths[0] && <span style={{ color: "var(--good)" }}>+ {m.strengths[0]} </span>}
                  {m.gaps[0] && <span style={{ color: "var(--bad)" }}>− {m.gaps[0]}</span>}
                </div>
              )}
            </div>
            <div className="stack" style={{ gap: 4, alignItems: "flex-end" }}>
              <EligibilityPill value={m.eligibility} />
              {m.application_status && <StatusPill status={m.application_status} />}
            </div>
          </div>
        )) : <div className="empty">No jobs match these filters. Search the boards above or ask the agent.</div>}
      </div>
    </>
  );
}
