"""
Utility for determining the current Swiss Unihockey season.

Extracted from main.py into its own module to avoid circular imports
(data_cache → main → data_cache).
"""
from datetime import datetime


def get_current_season() -> int:
    """
    Get the current Swiss Unihockey season year.
    Prefers the season flagged as highlighted in the DB.
    Falls back to date-based detection if DB is unavailable or no season is flagged.
    """
    try:
        from app.services.database import get_database_service
        from app.models.db_models import Season as _Season
        db = get_database_service()
        with db.session_scope() as session:
            row = session.query(_Season.id).filter(_Season.highlighted == True).first()
            if row:
                return row[0]
    except Exception:
        pass
    # Date-based fallback: Sep–Dec → current year, Jan–Aug → previous year
    now = datetime.now()
    return now.year if now.month >= 9 else now.year - 1
