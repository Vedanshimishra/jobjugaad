import { useState } from "react";
import { api } from "../api";
import { ErrorBanner, Spinner, fmtDate, useAction, useAsync } from "../components/ui";

export default function MemoryPage() {
  const [q, setQ] = useState("");
  const list = useAsync(() => api.memories(q), [q]);
  const action = useAction();
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("preference");
  const [importance, setImportance] = useState(4);

  const add = async () => {
    if (await action.run("add", () => api.addMemory({ content, kind, importance }))) { setContent(""); list.reload(); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Memory</h1>
          <div className="subtitle">What the agent remembers across sessions. Importance 4–5 preferences are always in its context.</div>
        </div>
      </div>
      <ErrorBanner error={action.error ?? list.error} />
      <div className="card">
        <h2>Tell the agent something to remember</h2>
        <div className="row">
          <input style={{ flex: 3, minWidth: 220 }} value={content} onChange={(e) => setContent(e.target.value)} placeholder="e.g. I prefer early-stage startups and don't want to work in ad-tech" />
          <select style={{ flex: 1, minWidth: 120 }} value={kind} onChange={(e) => setKind(e.target.value)}>
            {["preference", "fact", "feedback", "interaction", "outcome"].map((k) => <option key={k}>{k}</option>)}
          </select>
          <select style={{ width: 130 }} value={importance} onChange={(e) => setImportance(Number(e.target.value))}>
            {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>importance {n}</option>)}
          </select>
          <button className="primary" disabled={content.trim().length < 3 || !!action.busy} onClick={add}>Remember</button>
        </div>
      </div>
      <div className="card mt">
        <input placeholder="Search memories" value={q} onChange={(e) => setQ(e.target.value)} />
        {list.loading ? <div className="empty"><Spinner /></div> : (
          <table className="mt"><tbody>
            {list.data?.map((m) => (
              <tr key={m.id}>
                <td style={{ width: 110 }}><span className="pill neutral">{m.kind}</span></td>
                <td>{m.content}<div className="small muted">{fmtDate(m.created_at)} · {m.source} · importance {m.importance}</div></td>
                <td style={{ width: 70 }}><button className="ghost danger small" onClick={() => action.run("del", () => api.deleteMemory(m.id)).then(list.reload)}>Delete</button></td>
              </tr>
            ))}
          </tbody></table>
        )}
        {!list.loading && !list.data?.length && <div className="empty">No memories yet.</div>}
      </div>
    </>
  );
}
