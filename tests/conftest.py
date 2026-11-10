import pytest

from ev_platform import config, db


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'test.db'}")
    monkeypatch.setenv("INGEST_SOURCES", "india_curated,oem_pages,open_ev_data")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config.get_settings.cache_clear()
    db.reset_engine()
    from ev_platform.cli import migrate

    migrate()
    s = db.session_scope()
    yield s
    s.close()
    db.reset_engine()
    config.get_settings.cache_clear()
