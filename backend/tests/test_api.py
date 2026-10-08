def test_end_to_end_without_llm(client, tmp_path):
    assert client.get("/api/health").json()["status"] == "ok"

    prof = client.put("/api/profile", json={
        "preferred_roles": ["Backend Engineer"], "preferred_levels": ["new_grad", "entry"],
        "skills": ["python", "Postgres", "docker"], "graduation_year": 2026,
        "work_authorization": {"authorized_countries": ["us"], "needs_sponsorship": False},
    }).json()
    assert prof["skills"] == ["python", "postgresql", "docker"]
    assert prof["work_authorization"]["authorized_countries"] == ["US"]

    # Resume upload falls back to heuristic parsing when the LLM is unavailable.
    import app.services.resume_parser as rp
    from app import llm

    def no_llm(*a, **k):
        raise llm.LLMUnavailable("test")

    orig = rp.parse_with_llm
    rp.parse_with_llm = no_llm
    try:
        r = client.post("/api/resumes", files={"file": ("cv.txt", b"Jane Doe\njane@x.dev\nEducation\nState U 2026\n"
                                                         b"Skills: Python, FastAPI, Kubernetes", "text/plain")})
    finally:
        rp.parse_with_llm = orig
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resume"]["parse_method"] == "heuristic" and body["warning"]
    assert body["profile"]["email"] == "jane@x.dev" and "kubernetes" in body["profile"]["skills"]

    job = client.post("/api/jobs/manual", json={
        "company": "Acme", "title": "Backend Engineer, New Grad", "location": "Remote - US",
        "description": "Build services in Python and PostgreSQL with Docker and Kubernetes. 0-2 years of experience.",
    }).json()
    jid = job["job"]["id"]
    assert job["eligibility"] == "eligible" and job["score"] > 60

    listed = client.get("/api/jobs", params={"min_score": 10}).json()
    assert listed[0]["job"]["id"] == jid

    app_ = client.put(f"/api/applications/{jid}", json={"status": "applied", "notes": "via referral"}).json()
    assert app_["status"] == "applied" and app_["applied_at"]
    assert [e["kind"] for e in app_["events"]][:2] == ["status_change", "status_change"]
    assert client.put(f"/api/applications/{jid}", json={"status": "bogus"}).status_code == 400

    mems = client.get("/api/memories").json()
    assert any("saved → applied" in m["content"] for m in mems)

    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["application"]["status"] == "applied"

    recs = client.get("/api/recommendations").json()
    assert all(r["job_id"] != jid for r in recs["apply_next"])  # applied jobs aren't recommended again

    assert client.get("/api/approvals").json() == []
    assert client.post("/api/approvals/999/decision", json={"approve": True}).status_code == 409
