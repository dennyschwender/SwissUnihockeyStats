"""Verify admin_stats_snapshots table is created idempotently by migration."""

import os

os.environ.setdefault("DATABASE_PATH", ":memory:")
os.environ.setdefault("ADMIN_PIN", "testpin")
os.environ.setdefault("SESSION_SECRET", "test-secret-key-32-chars-xxxxxxxx")
os.environ.setdefault("DEBUG", "true")

from sqlalchemy import text


def test_admin_stats_snapshots_table_exists():
    """Table must be created by _run_sqlite_migrations."""
    from app.services.database import DatabaseService

    db = DatabaseService.__new__(DatabaseService)
    db.database_url = "sqlite:///:memory:"
    db._initialized = False
    db.initialize()

    with db.engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
    assert "admin_stats_snapshots" in tables


def test_migration_columns():
    """Table must have all required columns."""
    from app.services.database import DatabaseService

    db = DatabaseService.__new__(DatabaseService)
    db.database_url = "sqlite:///:memory:"
    db._initialized = False
    db.initialize()

    with db.engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(admin_stats_snapshots)"))}
    for expected in (
        "ts",
        "db_size_bytes",
        "games",
        "players",
        "events",
        "player_stats",
        "jobs_run",
        "jobs_errors",
        "avg_job_duration_s",
    ):
        assert expected in cols, f"Missing column: {expected}"


def test_migration_is_idempotent():
    """Running migration twice must not raise."""
    from app.services.database import DatabaseService

    db = DatabaseService.__new__(DatabaseService)
    db.database_url = "sqlite:///:memory:"
    db._initialized = False
    db.initialize()
    db._run_sqlite_migrations()  # second call — must not raise
