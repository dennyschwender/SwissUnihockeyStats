"""
Database service for managing connections and sessions
"""
import logging
from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool, StaticPool

from app.models.db_models import Base
from app.config import settings

logger = logging.getLogger(__name__)


class DatabaseService:
    """Manages database connections and sessions"""
    
    def __init__(self, database_url: str = None):
        """Initialize database service
        
        Args:
            database_url: Database URL (defaults to settings)
        """
        self.database_url = database_url or self._get_database_url()
        self.engine = None
        self.SessionLocal = None
        self._initialized = False
    
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
                echo=False  # Set to True for SQL debugging
            )
            
            # Enable foreign keys for SQLite
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")   # concurrent readers + writer
                cursor.execute("PRAGMA busy_timeout=30000") # wait up to 30s for locks
                cursor.close()
        else:
            # PostgreSQL or other database
            self.engine = create_engine(
                self.database_url,
                pool_size=10,
                max_overflow=20,
                echo=False
            )
        
        # Create session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
        
        # Create all tables
        Base.metadata.create_all(bind=self.engine)

        # ── Schema migrations ────────────────────────────────────────────
        if self.database_url.startswith("sqlite"):
            self._run_sqlite_migrations()

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
                ("pen_2min",  "INTEGER DEFAULT 0"),
                ("pen_5min",  "INTEGER DEFAULT 0"),
                ("pen_10min", "INTEGER DEFAULT 0"),
                ("pen_match", "INTEGER DEFAULT 0"),
                ("game_class", "INTEGER"),
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

            # ── Drop the now-unused player_id index on game_events ──────────
            # player_id is always NULL (API returns names, not IDs), so the
            # index only stored NULLs.
            conn.execute(text("DROP INDEX IF EXISTS idx_event_player"))

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
