"""
Re-export shim so callers can use `from app.database import run_lifecycle_migration`
without knowing the internal services layout.
"""

from app.services.database import (  # noqa: F401
    run_lifecycle_migration,
    DatabaseService,
    get_database_service,
    get_db_session,
)
