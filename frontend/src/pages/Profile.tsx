import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Busy, ErrorBanner, Spinner, TagInput, useAction, useAsync } from "../components/ui";
import type { Profile } from "../types";

const LEVELS = ["internship", "new_grad", "entry", "mid"];
const MODES = ["remote", "hybrid", "onsite"];

export default function ProfilePage() {
  const loaded = useAsync(() => api.profile(), []);
  const [p, setP] = useState<Profile | null>(null);
  const [saved, setSaved] = useState(false);
  const [warning, setWarning] = useState<string | null>(null);
  const action = useAction();
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (loaded.data) setP(loaded.data); }, [loaded.data]);
  if (!p) return loaded.error ? <ErrorBanner error={loaded.error} /> : <div className="empty"><Spinner /></div>;

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => { setP({ ...p, [k]: v }); setSaved(false); };
  const wa = { authorized_countries: [], citizenship: [], needs_sponsorship: null, ...p.work_authorization };
  const setWa = (patch: Partial<typeof wa>) => set("work_authorization", { ...wa, ...patch });
  const toggle = (k: "preferred_levels" | "work_modes", v: string) =>
    set(k, p[k].includes(v) ? p[k].filter((x) => x !== v) : [...p[k], v]);

  const upload = async (f: File) => {
    const res = await action.run("upload", () => api.uploadResume(f));
    if (res) { setP(res.profile); setWarning(res.warning); }
  };
  const save = async () => {
    const res = await action.run("save", () => api.updateProfile({
      full_name: p.full_name, email: p.email, phone: p.phone, location: p.location, headline: p.headline,
      summary: p.summary, skills: p.skills, graduation_year: p.graduation_year,
      preferred_roles: p.preferred_roles, preferred_levels: p.preferred_levels, preferred_locations: p.preferred_locations,
      work_modes: p.work_modes, willing_to_relocate: p.willing_to_relocate, min_salary: p.min_salary,
      salary_currency: p.salary_currency, target_companies: p.target_companies,
      required_technologies: p.required_technologies, avoid_technologies: p.avoid_technologies,
      work_authorization: wa as Profile["work_authorization"],
    }));
    if (res) { setP(res); setSaved(true); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Profile & preferences</h1>
          <div className="subtitle">Facts come from your resume; preferences are yours to set. Saving re-scores every job.</div>
        </div>
        <button className="primary" onClick={save} disabled={!!action.busy}>
          <Busy on={action.busy === "save"}>{saved ? "Saved ✓" : "Save profile"}</Busy>
        </button>
      </div>
      <ErrorBanner error={action.error} />
      {warning && <div className="banner warn">{warning}</div>}

      <div className="card">
        <div className="spread">
          <div>
            <h2>Resume</h2>
            <p className="muted small">PDF, DOCX, TXT or MD. Parsed with AI into structured experience, projects and skills.</p>
          </div>
          <div>
            <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            <button className="primary" onClick={() => fileRef.current?.click()} disabled={!!action.busy}>
              <Busy on={action.busy === "upload"}>Upload resume</Busy>
            </button>
          </div>
        </div>
        {p.experience.length > 0 && (
          <div className="grid grid-2 mt">
            <div>
              <h3>Experience ({Math.round(p.experience_months / 12 * 10) / 10} yrs counted)</h3>
              {p.experience.map((e, i) => <p key={i} className="small"><strong>{e.title}</strong> · {e.company} <span className="muted">({e.start} – {e.end}){e.is_internship ? " · internship" : ""}</span></p>)}
            </div>
            <div>
              <h3>Projects</h3>
              {p.projects.map((pr, i) => <p key={i} className="small"><strong>{pr.name}</strong> <span className="muted">{pr.skills.join(", ")}</span></p>)}
              <h3>Education</h3>
              {p.education.map((e, i) => <p key={i} className="small">{e.degree} {e.field} · {e.school} <span className="muted">{e.end}</span></p>)}
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-2 mt">
        <div className="card">
          <h2>About you</h2>
          <div className="grid grid-2">
            <div className="field"><label>Full name</label><input value={p.full_name} onChange={(e) => set("full_name", e.target.value)} /></div>
            <div className="field"><label>Email</label><input value={p.email} onChange={(e) => set("email", e.target.value)} /></div>
            <div className="field"><label>Location</label><input value={p.location} onChange={(e) => set("location", e.target.value)} /></div>
            <div className="field"><label>Graduation year</label>
              <input type="number" min={1990} max={2040} value={p.graduation_year ?? ""} onChange={(e) => set("graduation_year", e.target.value ? Number(e.target.value) : null)} /></div>
          </div>
          <div className="field"><label>Headline</label><input value={p.headline} onChange={(e) => set("headline", e.target.value)} /></div>
          <div className="field"><label>Skills</label><TagInput value={p.skills} onChange={(v) => set("skills", v)} /></div>

          <h3>Work authorization</h3>
          <p className="small muted">Used only for eligibility checks (e.g. postings that don't sponsor visas).</p>
          <div className="grid grid-2">
            <div className="field"><label>Authorized to work in (country codes)</label>
              <TagInput value={wa.authorized_countries ?? []} onChange={(v) => setWa({ authorized_countries: v })} placeholder="e.g. US, IN" /></div>
            <div className="field"><label>Citizenship (country codes)</label>
              <TagInput value={wa.citizenship ?? []} onChange={(v) => setWa({ citizenship: v })} placeholder="e.g. IN" /></div>
          </div>
          <div className="field"><label>Do you need visa sponsorship?</label>
            <select value={wa.needs_sponsorship == null ? "" : String(wa.needs_sponsorship)}
              onChange={(e) => setWa({ needs_sponsorship: e.target.value === "" ? null : e.target.value === "true" })}>
              <option value="">Not specified</option><option value="false">No</option><option value="true">Yes, now or in the future</option>
            </select></div>
        </div>

        <div className="card">
          <h2>What you're looking for</h2>
          <div className="field"><label>Preferred roles</label><TagInput value={p.preferred_roles} onChange={(v) => set("preferred_roles", v)} placeholder="e.g. Backend Engineer, ML Engineer" /></div>
          <div className="field"><label>Levels</label>
            <div className="row">{LEVELS.map((l) => <label key={l} className="checkbox"><input type="checkbox" checked={p.preferred_levels.includes(l)} onChange={() => toggle("preferred_levels", l)} />{l.replace("_", " ")}</label>)}</div></div>
          <div className="field"><label>Work modes</label>
            <div className="row">{MODES.map((m) => <label key={m} className="checkbox"><input type="checkbox" checked={p.work_modes.includes(m)} onChange={() => toggle("work_modes", m)} />{m}</label>)}
              <label className="checkbox"><input type="checkbox" checked={p.willing_to_relocate} onChange={(e) => set("willing_to_relocate", e.target.checked)} />willing to relocate</label></div></div>
          <div className="field"><label>Preferred locations</label><TagInput value={p.preferred_locations} onChange={(v) => set("preferred_locations", v)} placeholder="e.g. New York, Remote" /></div>
          <div className="grid grid-2">
            <div className="field"><label>Minimum salary (annual)</label><input type="number" min={0} value={p.min_salary ?? ""} onChange={(e) => set("min_salary", e.target.value ? Number(e.target.value) : null)} /></div>
            <div className="field"><label>Currency</label><input value={p.salary_currency} onChange={(e) => set("salary_currency", e.target.value.toUpperCase())} /></div>
          </div>
          <div className="field"><label>Target companies</label><TagInput value={p.target_companies} onChange={(v) => set("target_companies", v)} /></div>
          <div className="field"><label>Technologies you want to use</label><TagInput value={p.required_technologies} onChange={(v) => set("required_technologies", v)} /></div>
          <div className="field"><label>Technologies to avoid</label><TagInput value={p.avoid_technologies} onChange={(v) => set("avoid_technologies", v)} /></div>
        </div>
      </div>
    </>
  );
}
