import { useCallback, useEffect, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import { Link } from "react-router-dom";
import type { Eligibility } from "../types";

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(fn, deps);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await load());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [load]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, setData, error, loading, reload };
}

/** Wraps an async action with busy + error state for buttons. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(key);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    } finally {
      setBusy(null);
    }
  }, []);
  return { busy, error, setError, run };
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" />;
}

export function ErrorBanner({ error }: { error: string | null }) {
  return error ? <div className="banner error" role="alert">{error}</div> : null;
}

export function Busy({ on, children }: { on: boolean; children: ReactNode }) {
  return <>{on ? <><Spinner /> Working…</> : children}</>;
}

export function ScoreBadge({ score }: { score: number }) {
  const cls = score >= 70 ? "high" : score >= 45 ? "mid" : "low";
  return <div className={`score ${cls}`} title="Match score (0-100)">{Math.round(score)}</div>;
}

export function EligibilityPill({ value }: { value: Eligibility }) {
  const cls = value === "eligible" ? "good" : value === "uncertain" ? "warn" : "bad";
  return <span className={`pill ${cls}`}>{value}</span>;
}

export function StatusPill({ status }: { status: string }) {
  const cls =
    ["offer", "sent", "executed", "approved", "completed"].includes(status) ? "good"
      : ["rejected", "failed", "withdrawn", "ghosted"].includes(status) ? "bad"
        : ["pending", "pending_approval", "running", "queued", "interviewing", "assessment"].includes(status) ? "warn"
          : status === "applied" ? "accent" : "neutral";
  return <span className={`pill ${cls}`}>{status.replace(/_/g, " ")}</span>;
}

export function TagInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...value, ...parts.filter((p) => !value.includes(p))]);
    setDraft("");
  };
  return (
    <div className="stack" style={{ gap: 6 }}>
      <input
        value={draft}
        placeholder={placeholder ?? "Type and press Enter"}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); add(); }
        }}
        onBlur={add}
      />
      {value.length > 0 && (
        <div className="tags">
          {value.map((t) => (
            <span className="tag" key={t}>
              {t}
              <button type="button" aria-label={`remove ${t}`} onClick={() => onChange(value.filter((x) => x !== t))}>×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function JobLink({ id, children }: { id: number; children: ReactNode }) {
  return <Link to={`/jobs/${id}`}>{children}</Link>;
}

export function Md({ children }: { children: string }) {
  return <div className="prose"><Markdown>{children}</Markdown></div>;
}

export function fmtDate(s: string | null | undefined) {
  if (!s) return "";
  return new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function salary(min: number | null, max: number | null, cur: string) {
  if (!max) return "";
  const k = (n: number) => `${Math.round(n / 1000)}k`;
  return `${cur || ""} ${min ? `${k(min)}–` : ""}${k(max)}`.trim();
}
