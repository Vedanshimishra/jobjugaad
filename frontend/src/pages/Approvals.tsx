import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner, Spinner, StatusPill, fmtDate, useAction, useAsync } from "../components/ui";
import type { Approval } from "../types";

function ApprovalCard({ a, onDone }: { a: Approval; onDone: () => void }) {
  const m = a.message;
  const [subject, setSubject] = useState(m?.subject ?? "");
  const [body, setBody] = useState(m?.body ?? "");
  const [contact, setContact] = useState(m?.recipient_contact ?? "");
  const [note, setNote] = useState("");
  const action = useAction();
  const pending = a.status === "pending";

  const decide = async (approve: boolean) => {
    const edits = m && (subject !== m.subject || body !== m.body || contact !== m.recipient_contact)
      ? { subject, body, recipient_contact: contact } : undefined;
    if (await action.run(approve ? "approve" : "reject", () => api.decide(a.id, approve, note, edits))) onDone();
  };

  return (
    <div className="card">
      <div className="spread">
        <div>
          <strong>{a.summary}</strong>
          <div className="small muted">
            {fmtDate(a.created_at)}
            {a.agent_run_id && <> · proposed by <Link to={`/agent/${a.agent_run_id}`}>agent run #{a.agent_run_id}</Link></>}
            {m?.job_id && <> · <Link to={`/jobs/${m.job_id}`}>job</Link></>}
          </div>
        </div>
        <StatusPill status={a.status} />
      </div>
      <ErrorBanner error={action.error} />
      {m && (
        <div className="stack mt">
          <div className="grid grid-2">
            <div><label>To</label><div>{m.recipient_name || "—"} {m.recipient_role && <span className="muted">({m.recipient_role})</span>} · {m.channel}</div></div>
            <div><label>Email / profile</label><input value={contact} disabled={!pending} onChange={(e) => setContact(e.target.value)} /></div>
          </div>
          {m.channel === "email" && <div><label>Subject</label><input value={subject} disabled={!pending} onChange={(e) => setSubject(e.target.value)} /></div>}
          <div><label>Message (you can edit before approving)</label><textarea rows={8} value={body} disabled={!pending} onChange={(e) => setBody(e.target.value)} /></div>
        </div>
      )}
      {pending ? (
        <div className="row mt">
          <input style={{ flex: 1 }} placeholder="Optional note (rejection feedback is remembered by the agent)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="danger" disabled={!!action.busy} onClick={() => decide(false)}>Reject</button>
          <button className="primary" disabled={!!action.busy} onClick={() => decide(true)}>
            {action.busy === "approve" ? <Spinner /> : "Approve"}
          </button>
        </div>
      ) : (
        <p className="small muted mt">
          {a.result?.delivery === "manual" ? "Approved — copy the message and send it yourself, then mark it sent on the job page."
            : a.result?.delivery === "sent_via_smtp" ? `Sent by email to ${a.result.to}.`
              : a.result?.error ? `Failed: ${String(a.result.error)}` : a.decision_note}
        </p>
      )}
    </div>
  );
}

export default function ApprovalsPage({ onChange }: { onChange: (n: number) => void }) {
  const [status, setStatus] = useState("pending");
  const list = useAsync(async () => {
    const res = await api.approvals(status);
    if (status === "pending") onChange(res.length);
    return res;
  }, [status]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Approvals</h1>
          <div className="subtitle">Nothing leaves JobJugaad without your explicit approval.</div>
        </div>
        <select style={{ width: 180 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">Pending</option><option value="executed">Approved</option>
          <option value="rejected">Rejected</option><option value="failed">Failed</option><option value="">All</option>
        </select>
      </div>
      <ErrorBanner error={list.error} />
      {list.loading ? <div className="empty"><Spinner /></div> : list.data?.length ? (
        <div className="stack">{list.data.map((a) => <ApprovalCard key={a.id} a={a} onDone={list.reload} />)}</div>
      ) : <div className="card empty">Nothing here.</div>}
    </>
  );
}
