"""Agent loop + human-approval gate, with the LLM replaced by a scripted fake."""

from types import SimpleNamespace

import pytest

from app import llm
from app.agent import runner as runner_mod
from app.agent.tools import TOOL_MAP, ToolContext, ToolError
from app.models import ActionRequest, AgentRun, OutreachMessage
from app.services import approvals

from .conftest import make_job, make_profile


class Block(SimpleNamespace):
    def model_dump(self, **_):
        return {k: v for k, v in vars(self).items()}


def msg(stop, *blocks):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(stop_reason=stop, content=list(blocks), usage=usage)


def tool_use(id_, name, input_):
    return Block(type="tool_use", id=id_, name=name, input=input_)


def text(t):
    return Block(type="text", text=t)


@pytest.fixture
def draft(db):
    p = make_profile(db)
    j = make_job(db)
    m = OutreachMessage(user_id=p.user_id, job_id=j.id, kind="recruiter", channel="email",
                        recipient_name="Sam", body="Hi Sam", status="draft")
    db.add(m)
    db.commit()
    return p, j, m


def test_agent_cannot_send_without_approval(db, draft):
    p, _, m = draft
    out = TOOL_MAP["request_approval_to_send"].handler(ToolContext(db, p.user_id, None),
                                                      {"message_id": m.id, "reason": "strong match"})
    assert out["status"] == "pending_human_approval"
    db.refresh(m)
    assert m.status == "pending_approval" and m.sent_at is None
    # A second request for the same message is refused.
    with pytest.raises(ToolError):
        TOOL_MAP["request_approval_to_send"].handler(ToolContext(db, p.user_id, None),
                                                    {"message_id": m.id, "reason": "again"})


def test_approve_executes_and_reject_does_not(db, draft):
    p, _, m = draft
    req = approvals.propose(db, p.user_id, "send_outreach_message", "send", {"message_id": m.id})
    done = approvals.decide(db, p.user_id, req.id, approve=True, edits={"body": "Hi Sam, edited"})
    assert done.status == "executed" and done.result["delivery"] == "manual"  # no SMTP configured
    db.refresh(m)
    assert m.status == "approved" and m.body == "Hi Sam, edited"
    with pytest.raises(approvals.ApprovalError):
        approvals.decide(db, p.user_id, req.id, approve=True)

    m2 = OutreachMessage(user_id=p.user_id, kind="referral", channel="linkedin", body="x", status="draft")
    db.add(m2)
    db.commit()
    req2 = approvals.propose(db, p.user_id, "send_outreach_message", "send", {"message_id": m2.id})
    rej = approvals.decide(db, p.user_id, req2.id, approve=False, note="too formal")
    db.refresh(m2)
    assert rej.status == "rejected" and m2.status == "rejected"


def test_other_users_cannot_decide(db, draft):
    p, _, m = draft
    other = make_profile(db)
    req = approvals.propose(db, p.user_id, "send_outreach_message", "send", {"message_id": m.id})
    with pytest.raises(approvals.ApprovalError):
        approvals.decide(db, other.user_id, req.id, approve=True)


def test_agent_loop_chains_tools_and_finishes(db, monkeypatch, draft):
    p, j, m = draft
    script = iter([
        msg("tool_use", text("Checking profile and jobs."), tool_use("t1", "get_candidate_profile", {}),
            tool_use("t2", "list_known_jobs", {"min_score": 0})),
        msg("tool_use", tool_use("t3", "track_application", {"job_id": j.id, "status": "preparing"}),
            tool_use("t4", "request_approval_to_send", {"message_id": m.id, "reason": "good fit"}),
            tool_use("t5", "get_job_details", {"job_id": 99999})),
        msg("end_turn", text("## Done\nTracked the job and queued a message for your approval.")),
    ])
    seen_transcripts = []

    def fake_turn(*, system, messages, tools, **_):
        seen_transcripts.append(list(messages))
        return next(script)

    monkeypatch.setattr(llm, "agent_turn", fake_turn)
    from app.services import jobs as job_svc
    job_svc.compute_match(db, p, j)
    db.commit()

    run = AgentRun(user_id=p.user_id, goal="Find me a job and reach out", status="queued")
    db.add(run)
    db.commit()
    runner_mod.AgentRunner(run.id).start()

    db.expire_all()
    run = db.get(AgentRun, run.id)
    assert run.status == "completed"
    assert "approval" in run.final_answer
    kinds = [s.kind for s in run.steps]
    assert kinds.count("tool_call") == 5 and kinds.count("tool_result") == 5 and kinds[-1] == "final"
    bad = [s for s in run.steps if s.kind == "tool_result" and s.tool_name == "get_job_details"][0]
    assert bad.content["is_error"] is True  # errors are observed by the model, not fatal

    # Tool results for one turn are returned together in a single user message.
    last_user = seen_transcripts[2][-1]
    assert last_user["role"] == "user" and len(last_user["content"]) == 3

    req = db.query(ActionRequest).filter_by(agent_run_id=run.id).one()
    assert req.status == "pending"
    db.refresh(m)
    assert m.status == "pending_approval"


def test_agent_run_fails_cleanly_without_credentials(db, monkeypatch):
    p = make_profile(db)

    def boom(**_):
        raise llm.LLMUnavailable("no key")

    monkeypatch.setattr(llm, "agent_turn", boom)
    run = AgentRun(user_id=p.user_id, goal="hi", status="queued")
    db.add(run)
    db.commit()
    runner_mod.AgentRunner(run.id).start()
    db.expire_all()
    run = db.get(AgentRun, run.id)
    assert run.status == "failed" and "no key" in run.error


def test_tool_argument_validation():
    t = TOOL_MAP["track_application"]
    with pytest.raises(ToolError):
        t.normalize({})
    with pytest.raises(ToolError):
        t.normalize({"job_id": 1, "status": "hired!!"})
    assert t.normalize({"job_id": "3"})["job_id"] == 3
