"""
Database service for managing connections and sessions
"""
import logging
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

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
            # SQLite-specific configuration
            self.engine = create_engine(
                self.database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False  # Set to True for SQL debugging
            )
            
            # Enable foreign keys for SQLite
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for better concurrency
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
        
        self._initialized = True
        logger.info("Database initialized successfully")
    
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
_db_service: DatabaseService = None


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
