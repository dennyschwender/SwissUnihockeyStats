"""
Database service for managing connections and sessions
"""

import logging
from contextlib import contextmanager
from datetime import timedelta
from typing import Generator, Optional
from sqlalchemy import create_engine, event, select, text, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool, StaticPool

from app.models.db_models import Base, Game, GameSyncFailure, _utcnow
from app.config import settings

logger = logging.getLogger(__name__)


def run_lifecycle_migration(engine) -> None:
    """Idempotent migration: add lifecycle columns to games, create game_sync_failures,
    and backfill completeness_status for all existing games rows.

    Safe to call multiple times — all operations are gated on current state.
    """
    insp = sa_inspect(engine)
    existing_cols = {c["name"] for c in insp.get_columns("games")}

    with engine.connect() as conn:
        if "completeness_status" not in existing_cols:
            conn.execute(
                text(
                    "ALTER TABLE games ADD COLUMN completeness_status VARCHAR(20) NOT NULL DEFAULT 'upcoming'"
                )
            )
        if "incomplete_fields" not in existing_cols:
            conn.execute(text("ALTER TABLE games ADD COLUMN incomplete_fields TEXT"))
        if "give_up_at" not in existing_cols:
            conn.execute(text("ALTER TABLE games ADD COLUMN give_up_at DATETIME"))
        if "completeness_checked_at" not in existing_cols:
            conn.execute(text("ALTER TABLE games ADD COLUMN completeness_checked_at DATETIME"))
        conn.commit()

    # Create game_sync_failures table if missing
    GameSyncFailure.__table__.create(engine, checkfirst=True)

    # Backfill: only process finished games still marked 'upcoming' (the column default).
    # Non-finished (scheduled/live) games are correctly 'upcoming' already — skip them
    # to avoid loading thousands of ORM objects on every restart.
    now = _utcnow()
    # SQLite returns naive datetimes; use a naive UTC now for comparisons.
    now_naive = now.replace(tzinfo=None)
    with Session(engine) as session:
        games = (
            session.execute(
                select(Game).where(
                    Game.completeness_status == "upcoming",
                    Game.status == "finished",
                )
            )
            .scalars()
            .all()
        )

        for i, game in enumerate(games):
            is_complete = game.home_score is not None and game.away_score is not None
            if is_complete:
                game.completeness_status = "complete"
                game.give_up_at = None
                game.incomplete_fields = None
            else:
                missing = ["score"]
                deadline = (
                    (game.game_date + timedelta(days=3))
                    if game.game_date is not None
                    else (now_naive + timedelta(days=3))
                )
                if game.game_date is None or deadline > now_naive:
                    game.completeness_status = "post_game"
                    game.give_up_at = deadline
                    game.incomplete_fields = missing
                else:
                    game.completeness_status = "abandoned"
                    game.give_up_at = None
                    game.incomplete_fields = missing
                    # Write failure row only if one doesn't already exist
                    existing_failure = session.execute(
                        select(GameSyncFailure).where(GameSyncFailure.game_id == game.id)
                    ).scalar_one_or_none()
                    if existing_failure is None:
                        session.add(
                            GameSyncFailure(
                                game_id=game.id,
                                season_id=game.season_id,
                                abandoned_at=now,
                                missing_fields=missing,
                                can_retry=False,
                            )
                        )

            if (i + 1) % 200 == 0:
                session.commit()

        session.commit()
    logger.debug("Lifecycle migration applied")


class DatabaseService:
    """Manages database connections and sessions"""

    def __init__(self, database_url: str = None):
        """Initialize database service

        Args:
            database_url: Database URL (defaults to settings)
        """
        import threading

        self.database_url = database_url or self._get_database_url()
        self.engine = None
        self.SessionLocal = None
        self._initialized = False
        # StaticPool (used for :memory: SQLite in tests) shares one underlying
        # connection across all threads.  Concurrent sessions from background
        # asyncio tasks would race to issue BEGIN on the same connection and
        # hit "cannot start a transaction within a transaction".  Serialise
        # session_scope() with a reentrant lock when using the static pool so
        # that only one thread holds a session at a time.
        self._session_lock: threading.RLock | None = None

    def _get_database_url(self) -> str:
        """Get database URL from settings"""
        # Use SQLite by default for simplicity
        # Can be overridden in settings to use PostgreSQL
        db_path = getattr(settings, "DATABASE_PATH", "data/swissunihockey.db")
        return f"sqlite:///{db_path}"

    def initialize(self):
        """Initialize database engine and create tables"""
        if self._initialized:
            logger.debug("Database already initialized")
            return

        logger.info(f"Initializing database: {self.database_url}")

        # Create engine
        if self.database_url.startswith("sqlite"):
            # For :memory: databases (tests) use StaticPool so all connections
            # share the same in-memory database.  For file-based SQLite use
            # NullPool so concurrent asyncio.to_thread workers each get their
            # own connection; WAL + busy_timeout serialise writes at the
            # file level, which is safe.
            is_memory = ":memory:" in self.database_url
            self.engine = create_engine(
                self.database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool if is_memory else NullPool,
                echo=False,  # Set to True for SQL debugging
            )
            if is_memory:
                import threading

                self._session_lock = threading.RLock()

            # Enable foreign keys for SQLite
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute(
                    "PRAGMA busy_timeout=30000"
                )  # wait up to 30s for locks (must be first)
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")  # concurrent readers + writer
                cursor.close()

        else:
            # PostgreSQL or other database
            self.engine = create_engine(
                self.database_url, pool_size=10, max_overflow=20, echo=False
            )

        # Create session factory
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        # Create all tables
        Base.metadata.create_all(bind=self.engine)

        # ── Schema migrations ────────────────────────────────────────────
        if self.database_url.startswith("sqlite"):
            self._run_sqlite_migrations()

        # ── Game lifecycle migration (idempotent backfill) ───────────────
        run_lifecycle_migration(self.engine)

        self._initialized = True
        logger.info("Database initialized successfully")

    def _run_sqlite_migrations(self):
        """Idempotent SQLite schema migrations run on every startup.

        Rules for keeping this clean:
        - ADD COLUMN stanzas can be removed once all deployed DBs have been
          updated (i.e. after the next Pi docker pull + restart).
        - Backfill UPDATEs stay as long as rows without those values can exist
          (they are WHERE-gated so they are cheap no-ops once fully backfilled).
        - One-time repair statements (index rebuilds, duplicate deletes, etc.)
          must be removed after all instances have been updated.
        """
        from sqlalchemy import text

        with self.engine.connect() as conn:

            # ── Add new columns to player_statistics (idempotent) ───────────
            # Can be removed once all deployed DBs have been updated past the
            # commit that added each column.
            existing_cols = {
                row[1] for row in conn.execute(text("PRAGMA table_info(player_statistics)"))
            }
            for col, typedef in [
                ("pen_2min", "INTEGER DEFAULT 0"),
                ("pen_5min", "INTEGER DEFAULT 0"),
                ("pen_10min", "INTEGER DEFAULT 0"),
                ("pen_match", "INTEGER DEFAULT 0"),
                ("game_class", "INTEGER"),
                ("computed_from_local", "INTEGER NOT NULL DEFAULT 0"),
                ("local_computed_at", "DATETIME"),
            ]:
                if col not in existing_cols:
                    conn.execute(text(f"ALTER TABLE player_statistics ADD COLUMN {col} {typedef}"))

            # ── Backfill game_class (WHERE IS NULL — cheap once done) ───────
            # Derives gender/age class from the player's TeamPlayer → Team rows.
            # Runs incrementally: only touches rows not yet resolved.
            conn.execute(text("""
                UPDATE player_statistics
                SET game_class = (
                    SELECT t.game_class
                    FROM team_players tp
                    JOIN teams t ON t.id = tp.team_id AND t.season_id = tp.season_id
                    WHERE tp.player_id = player_statistics.player_id
                      AND tp.season_id = player_statistics.season_id
                      AND t.name = player_statistics.team_name
                    LIMIT 1
                )
                WHERE game_class IS NULL
            """))

            # ── Backfill team_id (WHERE IS NULL AND game_class IS NOT NULL) ─
            # Uses (name, season_id, game_class) to disambiguate same-named clubs
            # that field both male and female teams. Requires game_class first.
            conn.execute(text("""
                UPDATE player_statistics
                SET team_id = (
                    SELECT t.id
                    FROM teams t
                    WHERE t.name = player_statistics.team_name
                      AND t.season_id = player_statistics.season_id
                      AND t.game_class = player_statistics.game_class
                    LIMIT 1
                )
                WHERE team_id IS NULL AND game_class IS NOT NULL
            """))

            # ── Add phase column to league_groups ────────────────────────────
            lg_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(league_groups)"))}
            if "phase" not in lg_cols:
                conn.execute(text("ALTER TABLE league_groups ADD COLUMN phase TEXT"))

            # ── Add referee/spectator columns to games ───────────────────────
            game_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(games)"))}
            for col, typedef in [
                ("spectators", "INTEGER"),
                ("referee_1", "VARCHAR(100)"),
                ("referee_2", "VARCHAR(100)"),
            ]:
                if col not in game_cols:
                    conn.execute(text(f"ALTER TABLE games ADD COLUMN {col} {typedef}"))

            # ── Drop the now-unused player_id index on game_events ──────────
            # player_id is always NULL (API returns names, not IDs), so the
            # index only stored NULLs.
            conn.execute(text("DROP INDEX IF EXISTS idx_event_player"))

            # ── Fix Team.league_id values stored as DB PKs instead of API league_ids ──
            # Some code paths wrote the leagues.id (auto-increment PK) into Team.league_id
            # instead of leagues.league_id (the API league_id used by LEAGUE_TIERS).  This
            # caused league_tier() to return wrong tiers (e.g. DB PK 14 → tier 3/B-youth
            # when the real API league_id 6 → tier 6/4.Liga), leading to youth teams being
            # included in the players job which only works for NLA/NLB.  Fix by re-deriving
            # the API league_id from the game → league_group → league join wherever the
            # stored value is not a valid API league_id.
            conn.execute(text("""
                UPDATE teams
                SET league_id = (
                    SELECT l.league_id
                    FROM games g
                    JOIN league_groups lg ON g.group_id = lg.id
                    JOIN leagues l        ON lg.league_id = l.id
                    WHERE (g.home_team_id = teams.id OR g.away_team_id = teams.id)
                      AND g.season_id = teams.season_id
                    LIMIT 1
                )
                WHERE teams.league_id IS NOT NULL
                AND   teams.league_id NOT IN (SELECT DISTINCT league_id FROM leagues)
                AND   EXISTS (
                    SELECT 1 FROM games g
                    JOIN league_groups lg ON g.group_id = lg.id
                    WHERE (g.home_team_id = teams.id OR g.away_team_id = teams.id)
                      AND g.season_id = teams.season_id
                )
            """))

            # ── Backfill game.period = 'OT' from indexed events ──────────────
            # index_game_events now detects overtime from goal events at time≥61:00
            # and sets game.period = 'OT'.  This backfill updates the ~950 already-
            # indexed games where game_events contain an OT goal but period is NULL.
            conn.execute(text("""
                UPDATE games
                SET period = 'OT'
                WHERE period IS NULL
                  AND status = 'finished'
                  AND id IN (
                      SELECT DISTINCT game_id FROM game_events
                      WHERE time >= '61:00'
                        AND event_type LIKE 'Torschütze%'
                  )
            """))
            # ── Reset sync_status for recently-finished games with NULL period ─
            # index_game_events can now detect OT from the game_summary title
            # suffix "n.V." / "n.P." (added 2026-03-02).  Any games indexed
            # *before* that change have period=NULL even when they were played
            # in overtime, because the old code only used event timestamps ≥61:00
            # which sometimes weren't present (absent goal events, corrupted rows).
            # Deleting their sync_status rows forces the scheduler to re-index
            # them with the new code so the period is set correctly.
            # NOTE: ':events' in SQL text would be parsed by SQLAlchemy as a
            # bind parameter placeholder.  Pass it as an explicit bind value
            # instead, using :suffix, so the literal colon is handled safely.
            # The last_sync guard makes this a true one-shot migration: rows
            # written by the *new* scheduler (after 2026-03-02) won't be
            # deleted again on subsequent container restarts.
            # Scoped to season_id=2025 (current season) to avoid re-queuing
            # ~30k historical games from prior seasons — the initial version
            # used game_date >= '-40 days' which missed earlier rounds of the
            # current season (Sep–Jan games were 44–156 days old, just outside).
            conn.execute(
                text("""
                DELETE FROM sync_status
                WHERE entity_type = 'game_events'
                  AND last_sync < '2026-03-02 00:00:00'
                  AND entity_id IN (
                      SELECT 'game:' || g.id || :suffix
                      FROM games g
                      WHERE g.status = 'finished'
                        AND g.period IS NULL
                        AND g.home_score IS NOT NULL
                        AND g.season_id = 2025
                  )
            """),
                {"suffix": ":events"},
            )
            # ── Remove phantom future-season rows ────────────────────────────
            # index_seasons now skips seasons that haven't started yet, but any
            # already-created phantom rows (e.g. 2026/27 created in Feb 2026)
            # should be cleaned up so they don't appear in admin stats.
            # Safe because seasons > current_year+1 have no child rows.
            conn.execute(text("""
                DELETE FROM seasons
                WHERE id > (CASE WHEN strftime('%m','now') >= '09'
                                 THEN CAST(strftime('%Y','now') AS INTEGER)
                                 ELSE CAST(strftime('%Y','now') AS INTEGER) - 1
                            END)
            """))

            # ── Add api_failures / api_skip_until to players ─────────────────
            player_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(players)"))}
            for col, typedef in [
                ("api_failures", "INTEGER NOT NULL DEFAULT 0"),
                ("api_skip_until", "DATETIME"),
            ]:
                if col not in player_cols:
                    conn.execute(text(f"ALTER TABLE players ADD COLUMN {col} {typedef}"))

            # ── Covering index for game_events duplicate cleanup ─────────────
            # The admin cleanup DELETE uses NOT IN (SELECT MIN(id) … GROUP BY
            # game_id, event_type, period, time, player_id).  Without a
            # covering index SQLite does a full-table sort for the subquery
            # (O(n²) on 370 K rows → 4+ minutes).  The covering index lets
            # SQLite resolve the GROUP BY + MIN entirely from the index.
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_event_dedup "
                    "ON game_events(game_id, event_type, period, time, player_id, id)"
                )
            )

            # ── Composite index for sync_status cleanup query ─────────────────
            # The cleanup DELETE filters on both columns simultaneously; a
            # composite index is more selective than two separate indexes.
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_sync_cleanup "
                    "ON sync_status(sync_status, last_sync)"
                )
            )

            # ── Create admin_stats_snapshots if it doesn't exist ─────────────
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS admin_stats_snapshots (
                    ts                 DATETIME PRIMARY KEY,
                    db_size_bytes      INTEGER,
                    games              INTEGER,
                    players            INTEGER,
                    events             INTEGER,
                    player_stats       INTEGER,
                    jobs_run           INTEGER,
                    jobs_errors        INTEGER,
                    avg_job_duration_s REAL
                )
            """))

            # ── New composite indexes on player_statistics (idempotent) ─────────
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_stats_season_league_points "
                "ON player_statistics (season_id, league_abbrev, points)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_stats_season_player "
                "ON player_statistics (season_id, player_id)"
            ))

            # ── Add is_frozen to seasons ─────────────────────────────────────
            season_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(seasons)"))}
            if "is_frozen" not in season_cols:
                conn.execute(text("ALTER TABLE seasons ADD COLUMN is_frozen INTEGER NOT NULL DEFAULT 0"))

            # ── Add biographical cache columns to players ────────────────────
            existing_player_cols = {
                row[1] for row in conn.execute(text("PRAGMA table_info(players)"))
            }
            for col, typedef in [
                ("photo_url", "VARCHAR(500)"),
                ("height_cm", "INTEGER"),
                ("weight_kg", "INTEGER"),
                ("position_raw", "VARCHAR(50)"),
                ("license_raw", "VARCHAR(100)"),
                ("player_details_fetched_at", "DATETIME"),
            ]:
                if col not in existing_player_cols:
                    conn.execute(text(f"ALTER TABLE players ADD COLUMN {col} {typedef}"))

            conn.commit()
            logger.debug("SQLite migrations applied")

    def get_session(self) -> Session:
        """Get a new database session

        Returns:
            SQLAlchemy Session
        """
        if not self._initialized:
            self.initialize()
        return self.SessionLocal()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Provide a transactional scope around a series of operations

        Yields:
            SQLAlchemy Session

        Example:
            with db_service.session_scope() as session:
                players = session.query(Player).all()
        """
        lock = self._session_lock
        if lock is not None:
            lock.acquire()
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}", exc_info=True)
            raise
        finally:
            session.close()
            if lock is not None:
                lock.release()

    def drop_all_tables(self):
        """Drop all tables (use with caution!)"""
        if not self._initialized:
            self.initialize()
        logger.warning("Dropping all database tables")
        Base.metadata.drop_all(bind=self.engine)

    def recreate_all_tables(self):
        """Drop and recreate all tables (use with caution!)"""
        self.drop_all_tables()
        Base.metadata.create_all(bind=self.engine)
        logger.info("All tables recreated")

    def close(self):
        """Close database connections"""
        if self.engine:
            self.engine.dispose()
            self._initialized = False
            logger.info("Database connections closed")


# Global database service instance
_db_service: Optional[DatabaseService] = None


def get_database_service() -> DatabaseService:
    """Get the global database service instance

    Returns:
        DatabaseService instance
    """
    global _db_service
    if _db_service is None:
        _db_service = DatabaseService()
        _db_service.initialize()
    return _db_service


def get_db_session() -> Generator[Session, None, None]:
    """Dependency for FastAPI endpoints to get database session

    Yields:
        SQLAlchemy Session

    Example:
        @app.get("/players")
        def get_players(db: Session = Depends(get_db_session)):
            return db.query(Player).all()
    """
    db_service = get_database_service()
    session = db_service.get_session()
    try:
        yield session
    finally:
        session.close()
