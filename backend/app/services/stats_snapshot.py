"""Write periodic admin stats snapshots to admin_stats_snapshots table."""
import os
import logging
from datetime import datetime, timezone
from sqlalchemy import text

logger = logging.getLogger(__name__)


def write_stats_snapshot(
    db_service,
    jobs_run: int,
    jobs_errors: int,
    avg_job_duration_s: float,
) -> None:
    """Insert one row into admin_stats_snapshots.

    Called by the scheduler background loop every 6 hours.
    Uses INSERT OR REPLACE so duplicate timestamps don't raise.
    """
    from app.models.db_models import Game, Player, GameEvent, PlayerStatistics
    from sqlalchemy import func

    # Collect entity counts
    try:
        with db_service.session_scope() as session:
            games        = session.query(func.count(Game.id)).scalar() or 0
            players      = session.query(func.count(Player.person_id)).scalar() or 0
            events       = session.query(func.count(GameEvent.id)).scalar() or 0
            player_stats = session.query(func.count(PlayerStatistics.id)).scalar() or 0
    except Exception as exc:
        logger.warning("stats_snapshot: failed to count entities: %s", exc)
        games = players = events = player_stats = 0

    # DB file size
    try:
        from app.config import get_settings
        db_path = get_settings().DATABASE_PATH
        db_size = os.path.getsize(db_path) if db_path and db_path != ":memory:" else 0
    except Exception:
        db_size = 0

    ts = datetime.now(timezone.utc).replace(microsecond=0)

    try:
        with db_service.engine.connect() as conn:
            conn.execute(text("""
                INSERT OR REPLACE INTO admin_stats_snapshots
                (ts, db_size_bytes, games, players, events, player_stats,
                 jobs_run, jobs_errors, avg_job_duration_s)
                VALUES (:ts, :db_size, :games, :players, :events, :player_stats,
                        :jobs_run, :jobs_errors, :avg_dur)
            """), {
                "ts": ts, "db_size": db_size, "games": games,
                "players": players, "events": events,
                "player_stats": player_stats, "jobs_run": jobs_run,
                "jobs_errors": jobs_errors, "avg_dur": avg_job_duration_s,
            })
            conn.commit()
    except Exception as exc:
        logger.error("stats_snapshot: failed to write snapshot: %s", exc)
