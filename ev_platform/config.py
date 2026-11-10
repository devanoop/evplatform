"""Runtime configuration, read from environment variables (Railway sets these per service)."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Railway's Postgres plugin exposes DATABASE_URL. Locally we fall back to SQLite.
    database_url: str = "sqlite:///./ev_platform.db"

    # Comma-separated list of sources the ingest job runs, in merge-priority order
    # (later sources only fill fields that earlier ones left empty).
    ingest_sources: str = "india_curated,oem_pages,open_ev_data,wikidata"

    # Polite crawling settings for any source that fetches web pages.
    http_user_agent: str = "EVPlatformSpecsBot/0.1 (+https://example.com/bot)"
    http_timeout_seconds: float = 30.0
    crawl_delay_seconds: float = 5.0  # minimum gap between requests to the same host

    # Open data endpoints
    open_ev_data_url: str = (
        "https://raw.githubusercontent.com/KilowattApp/open-ev-data/master/data/ev-data.json"
    )
    wikidata_sparql_url: str = "https://query.wikidata.org/sparql"

    # OEM page extraction uses Claude to turn a spec page into structured data.
    # Leave ANTHROPIC_API_KEY unset to skip that source.
    anthropic_api_key: str | None = None
    extraction_model: str = "claude-opus-5-5"

    # Protects POST /admin/* endpoints. Unset disables them.
    admin_token: str | None = None

    # Run the ingest loop inside the web process (handy for a single-service deploy).
    # On Railway prefer a separate cron service, see railway.ingest.json.
    enable_inprocess_scheduler: bool = False
    inprocess_ingest_interval_hours: float = 24.0

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        # Railway/Heroku style URLs use postgres:// which SQLAlchemy 2 rejects.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    @property
    def source_list(self) -> list[str]:
        return [s.strip() for s in self.ingest_sources.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
