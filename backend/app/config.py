import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_prefix="JOBJUGAAD_", extra="ignore")

    app_name: str = "JobJugaad"
    database_url: str = f"sqlite:///{(BASE_DIR / 'jobjugaad.db').as_posix()}"
    upload_dir: Path = BASE_DIR / "uploads"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Built frontend served by the backend in single-service deployments.
    frontend_dist: Path = BASE_DIR.parent / "frontend" / "dist"
    # If set, every request (except /api/health) requires HTTP Basic auth with this password.
    app_password: str | None = None

    # LLM. The Anthropic key itself is read by the SDK from ANTHROPIC_API_KEY
    # (or an `ant auth login` profile), never from this file.
    llm_model: str = "claude-opus-5-5"
    llm_effort_agent: str = "high"
    llm_effort_tasks: str = "medium"
    llm_server_fallbacks: bool = True
    llm_enable_web_search: bool = True

    # Agent guardrails
    agent_max_steps: int = 25
    agent_max_jobs_per_search: int = 60

    # Job discovery: comma-separated board tokens for public ATS APIs.
    greenhouse_boards: str = "anthropic,stripe,databricks,figma,discord,robinhood"
    lever_companies: str = "palantir"
    ashby_boards: str = "openai,ramp,notion,linear"
    http_timeout_s: float = 20.0

    # Optional outbound email (used only after explicit human approval).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None


def _export_anthropic_env() -> None:
    """Let ANTHROPIC_* values in backend/.env reach the SDK, which reads os.environ.
    Real environment variables always win."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.startswith("ANTHROPIC_") and value.strip():
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


@lru_cache
def get_settings() -> Settings:
    _export_anthropic_env()
    return Settings()
