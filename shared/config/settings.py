"""
Central configuration — the single control panel for the whole system.

Everything tunable lives here and is overridable via environment variables /
a .env file. Nothing operational (model name, concurrency, ports, engine
choice, toggles, secrets) is hardcoded in business logic.

Settings are grouped by concern into nested blocks so the control panel reads
cleanly:

    settings.llm.model            settings.db.engine
    settings.llm.max_concurrency  settings.db.max_query_rows
    settings.agent.max_steps      settings.auth.jwt_secret
    settings.supervisor.*         settings.router.*
    settings.ports.*

Env var naming: each block reads FLAT, conventional names directly from the
environment / .env (OLLAMA_API_KEY, LLM_MODEL, DB_ENGINE, JWT_SECRET, ...).
Each nested block is its own BaseSettings that loads .env independently, which
is what makes the flat names work while keeping the grouped access structure.

Why pydantic-settings: typed, validated config with automatic env binding and
a clear failure mode (the app refuses to start if a required value is missing
or malformed) rather than blowing up deep inside a request.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = three levels up (shared/config/settings.py -> config -> shared -> root).
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data"

# Shared config for every block: read the same .env, ignore unrelated keys, and
# match env var names case-insensitively.
_ENV = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    case_sensitive=False,
)


# ===========================================================================
# Grouped setting blocks — each independently reads flat env vars from .env
# ===========================================================================
class LLMSettings(BaseSettings):
    """Ollama Cloud LLM configuration."""
    model_config = _ENV

    # REQUIRED, no default — the app refuses to start without it, so a key is
    # never accidentally hardcoded/committed.
    api_key: str = Field(..., validation_alias="OLLAMA_API_KEY")
    host: str = Field("https://ollama.com", validation_alias="OLLAMA_HOST")
    model: str = Field("gemma4:31b-cloud", validation_alias="LLM_MODEL")

    # Ollama Cloud concurrency cap. Free = 1, Pro = 3, Max = 10 concurrent cloud
    # models. A Semaphore(max_concurrency) serializes cloud calls app-wide.
    # Raising this unlocks parallel sub-agent calls (Backend 2) with NO code
    # change — the semaphore is the throttle, the code path is identical.
    max_concurrency: int = Field(1, validation_alias="LLM_MAX_CONCURRENCY", ge=1)
    timeout_seconds: float = Field(120.0, validation_alias="LLM_TIMEOUT_SECONDS", gt=0)


class AgentSettings(BaseSettings):
    """ReAct agent (Backend 1) loop guardrails."""
    model_config = _ENV
    # Max Thought->Action->Observation iterations per turn; stops a model that
    # never decides to quit calling tools.
    max_steps: int = Field(6, validation_alias="AGENT_MAX_STEPS", ge=1, le=20)


class DBSettings(BaseSettings):
    """Data layer configuration."""
    model_config = _ENV
    # 'sqlite' (default) drives Backends 1 & 2's transactional lookups.
    # 'duckdb' drives Backend 3 to demonstrate the analytical scaling path.
    engine: str = Field("sqlite", validation_alias="DB_ENGINE")
    assets_db_path: Path = Field(DATA_DIR / "assets.db", validation_alias="DB_PATH")
    assets_csv: Path = Field(DATA_DIR / "assets_seed.csv", validation_alias="ASSETS_CSV")
    # Separate read-write DB for user accounts, kept apart from the read-only
    # assets DB so the "assets are physically immutable" (mode=ro) guarantee holds.
    users_db_path: Path = Field(DATA_DIR / "users.db", validation_alias="USERS_DB_PATH")
    # Hard cap on rows any list/search/recommend path may return.
    max_query_rows: int = Field(50, validation_alias="MAX_QUERY_ROWS", ge=1)

    @property
    def sqlite_uri_readonly(self) -> str:
        return f"file:{self.assets_db_path}?mode=ro"


class AuthSettings(BaseSettings):
    """Shared JWT auth for all backends + the Streamlit login."""
    model_config = _ENV
    jwt_secret: str = Field("change-me-in-production-please", validation_alias="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", validation_alias="JWT_ALGORITHM")
    jwt_expiry_minutes: int = Field(120, validation_alias="JWT_EXPIRY_MINUTES", ge=1)


class SupervisorSettings(BaseSettings):
    """Backend 2 (LangGraph multi-agent) tuning."""
    model_config = _ENV
    # When True AND llm.max_concurrency > 1, independent workers dispatch
    # concurrently (asyncio.gather). Otherwise sequential through the semaphore.
    parallel_workers: bool = Field(True, validation_alias="SUPERVISOR_PARALLEL_WORKERS")
    max_routing_steps: int = Field(4, validation_alias="SUPERVISOR_MAX_ROUTING_STEPS", ge=1, le=10)


class RouterSettings(BaseSettings):
    """Backend 3 (intent-extraction router) tuning."""
    model_config = _ENV
    max_chained_intents: int = Field(3, validation_alias="ROUTER_MAX_CHAINED_INTENTS", ge=1, le=6)


class PortSettings(BaseSettings):
    """Local dev ports for the three backends (Streamlit talks to these)."""
    model_config = _ENV
    react: int = Field(8001, validation_alias="PORT_REACT")
    supervisor: int = Field(8002, validation_alias="PORT_SUPERVISOR")
    router: int = Field(8003, validation_alias="PORT_ROUTER")


# ===========================================================================
# Root settings object — assembles the blocks. Each block loads its own env.
# ===========================================================================
class Settings(BaseSettings):
    model_config = _ENV

    llm: LLMSettings = Field(default_factory=LLMSettings)          # type: ignore[arg-type]
    agent: AgentSettings = Field(default_factory=AgentSettings)
    db: DBSettings = Field(default_factory=DBSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    supervisor: SupervisorSettings = Field(default_factory=SupervisorSettings)
    router: RouterSettings = Field(default_factory=RouterSettings)
    ports: PortSettings = Field(default_factory=PortSettings)

    # Streamlit CORS origin(s) the backends allow.
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8501", "http://127.0.0.1:8501"],
    )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — env/.env parsed exactly once."""
    return Settings()  # type: ignore[call-arg]
