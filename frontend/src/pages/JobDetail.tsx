import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import {
  Busy, EligibilityPill, ErrorBanner, Md, ScoreBadge, Spinner, StatusPill, fmtDate, salary, useAction, useAsync,
} from "../components/ui";
import type { JobDetail, OutreachMessage, PrepQuestion } from "../types";

const TABS = ["match", "research", "resume", "outreach", "interview", "tracker", "description"] as const;
type Tab = (typeof TABS)[number];

export default function JobDetailPage() {
  const id = Number(useParams().jobId);
  const detail = useAsync(() => api.job(id), [id]);
  const [tab, setTab] = useState<Tab>("match");
  const action = useAction();

  if (detail.loading && !detail.data) return <div className="empty"><Spinner /></div>;
  if (detail.error) return <ErrorBanner error={detail.error} />;
  const d = detail.data!;
  const j = d.job;

  return (
    <>
      <div className="page-head">
        <div className="row" style={{ gap: 14 }}>
          <ScoreBadge score={d.match.score} />
          <div>
            <h1>{j.title}</h1>
            <div className="subtitle">
              {j.company} · {j.location || "—"} · {j.work_mode} · {j.level.replace("_", " ")}
              {j.salary_max ? ` · ${salary(j.salary_min, j.salary_max, j.salary_currency)}` : ""}
              {j.posted_at ? ` · posted ${fmtDate(j.posted_at)}` : ""}
            </div>
          </div>
        </div>
        <div className="row">
          <EligibilityPill value={d.match.eligibility} />
          {d.application && <StatusPill status={d.application.status} />}
          {j.url && <a className="btn" href={j.url} target="_blank" rel="noreferrer">Open posting ↗</a>}
        </div>
      </div>
      <ErrorBanner error={action.error} />
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`tab${tab === t ? " active" : ""}`} onClick={() => setTab(t)}>
            {t === "interview" ? "Interview prep" : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      {tab === "match" && <MatchTab d={d} action={action} onChange={detail.reload} />}
      {tab === "research" && <ResearchTab d={d} action={action} onChange={detail.reload} />}
      {tab === "resume" && <ResumeTab d={d} action={action} onChange={detail.reload} />}
      {tab === "outreach" && <OutreachTab d={d} action={action} onChange={detail.reload} />}
      {tab === "interview" && <PrepTab d={d} action={action} onChange={detail.reload} />}
      {tab === "tracker" && <TrackerTab d={d} action={action} onChange={detail.reload} />}
      {tab === "description" && <div className="card"><div className="pre" style={{ background: "none", padding: 0, fontFamily: "inherit", fontSize: 14 }}>{j.description}</div></div>}
    </>
  );
}

type TabProps = { d: JobDetail; action: ReturnType<typeof useAction>; onChange: () => void };

function MatchTab({ d, action, onChange }: TabProps) {
  const m = d.match;
  const llm = m.breakdown.llm;
  const comps = m.breakdown.components ?? {};
  const sk = m.breakdown.skills ?? {};
  return (
    <div className="grid grid-2">
      <div className="card">
        <h2>Score breakdown</h2>
        {Object.entries(comps).map(([k, c]) => (
          <div key={k} style={{ marginBottom: 10 }}>
            <div className="spread small"><strong style={{ textTransform: "capitalize" }}>{k}</strong><span>{c.points} / {c.weight}</span></div>
            <div className="bar"><div style={{ width: `${c.score * 100}%` }} /></div>
            <div className="small muted">{c.detail}</div>
          </div>
        ))}
        <p className="small muted">
          Fit {m.breakdown.fit}{m.breakdown.avoid_penalty ? ` − ${m.breakdown.avoid_penalty} (avoided tech)` : ""} × {m.breakdown.eligibility_multiplier} (eligibility) = <strong>{m.score}</strong>
        </p>
        <h3>Skills</h3>
        <p className="small"><span style={{ color: "var(--good)" }}>Have:</span> {[...(sk.matched_required ?? []), ...(sk.matched_preferred ?? [])].join(", ") || "—"}</p>
        <p className="small"><span style={{ color: "var(--bad)" }}>Missing (required):</span> {(sk.missing_required ?? []).join(", ") || "—"}</p>
      </div>
      <div className="stack">
        <div className="card">
          <h2>Eligibility <EligibilityPill value={m.eligibility} /></h2>
          <table><tbody>
            {m.eligibility_reasons.map((r, i) => (
              <tr key={i}>
                <td><span className={`pill ${r.status === "pass" ? "good" : r.status === "fail" ? "bad" : "warn"}`}>{r.status}</span></td>
                <td><strong>{r.check.replace("_", " ")}</strong><div className="small muted">{r.detail}</div></td>
              </tr>
            ))}
          </tbody></table>
        </div>
        <div className="card">
          <div className="spread">
            <h2>Coach's take</h2>
            <button onClick={async () => { if (await action.run("explain", () => api.explain(d.job.id))) onChange(); }} disabled={!!action.busy}>
              <Busy on={action.busy === "explain"}>{llm ? "Regenerate" : "Explain this match"}</Busy>
            </button>
          </div>
          {llm ? (
            <>
              <p><span className="pill accent">{llm.recommendation.replace("_", " ")}</span> {llm.summary}</p>
              <h3>Why apply</h3><ul>{llm.reasons_for.map((x, i) => <li key={i}>{x}</li>)}</ul>
              <h3>Concerns</h3><ul>{llm.reasons_against.map((x, i) => <li key={i}>{x}</li>)}</ul>
              <h3>Improve your odds</h3><ul>{llm.how_to_improve_odds.map((x, i) => <li key={i}>{x}</li>)}</ul>
            </>
          ) : <p className="muted">Get a written explanation and an apply / stretch / skip recommendation.</p>}
        </div>
      </div>
    </div>
  );
}

function ResearchTab({ d, action, onChange }: TabProps) {
  const r = d.research?.content;
  const go = async (refresh: boolean) => { if (await action.run("research", () => api.research(d.job.id, refresh))) onChange(); };
  return (
    <div className="card">
      <div className="spread">
        <h2>{d.job.company} research {d.research && <span className="small muted">· {fmtDate(d.research.created_at)} · confidence {r?.confidence}</span>}</h2>
        <button className="primary" onClick={() => go(!!d.research)} disabled={!!action.busy}>
          <Busy on={action.busy === "research"}>{d.research ? "Refresh" : "Research company"}</Busy>
        </button>
      </div>
      {!r ? <p className="muted">Uses web search to brief you on products, stack, culture, recent news and the interview process.</p> : (
        <div className="grid grid-2">
          <div>
            <h3>Overview</h3><p>{r.overview}</p>
            <h3>Products</h3><ul>{r.products.map((x, i) => <li key={i}>{x}</li>)}</ul>
            <h3>Tech stack</h3><div className="tags">{r.tech_stack.map((x) => <span key={x} className="tag">{x}</span>)}</div>
            <h3>Engineering culture</h3><p>{r.engineering_culture}</p>
            <h3>Interview process</h3><p>{r.interview_process}</p>
          </div>
          <div>
            <h3>Talking points for you</h3><ul>{r.talking_points.map((x, i) => <li key={i}>{x}</li>)}</ul>
            <h3>Recent news</h3>
            <ul>{r.recent_news.map((n, i) => <li key={i}><strong>{n.headline}</strong> <span className="muted small">{n.date}</span><div className="small">{n.why_it_matters}</div></li>)}</ul>
            {r.red_flags.length > 0 && <><h3>Things to check</h3><ul>{r.red_flags.map((x, i) => <li key={i}>{x}</li>)}</ul></>}
            <h3>Sources</h3>
            <ul className="small">{r.sources.map((s, i) => <li key={i}><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a></li>)}</ul>
          </div>
        </div>
      )}
    </div>
  );
}

function ResumeTab({ d, action, onChange }: TabProps) {
  const t = d.tailored_resume;
  return (
    <div className="card">
      <div className="spread">
        <h2>Tailored resume {t && <span className="small muted">· {fmtDate(t.created_at)}</span>}</h2>
        <div className="row">
          {t && <a className="btn" href={`/api/jobs/tailored/${t.id}/download`}>Download .md</a>}
          {t && <button onClick={() => navigator.clipboard.writeText(t.markdown)}>Copy</button>}
          <button className="primary" disabled={!!action.busy}
            onClick={async () => { if (await action.run("tailor", () => api.tailor(d.job.id))) onChange(); }}>
            <Busy on={action.busy === "tailor"}>{t ? "Re-tailor" : "Tailor my resume"}</Busy>
          </button>
        </div>
      </div>
      {!t ? <p className="muted">Rewrites and reorders your real experience for this job. It never adds experience you don't have, and flags anything it can't verify.</p> : (
        <>
          {t.warnings.length > 0 && (
            <div className="banner warn"><strong>Verify before using:</strong><ul>{t.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div>
          )}
          <div className="grid grid-2">
            <div className="pre" style={{ maxHeight: 600, overflow: "auto" }}>{t.markdown}</div>
            <div>
              <h3>What changed</h3><ul className="small">{t.change_log.map((c, i) => <li key={i}>{c}</li>)}</ul>
              {t.content.honest_gaps?.length ? <><h3>Honest gaps</h3><ul className="small">{t.content.honest_gaps.map((c, i) => <li key={i}>{c}</li>)}</ul></> : null}
              {t.content.keywords_covered?.length ? <><h3>Keywords covered</h3><div className="tags">{t.content.keywords_covered.map((k) => <span className="tag" key={k}>{k}</span>)}</div></> : null}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function OutreachTab({ d, action, onChange }: TabProps) {
  const [form, setForm] = useState({ kind: "recruiter", channel: "email", recipient_name: "", recipient_role: "", recipient_contact: "", context: "" });
  const draft = async () => {
    if (await action.run("draft", () => api.draftOutreach({ job_id: d.job.id, ...form }))) onChange();
  };
  return (
    <div className="grid grid-2">
      <div className="card">
        <h2>Draft a message</h2>
        <div className="grid grid-2">
          <div className="field"><label>Type</label>
            <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="recruiter">Recruiter</option><option value="referral">Referral request</option>
              <option value="hiring_manager">Hiring manager</option><option value="follow_up">Follow-up</option>
              <option value="thank_you">Thank-you</option>
            </select></div>
          <div className="field"><label>Channel</label>
            <select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
              <option value="email">Email</option><option value="linkedin">LinkedIn message</option>
              <option value="linkedin_note">LinkedIn connection note (300 chars)</option>
            </select></div>
          <div className="field"><label>Recipient name</label><input value={form.recipient_name} onChange={(e) => setForm({ ...form, recipient_name: e.target.value })} /></div>
          <div className="field"><label>Recipient role</label><input value={form.recipient_role} onChange={(e) => setForm({ ...form, recipient_role: e.target.value })} /></div>
        </div>
        <div className="field"><label>Email / profile URL</label><input value={form.recipient_contact} onChange={(e) => setForm({ ...form, recipient_contact: e.target.value })} /></div>
        <div className="field"><label>Context (shared school, how you met, what to emphasize)</label>
          <textarea rows={3} value={form.context} onChange={(e) => setForm({ ...form, context: e.target.value })} /></div>
        <button className="primary" onClick={draft} disabled={!!action.busy}><Busy on={action.busy === "draft"}>Draft message</Busy></button>
      </div>
      <div className="stack">
        {d.messages.length === 0 && <div className="card muted">No messages yet.</div>}
        {d.messages.map((m) => <MessageCard key={m.id} m={m} action={action} onChange={onChange} />)}
      </div>
    </div>
  );
}

function MessageCard({ m, action, onChange }: { m: OutreachMessage; action: TabProps["action"]; onChange: () => void }) {
  const [edit, setEdit] = useState(false);
  const [subject, setSubject] = useState(m.subject);
  const [body, setBody] = useState(m.body);
  const editable = ["draft", "rejected", "approved"].includes(m.status);
  return (
    <div className="card">
      <div className="spread">
        <strong>{m.kind.replace("_", " ")} → {m.recipient_name || "recipient"} <span className="muted small">({m.channel})</span></strong>
        <StatusPill status={m.status} />
      </div>
      {edit ? (
        <div className="stack mt">
          {m.channel === "email" && <input value={subject} onChange={(e) => setSubject(e.target.value)} />}
          <textarea rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="row">
            <button className="primary" onClick={async () => { if (await action.run("edit", () => api.editOutreach(m.id, { subject, body }))) { setEdit(false); onChange(); } }}>Save</button>
            <button onClick={() => setEdit(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <>
          {m.subject && <p className="mt"><strong>Subject:</strong> {m.subject}</p>}
          <div className="pre mt" style={{ fontFamily: "inherit", fontSize: 14 }}>{m.body}</div>
        </>
      )}
      <div className="row mt">
        {editable && !edit && <button onClick={() => setEdit(true)}>Edit</button>}
        <button onClick={() => navigator.clipboard.writeText(m.subject ? `${m.subject}\n\n${m.body}` : m.body)}>Copy</button>
        {["draft", "rejected"].includes(m.status) && (
          <button className="primary" onClick={async () => { if (await action.run("approve", () => api.requestApproval(m.id, "Requested from job page"))) onChange(); }}>
            Request approval to send
          </button>
        )}
        {m.status === "pending_approval" && <Link to="/approvals">Review in approvals →</Link>}
        {m.status === "approved" && (
          <button onClick={async () => { if (await action.run("sent", () => api.markSent(m.id))) onChange(); }}>I sent it</button>
        )}
      </div>
    </div>
  );
}

function QList({ title, qs }: { title: string; qs: PrepQuestion[] }) {
  if (!qs.length) return null;
  return (
    <>
      <h3>{title}</h3>
      {qs.map((q, i) => (
        <details key={i} style={{ marginBottom: 6 }}>
          <summary>{q.question}</summary>
          <div className="small" style={{ padding: "4px 0 4px 16px" }}>
            <div className="muted">Assesses: {q.what_they_assess}</div>
            <div>{q.answer_guidance}</div>
          </div>
        </details>
      ))}
    </>
  );
}

function PrepTab({ d, action, onChange }: TabProps) {
  const [days, setDays] = useState(7);
  const p = d.interview_prep?.content;
  return (
    <div className="card">
      <div className="spread">
        <h2>Interview prep</h2>
        <div className="row">
          <label className="checkbox">Days to prepare <input type="number" min={1} max={60} value={days} style={{ width: 70 }} onChange={(e) => setDays(Number(e.target.value))} /></label>
          <button className="primary" disabled={!!action.busy}
            onClick={async () => { if (await action.run("prep", () => api.prep(d.job.id, days))) onChange(); }}>
            <Busy on={action.busy === "prep"}>{p ? "Regenerate" : "Build prep plan"}</Busy>
          </button>
        </div>
      </div>
      {!p ? <p className="muted">Builds a role-specific plan: likely rounds, topics, questions with guidance drawn from your own projects, and a day-by-day study plan. Research the company first for better results.</p> : (
        <div className="grid grid-2">
          <div>
            <p>{p.role_summary}</p>
            <h3>Likely process</h3><ol>{p.likely_process.map((x, i) => <li key={i}>{x}</li>)}</ol>
            <h3>Technical topics</h3>
            <ul>{p.technical_topics.map((t, i) => <li key={i}><strong>{t.topic}</strong> — {t.why}<div className="small muted">{t.how_to_prepare}</div></li>)}</ul>
            <h3>Study plan</h3>
            {p.study_plan.map((s) => <div key={s.day} className="small" style={{ marginBottom: 6 }}><strong>Day {s.day}: {s.focus}</strong><ul>{s.tasks.map((t, i) => <li key={i}>{t}</li>)}</ul></div>)}
          </div>
          <div>
            <QList title="Coding" qs={p.coding_questions} />
            <QList title="System design / ML" qs={p.system_design_or_ml_questions} />
            <QList title="Behavioral" qs={p.behavioral_questions} />
            <QList title="Your resume deep-dive" qs={p.resume_deep_dive} />
            <h3>Questions to ask them</h3><ul>{p.questions_to_ask_them.map((q, i) => <li key={i}>{q}</li>)}</ul>
          </div>
        </div>
      )}
    </div>
  );
}

const STATUSES = ["saved", "preparing", "applied", "assessment", "interviewing", "offer", "rejected", "withdrawn", "ghosted"];

function TrackerTab({ d, action, onChange }: TabProps) {
  const a = d.application;
  const [notes, setNotes] = useState(a?.notes ?? "");
  const [next, setNext] = useState(a?.next_action ?? "");
  const [due, setDue] = useState(a?.next_action_due?.slice(0, 10) ?? "");
  const save = (patch: Record<string, unknown>) => action.run("track", () => api.updateApplication(d.job.id, patch)).then((r) => r && onChange());
  return (
    <div className="grid grid-2">
      <div className="card">
        <h2>Application</h2>
        <div className="field"><label>Status</label>
          <select value={a?.status ?? ""} onChange={(e) => save({ status: e.target.value })}>
            {!a && <option value="">Not tracked</option>}
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select></div>
        <div className="field"><label>Next action</label><input value={next} onChange={(e) => setNext(e.target.value)} placeholder="e.g. Follow up with recruiter" /></div>
        <div className="field"><label>Due</label><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></div>
        <div className="field"><label>Notes</label><textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
        <button className="primary" onClick={() => save({ notes, next_action: next, ...(due ? { next_action_due: new Date(due).toISOString() } : {}) })}>Save</button>
      </div>
      <div className="card">
        <h2>History</h2>
        {a?.events?.length ? a.events.slice().reverse().map((e) => (
          <div key={e.id} className="small" style={{ marginBottom: 6 }}>
            <span className="muted">{fmtDate(e.created_at)}</span> · <strong>{e.kind.replace("_", " ")}</strong>{" "}
            {e.kind === "status_change" ? `${e.detail.from ?? "—"} → ${e.detail.to}` : ""}
            {e.kind === "message" ? `${e.detail.kind ?? ""} message ${e.detail.status}` : ""}
          </div>
        )) : <p className="muted">Not tracked yet. Set a status to start tracking.</p>}
        {d.match.explanation && <><h3>Saved explanation</h3><Md>{d.match.explanation}</Md></>}
      </div>
    </div>
  );
}
