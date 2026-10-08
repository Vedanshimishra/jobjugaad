# JobJugaad

An AI job-search agent for students and new grads targeting software engineering, backend, full-stack and AI/ML roles (internship, new grad, entry level, 0–2 years).

You give it a goal ("find AI/ML new-grad roles I'm eligible for, research the best one, tailor my resume and draft a referral request"). It plans, calls tools, observes the results and keeps going until the goal is met. It **never sends anything without your approval**.

## Quick start

Prerequisites: Python 3.11+ (developed on 3.13), Node 20+, and an Anthropic API key.

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # macOS/Linux: .venv/bin/pip
cp .env.example .env                                 # then set ANTHROPIC_API_KEY
.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload

# Frontend (second terminal)
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```

Then go to **Profile**, upload your resume and set your preferences (graduation year, roles, locations, work authorization). Search for jobs on **Jobs**, or give the **Agent** a goal.

Without an API key the deterministic parts still work: job discovery, eligibility checks, scoring, tracking, memory and approvals. Resume upload falls back to a basic parser. AI features return a clear "credentials missing" error.

Tests: `cd backend && .venv/Scripts/python -m pytest -q`

## Deploy (Render)

The repo has a `Dockerfile`, which builds the React app and serves it plus the API from one FastAPI service, and a `render.yaml` blueprint that sets up a web service and a Postgres database.

1. On [render.com](https://render.com), choose **New → Blueprint**, connect GitHub, and pick this repo.
2. When Render asks for `ANTHROPIC_API_KEY`, paste your key, then click **Apply**. The first build takes about 5–10 minutes.
3. Open the service URL. The browser asks for a username and password: use any username, and the password from **JOBJUGAAD_APP_PASSWORD** under the service's **Environment** tab. Render generates it randomly.

The password gate exists so that strangers who find the URL can't read your data or spend your API key. Free instances sleep when idle, so the first request after a while takes 30–60 seconds. Free Render Postgres databases expire after a fixed period, so upgrade the database if you want to keep your data.

## Architecture

```
frontend/ (React + Vite + TS)  ──/api──▶  backend/ (FastAPI + SQLAlchemy, SQLite by default)
                                              │
     ┌────────────────────────────────────────┼─────────────────────────────────────────┐
     │ agent/runner.py   manual tool-use loop: goal → Claude picks tools → execute →     │
     │                   observe → repeat; every step persisted; stoppable; resumable    │
     │ agent/tools.py    16 tools (search, evaluate, research, tailor, draft, track…)    │
     ├───────────────────────────────────────────────────────────────────────────────────┤
     │ services/  deterministic core            │ services/ai_tasks.py  Claude-backed     │
     │  jd_parser    level, YOE, sponsorship,   │  explain match, company research (web   │
     │               grad-year, salary parsing  │  search), resume tailoring + fabrication│
     │  eligibility  hard-constraint rules      │  checks, outreach, interview prep       │
     │  matching     explainable 0-100 score    │ llm.py  Anthropic SDK wrapper:          │
     │  jobs         Greenhouse/Lever/Ashby     │  structured outputs, adaptive thinking, │
     │  approvals    human-in-the-loop gate     │  streaming, refusal fallbacks           │
     │  memory       long-term memory           │                                         │
     │  prioritization  what to do next         │                                         │
     └───────────────────────────────────────────────────────────────────────────────────┘
```

### Why it is agentic, not a chatbot
- **Tool use with feedback.** The model gets your goal plus your saved memories, and chooses among 16 tools. Each result, including errors, goes back to it so it can adapt, for example retrying with a valid job id.
- **Multi-step workflows.** For example: search → evaluate the top matches → research the company → tailor resume → draft outreach → request approval → track the application.
- **Full trace.** Every reasoning summary, tool call and result is stored as an `AgentStep` and shown live in the UI.
- **Continuable.** The append-only transcript is stored with the run, so follow-up instructions continue with full context.
- **Guardrails.** There's a per-turn step budget, a stop button, and a tool layer that has no "send" capability at all.

### Human approval gate
No tool and no API route can contact anyone. The agent can only call `request_approval_to_send`, which creates a pending `ActionRequest`. Execution happens only in `approvals.decide()`, which is reachable only from the Approvals inbox, where you can edit the message before approving. Approved emails go out by SMTP if you configure it. Otherwise you copy the message, send it yourself and mark it sent. When you reject a draft, your note is saved as feedback the agent recalls next time.

### Match score (0–100)
| Component | Weight | Based on |
|---|---|---|
| Skills | 40 | Required skills ×1 and preferred ×0.5, from a curated taxonomy with aliases; smoothed so 1/1 isn't "perfect" |
| Role | 20 | Title vs. your preferred roles, plus domain affinity (an ML-heavy posting counts for AI/ML preferences) |
| Level | 15 | Internship / new grad / entry vs. your preferred levels |
| Location | 10 | Work mode plus preferred locations, relocation |
| Preferences | 10 | Must-have technologies, target companies |
| Compensation | 5 | Posted salary vs. your minimum |

Then: **− 15 per avoided technology** (max 30), then **× eligibility** (eligible 1.0, uncertain 0.85, ineligible 0.4). Each component's inputs are stored, so the UI and the agent can explain the number. Claude adds a written verdict (apply / stretch / skip) on request.

### Eligibility (separate from fit)
Checks are rule-based and each reports pass, fail or unknown:
- Seniority and years of experience. Internship months count at half weight.
- Graduation-year windows and cohort years in the title, e.g. "Intern (2027)".
- Internship enrollment requirements.
- Work authorization by country.
- "No sponsorship" and citizenship or clearance requirements.
- PhD or master's requirements.

### Truthfulness
Resume tailoring may only rephrase, reorder or drop your real content. After generation, the output is compared against your profile. It flags new technologies, unknown employers and numbers that aren't in your original resume, and lists the job requirements you don't meet under "honest gaps".

## Configuration
Everything lives in `backend/.env` (see `.env.example`). Main settings:
- the model (`claude-opus-5-5`)
- effort levels for the agent and for one-off tasks
- the agent's step budget
- which company job boards to search
- optional SMTP for sending approved emails

## Current limitations / next steps
- **Single local user.** All data is already scoped by `user_id`; real auth replaces `api/deps.py::current_user`.
- **Agent runs in a background thread.** For multi-instance deployment, move runs to a queue (RQ, Celery, Arq).
- **No migrations yet.** Tables are created on startup; add Alembic before schema changes in production.
- **Limited job sources.** Discovery covers public Greenhouse, Lever and Ashby boards. Add sources in `services/job_sources/` by implementing `fetch(board) -> list[RawJob]`.
- **Lexical memory retrieval.** It is transparent and needs no extra service; swap in embeddings if recall quality becomes an issue.
- **Markdown-only resume export.** PDF/DOCX export is a natural addition.
