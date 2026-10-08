import type {
  AgentRun, Application, Approval, JobDetail, Match, MemoryItem, OutreachMessage, Prep, Profile, Recommendations,
  Research, Tailored,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, { ...init, headers: { ...headers, ...(init.headers as object) } });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T,>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) });
const patch = <T,>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

function qs(params: Record<string, string | number | undefined | null>) {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && s.set(k, String(v)));
  const out = s.toString();
  return out ? `?${out}` : "";
}

export const api = {
  health: () => request<{ status: string; model: string; llm_credentials_detected: boolean }>("/health"),

  profile: () => request<Profile>("/profile"),
  updateProfile: (p: Partial<Profile>) => put<Profile>("/profile", p),
  uploadResume: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ profile: Profile; warning: string | null }>("/resumes", { method: "POST", body: fd });
  },

  discover: (body: {
    keywords: string[]; companies: string[]; levels: string[]; work_modes: string[]; location?: string | null;
    include_ineligible: boolean; limit: number;
  }) => post<{ fetched: number; relevant: number; errors: string[]; matches: Match[] }>("/jobs/discover", body),
  jobs: (p: { min_score?: number; eligibility?: string; q?: string; level?: string; work_mode?: string; limit?: number }) =>
    request<Match[]>(`/jobs${qs(p)}`),
  addManualJob: (b: { company: string; title: string; description: string; location: string; url: string }) =>
    post<Match>("/jobs/manual", b),
  job: (id: number) => request<JobDetail>(`/jobs/${id}`),
  explain: (id: number) => post<Match>(`/jobs/${id}/explain`),
  research: (id: number, refresh = false) => post<Research>(`/jobs/${id}/research`, { refresh }),
  tailor: (id: number) => post<Tailored>(`/jobs/${id}/tailor`),
  prep: (id: number, days: number) => post<Prep>(`/jobs/${id}/interview-prep`, { days }),

  draftOutreach: (b: {
    job_id: number | null; kind: string; channel: string; recipient_name: string; recipient_role: string;
    recipient_contact: string; context: string;
  }) => post<OutreachMessage>("/outreach", b),
  editOutreach: (id: number, b: Partial<OutreachMessage>) => patch<OutreachMessage>(`/outreach/${id}`, b),
  requestApproval: (id: number, reason: string) => post<Approval>(`/outreach/${id}/request-approval`, { reason }),
  markSent: (id: number) => post<OutreachMessage>(`/outreach/${id}/mark-sent`),

  approvals: (status = "pending") => request<Approval[]>(`/approvals${qs({ status })}`),
  decide: (id: number, approve: boolean, note: string, edits?: Partial<OutreachMessage>) =>
    post<Approval>(`/approvals/${id}/decision`, { approve, note, edits }),

  applications: () => request<{ statuses: string[]; applications: Application[] }>("/applications"),
  updateApplication: (jobId: number, b: Partial<Application>) => put<Application>(`/applications/${jobId}`, b),
  recommendations: () => request<Recommendations>("/recommendations"),

  memories: (q = "") => request<MemoryItem[]>(`/memories${qs({ q })}`),
  addMemory: (b: { content: string; kind: string; importance: number }) => post<MemoryItem>("/memories", b),
  deleteMemory: (id: number) => request<void>(`/memories/${id}`, { method: "DELETE" }),

  runs: () => request<AgentRun[]>("/agent/runs"),
  run: (id: number) => request<AgentRun>(`/agent/runs/${id}`),
  startRun: (goal: string) => post<AgentRun>("/agent/runs", { goal }),
  followUp: (id: number, text: string) => post<AgentRun>(`/agent/runs/${id}/messages`, { text }),
  stopRun: (id: number) => post<AgentRun>(`/agent/runs/${id}/stop`),
};
