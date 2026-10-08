import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner, Md, Spinner, StatusPill, fmtDate, useAsync } from "../components/ui";
import type { AgentRun, AgentStep } from "../types";

const ACTIVE = ["queued", "running", "stopping"];

const TOOL_LABELS: Record<string, string> = {
  get_candidate_profile: "Read profile",
  search_jobs: "Search job boards",
  list_known_jobs: "List known jobs",
  get_job_details: "Read job details",
  evaluate_job_match: "Evaluate match",
  add_job_from_text: "Add job",
  research_company: "Research company",
  tailor_resume: "Tailor resume",
  draft_outreach_message: "Draft message",
  request_approval_to_send: "Request your approval",
  track_application: "Update tracker",
  list_applications: "List applications",
  prioritize_jobs: "Prioritize",
  prepare_interview: "Interview prep",
  save_memory: "Save memory",
  recall_memories: "Recall memories",
};

function Step({ step }: { step: AgentStep }) {
  const c = step.content;
  switch (step.kind) {
    case "thinking":
      return <div className="step thinking small">{c.text}</div>;
    case "message":
      return <div className="step"><Md>{c.text}</Md></div>;
    case "user":
      return <div className="step user"><strong>You:</strong> {c.text}</div>;
    case "tool_call":
      return (
        <div className="step tool_call">
          <strong>→ {TOOL_LABELS[step.tool_name] ?? step.tool_name}</strong>{" "}
          <span className="muted small">{summarizeInput(c.input)}</span>
        </div>
      );
    case "tool_result":
      return (
        <div className={`step tool_result${c.is_error ? " err" : ""}`}>
          <details>
            <summary className="small">
              {c.is_error ? "✗ " : "✓ "}{TOOL_LABELS[step.tool_name] ?? step.tool_name}: {summarizeOutput(step.tool_name, c.output)}
            </summary>
            <pre className="pre mt">{JSON.stringify(c.output, null, 2)}</pre>
          </details>
        </div>
      );
    case "final":
      return <div className="step final"><Md>{c.text || "(no answer)"}</Md></div>;
    case "error":
      return <div className="step error">Error: {c.error}</div>;
  }
}

function summarizeInput(input: Record<string, unknown> | undefined) {
  if (!input) return "";
  const parts = Object.entries(input)
    .filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0))
    .map(([k, v]) => `${k}=${typeof v === "string" ? v.slice(0, 40) : JSON.stringify(v)}`);
  return parts.join(", ").slice(0, 160);
}

function summarizeOutput(tool: string, out: any) {
  if (!out) return "";
  if (out.error) return out.error;
  if (out.results) return `${out.results.length} jobs`;
  if (out.applications) return `${out.applications.length} applications`;
  if (out.apply_next) return `${out.apply_next.length} ranked, ${out.follow_ups.length} follow-ups`;
  if (tool === "request_approval_to_send") return "pending your approval";
  if (out.score !== undefined) return `score ${out.score}, ${out.eligibility}`;
  if (out.message_id) return `draft #${out.message_id}`;
  if (out.tailored_resume_id) return `tailored resume #${out.tailored_resume_id}`;
  return "done";
}

export default function AgentPage() {
  const { runId } = useParams();
  const nav = useNavigate();
  const runs = useAsync(() => api.runs(), [runId]);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [goal, setGoal] = useState("");
  const [reply, setReply] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!runId) { setRun(null); return; }
    let timer: number | undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await api.run(Number(runId));
        if (cancelled) return;
        setRun(r);
        if (ACTIVE.includes(r.status)) timer = window.setTimeout(poll, 1500);
        else runs.reload();
      } catch (e) {
        setError((e as Error).message);
      }
    };
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, run?.status === "queued"]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [run?.steps?.length]);

  const start = async () => {
    try {
      const r = await api.startRun(goal);
      setGoal("");
      nav(`/agent/${r.id}`);
    } catch (e) { setError((e as Error).message); }
  };
  const sendReply = async () => {
    if (!run) return;
    try {
      const r = await api.followUp(run.id, reply);
      setReply("");
      setRun({ ...run, ...r });
    } catch (e) { setError((e as Error).message); }
  };

  const active = run && ACTIVE.includes(run.status);
  const pendingApprovals = run?.steps?.some((s) => s.tool_name === "request_approval_to_send" && s.kind === "tool_result" && !s.content.is_error);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Agent</h1>
          <div className="subtitle">Every reasoning step and tool call is shown. Sending anything requires your approval.</div>
        </div>
      </div>
      <ErrorBanner error={error} />
      <div className="grid agent-grid">
        <div className="card" style={{ alignSelf: "start" }}>
          <h2>Runs</h2>
          <button className="primary" style={{ width: "100%" }} onClick={() => nav("/agent")}>New goal</button>
          <div className="stack mt" style={{ gap: 4 }}>
            {runs.data?.map((r) => (
              <Link key={r.id} to={`/agent/${r.id}`} className={`nav-link${String(r.id) === runId ? " active" : ""}`}>
                <span className="small" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.goal}</span>
              </Link>
            ))}
            {!runs.data?.length && <p className="muted small">No runs yet.</p>}
          </div>
        </div>

        <div className="card">
          {!run ? (
            <form className="stack" onSubmit={(e) => { e.preventDefault(); if (goal.trim()) void start(); }}>
              <h2>Give the agent a goal</h2>
              <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={4}
                placeholder="e.g. Find AI/ML new-grad roles in the Bay Area I'm eligible for, research the top 2 companies, tailor my resume for the best one and draft a referral request." />
              <div><button className="primary" disabled={!goal.trim()}>Start</button></div>
            </form>
          ) : (
            <>
              <div className="spread">
                <div>
                  <h2 style={{ marginBottom: 2 }}>{run.goal}</h2>
                  <div className="row small muted">
                    <StatusPill status={run.status} /> {fmtDate(run.created_at)}
                    {run.usage?.output_tokens ? <span>· {(run.usage.input_tokens + run.usage.output_tokens).toLocaleString()} tokens</span> : null}
                  </div>
                </div>
                {active && <button className="danger" onClick={() => api.stopRun(run.id).then(setRun)}>Stop</button>}
              </div>
              {pendingApprovals && (
                <div className="banner info mt">The agent queued actions for your review. <Link to="/approvals">Open approvals →</Link></div>
              )}
              <div className="timeline mt">
                {run.steps?.map((s) => <Step key={s.index} step={s} />)}
                {active && <div className="step muted"><Spinner /> {run.status === "stopping" ? "Stopping…" : "Working…"}</div>}
                {run.status === "failed" && run.error && !run.steps?.some((s) => s.kind === "error") && (
                  <div className="step error">{run.error}</div>
                )}
                <div ref={bottom} />
              </div>
              {!active && (
                <form className="row mt" onSubmit={(e) => { e.preventDefault(); if (reply.trim()) void sendReply(); }}>
                  <input style={{ flex: 1 }} value={reply} onChange={(e) => setReply(e.target.value)}
                    placeholder="Reply or give a follow-up instruction…" />
                  <button className="primary" disabled={!reply.trim()}>Send</button>
                </form>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
