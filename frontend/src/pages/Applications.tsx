import { api } from "../api";
import { ErrorBanner, JobLink, Spinner, fmtDate, useAction, useAsync } from "../components/ui";

const BOARD = ["saved", "preparing", "applied", "assessment", "interviewing", "offer"];
const CLOSED = ["rejected", "withdrawn", "ghosted"];

export default function ApplicationsPage() {
  const data = useAsync(() => api.applications(), []);
  const action = useAction();
  const apps = data.data?.applications ?? [];

  const move = async (jobId: number, status: string) => {
    if (await action.run("move", () => api.updateApplication(jobId, { status }))) data.reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Applications</h1>
          <div className="subtitle">{apps.length} tracked · status changes are remembered and inform follow-up suggestions.</div>
        </div>
      </div>
      <ErrorBanner error={data.error ?? action.error} />
      {data.loading && !data.data ? <div className="empty"><Spinner /></div> : (
        <>
          <div className="kanban">
            {BOARD.map((status) => {
              const items = apps.filter((a) => a.status === status);
              return (
                <div className="column" key={status}>
                  <h3>{status} <span className="muted">{items.length}</span></h3>
                  {items.map((a) => (
                    <div className="kcard" key={a.id}>
                      <JobLink id={a.job.id}><strong>{a.job.title}</strong></JobLink>
                      <div className="small muted">{a.job.company}</div>
                      {a.next_action && <div className="small" style={{ marginTop: 4 }}>→ {a.next_action}{a.next_action_due ? ` (${fmtDate(a.next_action_due)})` : ""}</div>}
                      {a.applied_at && <div className="small muted">Applied {fmtDate(a.applied_at)}</div>}
                      <select className="mt small" style={{ marginTop: 6 }} value={a.status} onChange={(e) => move(a.job.id, e.target.value)} aria-label="Change status">
                        {[...BOARD, ...CLOSED].map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
          <div className="card mt">
            <h2>Closed</h2>
            {apps.filter((a) => CLOSED.includes(a.status)).map((a) => (
              <p key={a.id} className="small"><JobLink id={a.job.id}>{a.job.company} — {a.job.title}</JobLink> · {a.status}</p>
            ))}
            {!apps.some((a) => CLOSED.includes(a.status)) && <p className="muted">None.</p>}
          </div>
        </>
      )}
    </>
  );
}
