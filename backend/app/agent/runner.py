"""The JobJugaad agent loop.

goal -> [model reasons, picks tools] -> execute tools -> observe results -> repeat
until the model ends its turn, the step budget runs out, or the user stops it.

Design choices:
  * Manual loop (not the SDK tool runner) so every step is persisted for the UI and
    the run can be stopped between steps.
  * The transcript is append-only and replayed verbatim (including thinking blocks),
    so follow-up messages continue the same run with full context.
  * Consequential actions are impossible from here: the only send-capable tool files a
    pending approval request (see services/approvals.py).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any

from app import llm
from app.agent.tools import TOOL_MAP, ToolContext, ToolError, definitions
from app.config import get_settings
from app.db import SessionLocal
from app.models import AgentRun, AgentStep
from app.services import memory

log = logging.getLogger(__name__)
settings = get_settings()

SYSTEM_PROMPT = """You are JobJugaad, an autonomous job-search agent working on behalf of one candidate - typically a \
university student or new graduate targeting software engineering, backend, full-stack and AI/ML roles \
(internship, new grad, entry level, 0-2 years).

How you work
- Treat each request as a goal. Plan briefly, then use tools to gather facts, act, observe results, and keep going \
until the goal is met. Chain tools: e.g. search -> evaluate the best matches -> research the company -> tailor resume \
-> draft outreach -> request approval -> track the application.
- Start by checking the candidate profile unless you already have it in this conversation. If key fields are missing \
(graduation year, work authorization, preferred roles/locations), say so and continue with what you have.
- Ground every claim in tool output. Scores come from the deterministic matcher; explain them, don't invent new ones.
- Eligibility blockers (no sponsorship when the candidate needs it, senior roles, graduation-year windows, \
enrollment requirements) matter more than skill fit. Never recommend applying to a job the candidate is ineligible \
for without flagging it.
- Never fabricate candidate experience, skills, metrics or contacts. If you need information only the user has \
(e.g. a recruiter's name), leave a placeholder and ask.

Safety and approval
- You cannot send messages, submit applications or contact anyone. To send a drafted message you must call \
request_approval_to_send; the human decides. Never say something was sent or submitted unless a tool result says so.
- Internal bookkeeping (tracking applications, saving memories) is fine without approval.

Memory
- Use recall_memories when past interactions could matter (previous outreach to a company, stated preferences, \
feedback on earlier drafts). Use save_memory for durable new facts or preferences the user states \
(not for things already in the profile).

Final answer
- Finish with a concise summary for the user: what you did, the key findings (with job ids, scores and eligibility), \
anything awaiting their approval, and 2-4 recommended next steps. Use short markdown sections and bullets."""


def _serialize(blocks: list[Any]) -> list[dict[str, Any]]:
    out = []
    for b in blocks:
        if b.type == "fallback":  # audit marker only; not needed in replayed history
            continue
        out.append(b.model_dump(mode="json", exclude_none=True))
    return out


class AgentRunner:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self.db = SessionLocal()

    def _step(self, run: AgentRun, kind: str, content: dict, tool_name: str = "") -> None:
        idx = len(run.steps)
        run.steps.append(AgentStep(index=idx, kind=kind, tool_name=tool_name, content=content))
        self.db.commit()

    def _context_preamble(self, run: AgentRun) -> str:
        core = memory.core_memories(self.db, run.user_id)
        relevant = memory.recall(self.db, run.user_id, run.goal, limit=8)
        seen, lines = set(), []
        for m in [*core, *relevant]:
            if m.id not in seen:
                seen.add(m.id)
                lines.append(f"- ({m.kind}, {m.created_at.date().isoformat()}) {m.content}")
        mem = "\n".join(lines) or "- (none yet)"
        return f"<context>\nToday: {datetime.now(UTC).date().isoformat()}\nWhat you remember about this user:\n{mem}\n</context>"

    def start(self, follow_up: str | None = None) -> None:
        run = self.db.get(AgentRun, self.run_id)
        try:
            if follow_up is None:
                run.transcript = [{"role": "user", "content": f"{self._context_preamble(run)}\n\nGoal: {run.goal}"}]
            else:
                run.transcript = [*run.transcript, {"role": "user", "content": follow_up}]
                self._step(run, "user", {"text": follow_up})
            run.status = "running"
            self.db.commit()
            self._loop(run)
        except llm.LLMUnavailable as e:
            self._fail(run, str(e))
        except Exception as e:  # never leave a run stuck in 'running'
            log.exception("Agent run %s crashed", self.run_id)
            self._fail(run, f"{type(e).__name__}: {e}")
        finally:
            self.db.close()

    def _fail(self, run: AgentRun, error: str) -> None:
        self.db.rollback()
        run = self.db.get(AgentRun, self.run_id)
        run.status, run.error, run.finished_at = "failed", error, datetime.now(UTC)
        self._step(run, "error", {"error": error})

    def _loop(self, run: AgentRun) -> None:
        tools = definitions()
        ctx = ToolContext(db=self.db, user_id=run.user_id, run_id=run.id)
        usage = dict(run.usage or {})
        steps_this_turn = 0

        while True:
            self.db.refresh(run)
            if run.status == "stopping":
                run.status, run.finished_at = "stopped", datetime.now(UTC)
                self._step(run, "final", {"text": "Stopped by user."})
                return
            if steps_this_turn >= settings.agent_max_steps:
                run.status, run.finished_at = "completed", datetime.now(UTC)
                run.final_answer = run.final_answer or "Step budget reached before the goal was fully completed."
                self._step(run, "final", {"text": run.final_answer, "truncated": True})
                return
            steps_this_turn += 1

            message = llm.agent_turn(system=SYSTEM_PROMPT, messages=run.transcript, tools=tools)
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                usage[k] = usage.get(k, 0) + (getattr(message.usage, k, 0) or 0)
            run.usage = usage
            run.transcript = [*run.transcript, {"role": "assistant", "content": _serialize(message.content)}]
            self.db.commit()

            for b in message.content:
                if b.type == "thinking" and b.thinking:
                    self._step(run, "thinking", {"text": b.thinking})
                elif b.type == "text" and b.text.strip() and message.stop_reason == "tool_use":
                    self._step(run, "message", {"text": b.text})

            if message.stop_reason == "pause_turn":
                continue
            if message.stop_reason == "max_tokens":
                raise llm.LLMError("Model response was truncated (max_tokens).")
            tool_uses = [b for b in message.content if b.type == "tool_use"]
            if message.stop_reason != "tool_use" or not tool_uses:
                text = "\n".join(b.text for b in message.content if b.type == "text").strip()
                run.final_answer, run.status, run.finished_at = text, "completed", datetime.now(UTC)
                self._step(run, "final", {"text": text})
                return

            results = []
            for tu in tool_uses:
                self._step(run, "tool_call", {"input": tu.input, "tool_use_id": tu.id}, tool_name=tu.name)
                content, is_error = self._execute(ctx, tu.name, tu.input)
                self._step(run, "tool_result", {"output": content, "is_error": is_error, "tool_use_id": tu.id},
                           tool_name=tu.name)
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": json.dumps(content, default=str)[:60000], "is_error": is_error})
            # All results for one assistant turn go back in a single user message.
            run.transcript = [*run.transcript, {"role": "user", "content": results}]
            self.db.commit()

    def _execute(self, ctx: ToolContext, name: str, args: Any) -> tuple[dict, bool]:
        tool = TOOL_MAP.get(name)
        if tool is None:
            return {"error": f"Unknown tool '{name}'"}, True
        try:
            return tool.handler(ctx, tool.normalize(args)), False
        except ToolError as e:
            self.db.rollback()
            return {"error": str(e)}, True
        except llm.LLMUnavailable:
            raise
        except llm.LLMError as e:
            self.db.rollback()
            return {"error": f"AI sub-task failed: {e}"}, True
        except Exception as e:
            log.exception("Tool %s failed", name)
            self.db.rollback()
            return {"error": f"{type(e).__name__}: {e}"}, True


def start_run_async(run_id: int, follow_up: str | None = None) -> None:
    threading.Thread(target=AgentRunner(run_id).start, args=(follow_up,), daemon=True,
                     name=f"agent-run-{run_id}").start()
