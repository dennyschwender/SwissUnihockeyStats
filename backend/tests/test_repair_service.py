"""Tests for RepairService — conservative DB repairs and health reports."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import text
from app.services.repair_service import RepairService
from app.services.database import DatabaseService
from app.models.db_models import Base, Game, GameEvent, SyncStatus


@pytest.fixture
def db():
    """Fresh in-memory DB for each test."""
    svc = DatabaseService("sqlite:///:memory:")
    svc.initialize()
    # Insert minimal FK prerequisite rows used by all game-insert tests
    with svc.session_scope() as session:
        session.execute(text("INSERT INTO seasons (id) VALUES (2025)"))
        session.execute(text("INSERT INTO clubs (id, season_id) VALUES (1, 2025)"))
        session.execute(text("INSERT INTO teams (id, season_id, club_id) VALUES (1, 2025, 1)"))
        session.execute(text("INSERT INTO teams (id, season_id, club_id) VALUES (2, 2025, 1)"))
    return svc


@pytest.fixture
def repair(db):
    return RepairService(db)


def test_run_nightly_returns_dict(repair):
    result = repair.run_nightly()
    assert isinstance(result, dict)
    assert "total_fixed" in result
    assert "stuck_in_progress" in result
    assert "null_game_dates" in result
    assert "missing_events" in result
    assert "null_period_fixed" in result
    assert "stale_failed" in result


def test_run_nightly_on_empty_db_returns_zeros(repair):
    result = repair.run_nightly()
    assert result["total_fixed"] == 0


def test_fix_stuck_in_progress_resets_old_rows(db, repair):
    """in_progress rows older than 2h should be deleted."""
    with db.session_scope() as session:
        old = SyncStatus(
            entity_type="game_events",
            entity_id="game:999:events",
            sync_status="in_progress",
            last_sync=datetime.utcnow() - timedelta(hours=3),
        )
        recent = SyncStatus(
            entity_type="game_events",
            entity_id="game:998:events",
            sync_status="in_progress",
            last_sync=datetime.utcnow() - timedelta(minutes=10),
        )
        session.add_all([old, recent])

    n = repair.fix_stuck_in_progress()
    assert n == 1  # only the old one

    with db.session_scope() as session:
        remaining = session.query(SyncStatus).filter_by(sync_status="in_progress").count()
        assert remaining == 1  # recent one untouched


def test_fix_null_game_dates_deletes_sync_rows(db, repair):
    """Finished games with null game_date should have their sync_status deleted."""
    with db.session_scope() as session:
        # Insert a minimal game with null date and a finished sync row
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score, home_team_id, away_team_id)
            VALUES (1001, 2025, 'finished', 3, 2, 1, 2)
        """))
        session.execute(
            text("""
            INSERT INTO sync_status (entity_type, entity_id, sync_status, last_sync)
            VALUES ('game_events', 'game:1001:events', 'completed', :now)
        """),
            {"now": datetime.utcnow()},
        )

    n = repair.fix_null_game_dates()
    assert n == 1

    with db.session_scope() as session:
        row = session.query(SyncStatus).filter_by(entity_id="game:1001:events").first()
        assert row is None  # deleted so scheduler re-queues


def test_fix_missing_events_deletes_sync_rows(db, repair):
    """Finished scored games with 0 events should have sync_status deleted."""
    with db.session_scope() as session:
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score, game_date, home_team_id, away_team_id)
            VALUES (1002, 2025, 'finished', 2, 1, '2025-10-01', 1, 2)
        """))
        # sync_status exists (completed) but no game_events rows
        session.execute(
            text("""
            INSERT INTO sync_status (entity_type, entity_id, sync_status, last_sync)
            VALUES ('game_events', 'game:1002:events', 'completed', :now)
        """),
            {"now": datetime.utcnow()},
        )

    n = repair.fix_missing_events()
    assert n == 1


def test_fix_null_period_from_events_sets_ot(db, repair):
    """Games with a goal event at time >= 61:00 should get period='OT'."""
    with db.session_scope() as session:
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score, game_date, period, home_team_id, away_team_id)
            VALUES (1003, 2025, 'finished', 3, 2, '2025-11-01', NULL, 1, 2)
        """))
        session.execute(text("""
            INSERT INTO game_events (id, game_id, event_type, time)
            VALUES (1, 1003, 'Torschütze', '62:15')
        """))

    n = repair.fix_null_period_from_events()
    assert n >= 1

    with db.session_scope() as session:
        row = session.execute(text("SELECT period FROM games WHERE id=1003")).fetchone()
        assert row[0] == "OT"


def test_fix_null_period_from_events_sets_so(db, repair):
    """Games with a Penaltyschiessen event should get period='SO'."""
    with db.session_scope() as session:
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score, game_date, period, home_team_id, away_team_id)
            VALUES (1004, 2025, 'finished', 3, 2, '2025-11-01', NULL, 1, 2)
        """))
        session.execute(text("""
            INSERT INTO game_events (id, game_id, event_type, time)
            VALUES (2, 1004, 'Penaltyschiessen', '65:00')
        """))

    n = repair.fix_null_period_from_events()
    assert n >= 1

    with db.session_scope() as session:
        row = session.execute(text("SELECT period FROM games WHERE id=1004")).fetchone()
        assert row[0] == "SO"


def test_fix_stale_failed_rows_deletes_old_failures(db, repair):
    """Failed sync_status rows older than 7 days should be deleted."""
    with db.session_scope() as session:
        old_fail = SyncStatus(
            entity_type="game_events",
            entity_id="game:888:events",
            sync_status="failed",
            last_sync=datetime.utcnow() - timedelta(days=8),
        )
        recent_fail = SyncStatus(
            entity_type="game_events",
            entity_id="game:887:events",
            sync_status="failed",
            last_sync=datetime.utcnow() - timedelta(days=2),
        )
        session.add_all([old_fail, recent_fail])

    n = repair.fix_stale_failed_rows()
    assert n == 1  # only the old one

    with db.session_scope() as session:
        remaining = session.query(SyncStatus).filter_by(sync_status="failed").count()
        assert remaining == 1


def test_fix_abandoned_games_resets_to_post_game(db, repair):
    """Abandoned games should be reset to post_game with a fresh give_up_at."""
    with db.session_scope() as session:
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score, game_date,
                               completeness_status, give_up_at, incomplete_fields,
                               home_team_id, away_team_id)
            VALUES (2001, 2025, 'finished', 3, 2, '2025-11-01',
                    'abandoned', '2025-11-10', '["spectators"]', 1, 2)
        """))
        # A non-abandoned game — should not be touched
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score, game_date,
                               completeness_status, home_team_id, away_team_id)
            VALUES (2002, 2025, 'finished', 1, 0, '2025-11-02',
                    'post_game', 1, 2)
        """))

    n = repair.fix_abandoned_games()
    assert n == 1  # only the abandoned one

    with db.session_scope() as session:
        row = session.execute(
            text("SELECT completeness_status, give_up_at, incomplete_fields FROM games WHERE id=2001")
        ).fetchone()
        assert row[0] == "post_game"
        assert row[1] is not None   # give_up_at set to a future date
        assert row[2] is None       # incomplete_fields cleared

        # post_game game untouched
        row2 = session.execute(
            text("SELECT completeness_status FROM games WHERE id=2002")
        ).fetchone()
        assert row2[0] == "post_game"


def test_fix_abandoned_games_empty_db_returns_zero(repair):
    assert repair.fix_abandoned_games() == 0


def test_fix_null_phases_deletes_sync_status(db, repair):
    """sync_status rows for groups with null phase should be deleted."""
    with db.session_scope() as session:
        # Insert a leagues row (internal id=1, API league_id=99)
        session.execute(text("""
            INSERT INTO leagues (id, season_id, league_id, game_class, name, text)
            VALUES (1, 2025, 99, 1, 'TestLeague', 'TestLeague')
        """))
        # League group with null phase (league_id=1 is the internal leagues.id)
        session.execute(text("""
            INSERT INTO league_groups (id, league_id, group_id, name)
            VALUES (10, 1, 10, 'GroupA')
        """))
        # Matching sync_status row (entity_id uses internal leagues.id = 1)
        session.execute(
            text("""
            INSERT INTO sync_status (entity_type, entity_id, sync_status, last_sync)
            VALUES ('groups', 'league:1', 'completed', :now)
        """),
            {"now": datetime.utcnow()},
        )
        # A group with a valid phase — its sync_status must NOT be deleted
        session.execute(text("""
            INSERT INTO league_groups (id, league_id, group_id, name, phase)
            VALUES (11, 1, 11, 'GroupB', 'Playoff')
        """))
        session.execute(
            text("""
            INSERT INTO sync_status (entity_type, entity_id, sync_status, last_sync)
            VALUES ('groups', 'league:1:playoff', 'completed', :now)
        """),
            {"now": datetime.utcnow()},
        )

    n = repair.fix_null_phases()
    assert n == 1  # only the null-phase one deleted

    with db.session_scope() as session:
        deleted = session.execute(
            text("SELECT COUNT(*) FROM sync_status WHERE entity_type='groups' AND entity_id='league:1'")
        ).scalar()
        assert deleted == 0

        kept = session.execute(
            text("SELECT COUNT(*) FROM sync_status WHERE entity_type='groups' AND entity_id='league:1:playoff'")
        ).scalar()
        assert kept == 1


def test_fix_null_phases_empty_db_returns_zero(repair):
    assert repair.fix_null_phases() == 0


def test_report_methods_return_lists(repair):
    assert isinstance(repair.report_games_no_lineup(), list)
    assert isinstance(repair.report_roster_gaps(), list)
    assert isinstance(repair.report_unresolved_stats(), list)


def test_run_nightly_writes_sync_status(db, repair):
    """run_nightly() should write a completed sync_status row."""
    repair.run_nightly()
    with db.session_scope() as session:
        row = session.query(SyncStatus).filter_by(entity_type="repair", entity_id="all").first()
        assert row is not None
        assert row.sync_status == "completed"
