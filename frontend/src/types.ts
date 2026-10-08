export type Eligibility = "eligible" | "uncertain" | "ineligible";

export interface WorkAuthorization {
  authorized_countries: string[];
  citizenship: string[];
  needs_sponsorship: boolean | null;
  has_clearance?: boolean;
  notes?: string;
}

export interface Experience {
  company: string;
  title: string;
  location?: string;
  start: string;
  end: string;
  is_internship?: boolean;
  bullets: string[];
  skills: string[];
}

export interface Profile {
  id: number;
  version: number;
  full_name: string;
  email: string;
  phone: string;
  location: string;
  links: Record<string, string>;
  headline: string;
  summary: string;
  education: Record<string, string>[];
  experience: Experience[];
  projects: { name: string; description: string; bullets: string[]; skills: string[]; url?: string }[];
  skills: string[];
  certifications: string[];
  graduation_year: number | null;
  experience_months: number;
  preferred_roles: string[];
  preferred_levels: string[];
  preferred_locations: string[];
  work_modes: string[];
  willing_to_relocate: boolean;
  min_salary: number | null;
  salary_currency: string;
  target_companies: string[];
  required_technologies: string[];
  avoid_technologies: string[];
  work_authorization: Partial<WorkAuthorization>;
}

export interface Job {
  id: number;
  source: string;
  company: string;
  title: string;
  location: string;
  work_mode: string;
  url: string;
  level: string;
  employment_type: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  posted_at: string | null;
  description?: string;
}

export interface Component {
  score: number;
  weight: number;
  points: number;
  detail: string;
}

export interface Match {
  job: Job;
  score: number;
  eligibility: Eligibility;
  eligibility_reasons: { check: string; status: "pass" | "fail" | "unknown"; detail: string }[];
  breakdown: {
    components?: Record<string, Component>;
    fit?: number;
    avoid_penalty?: number;
    eligibility_multiplier?: number;
    skills?: Record<string, string[]>;
    target_company?: boolean;
    llm?: {
      recommendation: string;
      summary: string;
      reasons_for: string[];
      reasons_against: string[];
      how_to_improve_odds: string[];
    };
  };
  strengths: string[];
  gaps: string[];
  explanation: string;
  application_status: string | null;
}

export interface AppEvent {
  id: number;
  kind: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface Application {
  id: number;
  job: Job;
  status: string;
  priority: number;
  applied_at: string | null;
  next_action: string;
  next_action_due: string | null;
  notes: string;
  tailored_resume_id: number | null;
  updated_at: string;
  events?: AppEvent[];
}

export interface OutreachMessage {
  id: number;
  job_id: number | null;
  kind: string;
  channel: string;
  recipient_name: string;
  recipient_role: string;
  recipient_contact: string;
  subject: string;
  body: string;
  status: string;
  sent_at: string | null;
  created_at: string;
}

export interface Approval {
  id: number;
  action_type: string;
  summary: string;
  status: string;
  agent_run_id: number | null;
  decision_note: string;
  result: Record<string, unknown>;
  created_at: string;
  message: OutreachMessage | null;
}

export interface Tailored {
  id: number;
  job_id: number;
  markdown: string;
  change_log: string[];
  warnings: string[];
  content: { honest_gaps?: string[]; keywords_covered?: string[] };
  created_at: string;
}

export interface Research {
  id: number;
  company: string;
  created_at: string;
  content: {
    overview: string;
    products: string[];
    tech_stack: string[];
    engineering_culture: string;
    recent_news: { headline: string; date: string; why_it_matters: string }[];
    interview_process: string;
    team_or_role_insights: string;
    talking_points: string[];
    red_flags: string[];
    sources: { title: string; url: string }[];
    confidence: string;
  };
}

export interface PrepQuestion {
  question: string;
  what_they_assess: string;
  answer_guidance: string;
}

export interface Prep {
  id: number;
  created_at: string;
  content: {
    role_summary: string;
    likely_process: string[];
    technical_topics: { topic: string; why: string; how_to_prepare: string }[];
    coding_questions: PrepQuestion[];
    system_design_or_ml_questions: PrepQuestion[];
    behavioral_questions: PrepQuestion[];
    resume_deep_dive: PrepQuestion[];
    questions_to_ask_them: string[];
    study_plan: { day: number; focus: string; tasks: string[] }[];
  };
}

export interface JobDetail {
  job: Job;
  match: Match;
  application: Application | null;
  research: Research | null;
  tailored_resume: Tailored | null;
  interview_prep: Prep | null;
  messages: OutreachMessage[];
}

export interface MemoryItem {
  id: number;
  kind: string;
  content: string;
  tags: string[];
  importance: number;
  source: string;
  created_at: string;
}

export interface AgentStep {
  index: number;
  kind: "thinking" | "message" | "tool_call" | "tool_result" | "final" | "error" | "user";
  tool_name: string;
  content: Record<string, any>;
  created_at: string;
}

export interface AgentRun {
  id: number;
  goal: string;
  status: string;
  final_answer: string;
  error: string;
  usage: Record<string, number>;
  created_at: string;
  finished_at: string | null;
  steps?: AgentStep[];
}

export interface Recommendations {
  apply_next: { job_id: number; company: string; title: string; url: string; score: number; eligibility: Eligibility; priority: number; reasons: string[] }[];
  follow_ups: { job_id: number; company: string; title: string; action: string; due: string }[];
}
