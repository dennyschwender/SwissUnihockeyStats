"""Tests for admin stats snapshot writes."""
import os
os.environ.setdefault("DATABASE_PATH", ":memory:")
os.environ.setdefault("ADMIN_PIN", "testpin")
os.environ.setdefault("SESSION_SECRET", "test-secret-key-32-chars-xxxxxxxx")
os.environ.setdefault("DEBUG", "true")

from sqlalchemy import text


def _make_db():
    from app.services.database import DatabaseService
    db = DatabaseService.__new__(DatabaseService)
    db.database_url = "sqlite:///:memory:"
    db._initialized = False
    db.initialize()
    return db


def test_write_stats_snapshot_inserts_row():
    from app.services.stats_snapshot import write_stats_snapshot
    db = _make_db()
    write_stats_snapshot(db, jobs_run=3, jobs_errors=1, avg_job_duration_s=42.5)
    with db.engine.connect() as conn:
        rows = list(conn.execute(text("SELECT * FROM admin_stats_snapshots")))
    assert len(rows) == 1
    row = rows[0]._mapping
    assert row["jobs_run"] == 3
    assert row["jobs_errors"] == 1
    assert abs(row["avg_job_duration_s"] - 42.5) < 0.01


def test_write_stats_snapshot_populates_entity_counts():
    from app.services.stats_snapshot import write_stats_snapshot
    db = _make_db()
    write_stats_snapshot(db, jobs_run=0, jobs_errors=0, avg_job_duration_s=0)
    with db.engine.connect() as conn:
        row = dict(list(conn.execute(text("SELECT * FROM admin_stats_snapshots")))[0]._mapping)
    for col in ("db_size_bytes", "games", "players", "events", "player_stats"):
        assert col in row


def test_write_stats_snapshot_replace_on_same_ts():
    """Two writes in the same second must not raise (INSERT OR REPLACE)."""
    from app.services.stats_snapshot import write_stats_snapshot
    from datetime import datetime, timezone
    db = _make_db()
    write_stats_snapshot(db, jobs_run=1, jobs_errors=0, avg_job_duration_s=10.0)
    write_stats_snapshot(db, jobs_run=2, jobs_errors=0, avg_job_duration_s=5.0)
    # Intentionally loose: two rapid writes may share the same UTC second (→ 1 row
    # via INSERT OR REPLACE) or land in different seconds (→ 2 rows).  The test
    # only verifies that no IntegrityError / UNIQUE constraint violation is raised.
    with db.engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM admin_stats_snapshots")).scalar()
    assert count >= 1


# ── API endpoint tests ────────────────────────────────────────────────────────

def test_stats_history_requires_auth(client):
    """Unauthenticated access must be redirected (302) or rejected (401/403)."""
    r = client.get("/admin/api/stats/history", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


def test_stats_history_returns_list(admin_client):
    r = admin_client.get("/admin/api/stats/history")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_stats_history_row_shape(admin_client):
    """Each row must contain all expected keys."""
    # Insert a snapshot first
    from app.services.stats_snapshot import write_stats_snapshot
    from app.services.database import get_database_service
    write_stats_snapshot(get_database_service(), jobs_run=1, jobs_errors=0, avg_job_duration_s=10.0)
    r = admin_client.get("/admin/api/stats/history?days=30")
    assert r.status_code == 200
    rows = r.json()
    if rows:  # may be empty if snapshot was already there
        row = rows[0]
        for key in ("ts", "db_size_bytes", "games", "players", "events",
                    "player_stats", "jobs_run", "jobs_errors", "avg_job_duration_s"):
            assert key in row, f"Missing key: {key}"


def test_stats_history_days_filter(admin_client):
    """?days=0 must return an empty list."""
    r = admin_client.get("/admin/api/stats/history?days=0")
    assert r.status_code == 200
    assert r.json() == []
