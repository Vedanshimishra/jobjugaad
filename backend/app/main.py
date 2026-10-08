import base64
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update

from app.api import agent, jobs, outreach, profile, tracking
from app.api.deps import ensure_default_user
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.models import AgentRun

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        ensure_default_user(db)
        # Runs interrupted by a server restart can't resume their thread; mark them.
        db.execute(update(AgentRun).where(AgentRun.status.in_(["queued", "running", "stopping"]))
                   .values(status="failed", error="Interrupted by server restart"))
        db.commit()
    yield


app = FastAPI(title="JobJugaad API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def password_gate(request: Request, call_next):
    """When JOBJUGAAD_APP_PASSWORD is set (always, in deployment), require HTTP Basic auth
    for everything except the health check, so a public URL can't spend your API key."""
    password = settings.app_password
    if not password or request.url.path == "/api/health":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            _, _, given = base64.b64decode(header[6:]).decode().partition(":")
        except ValueError:
            given = ""
        if secrets.compare_digest(given.encode(), password.encode()):
            return await call_next(request)
    return Response("Authentication required", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="JobJugaad"'})


for r in (profile.router, jobs.router, outreach.router, tracking.router, agent.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    has_creds = any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"))
    return {"status": "ok", "model": settings.llm_model, "llm_credentials_detected": has_creds}


# Serve the built React app from the same origin when present (single-service deploy).
_dist = Path(settings.frontend_dist)
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return Response(status_code=404)
        file = (_dist / path).resolve()
        if path and file.is_file() and _dist.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(_dist / "index.html")
