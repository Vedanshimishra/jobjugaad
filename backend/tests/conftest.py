import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="jobjugaad-test-"))
os.environ["JOBJUGAAD_DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["JOBJUGAAD_UPLOAD_DIR"] = str(_tmp / "uploads")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import CandidateProfile, Job, User  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def make_profile(db, **overrides) -> CandidateProfile:
    user = User(email=f"u{os.urandom(3).hex()}@test")
    db.add(user)
    db.flush()
    defaults = dict(
        user_id=user.id, full_name="Test Candidate", graduation_year=2026, experience_months=6,
        skills=["Python", "PyTorch", "SQL", "Docker", "React", "FastAPI"],
        experience=[{"company": "Acme", "title": "SWE Intern", "start": "2025-05", "end": "2025-08",
                     "is_internship": True, "bullets": ["Built REST APIs in FastAPI serving 10k users"],
                     "skills": ["Python", "FastAPI"]}],
        projects=[{"name": "RAG bot", "description": "LLM chatbot with embeddings", "bullets": [], "skills": ["PyTorch"]}],
        education=[{"school": "State U", "degree": "B.S.", "field": "Computer Science", "end": "2026-05"}],
        preferred_roles=["Machine Learning Engineer", "Software Engineer"],
        preferred_levels=["new_grad", "entry"], preferred_locations=["San Francisco", "Remote"],
        work_modes=["remote", "hybrid", "onsite"], work_authorization={"authorized_countries": ["US"], "needs_sponsorship": False},
    )
    defaults.update(overrides)
    p = CandidateProfile(**defaults)
    db.add(p)
    db.commit()
    return p


def make_job(db, **overrides) -> Job:
    defaults = dict(source="manual", external_id=os.urandom(4).hex(), company="Example AI",
                    title="Software Engineer, New Grad", location="San Francisco, CA", work_mode="hybrid",
                    level="new_grad", description="We use Python, PyTorch and Kubernetes. 0-1 years of experience.")
    defaults.update(overrides)
    j = Job(**defaults)
    db.add(j)
    db.commit()
    return j


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
