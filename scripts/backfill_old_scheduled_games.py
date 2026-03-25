#!/usr/bin/env python3
"""
Backfill script: resolve old 'scheduled' games with no game_date from past seasons.

For each such game, queries the Swiss Unihockey API detail endpoint to determine
if the game was cancelled, played, or is otherwise resolvable.

Run inside Docker:
  docker exec swissunihockey-stats python3 /app/scripts/backfill_old_scheduled_games.py [--dry-run]
"""

import logging
import sys
import time

# Ensure backend is on path
# In Docker: /app is the workdir, app/ is the package
# Locally: backend/ contains app/
sys.path.insert(0, "/app")
sys.path.insert(0, "backend")

from app.services.database import get_database_service
from app.services.api_client import SwissUnihockeyClient
from app.services.season_utils import get_current_season
from app.models.db_models import Game, Season

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Cancelled keywords across all API languages
_CANCELLED_KEYWORDS = {"abgesagt", "cancelled", "annulé", "annullato"}


def _extract_cells_text(detail: dict) -> list[str]:
    """Extract all text values from a game detail API response."""
    texts = []
    for region in detail.get("data", {}).get("regions", []):
        for row in region.get("rows", []):
            for cell in row.get("cells", []):
                t = cell.get("text", [])
                if isinstance(t, list):
                    texts.extend(str(v).strip() for v in t if v)
                elif t:
                    texts.append(str(t).strip())
    return texts


def _is_cancelled(texts: list[str]) -> bool:
    return any(t.lower() in _CANCELLED_KEYWORDS for t in texts)


def _extract_score(texts: list[str]) -> tuple[int | None, int | None]:
    """Try to find a score like '5:3' in the text cells."""
    import re
    for t in texts:
        m = re.match(r"(\d+)\s*:\s*(\d+)", t.strip())
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def backfill(dry_run: bool = False):
    client = SwissUnihockeyClient()
    db_service = get_database_service()
    current_season = get_current_season()

    logger.info("Current season: %s", current_season)

    with db_service.session_scope() as session:
        # Find all scheduled games with no game_date from past (non-current) seasons
        games = (
            session.query(Game)
            .filter(
                Game.status == "scheduled",
                Game.game_date.is_(None),
                Game.season_id != current_season,
            )
            .all()
        )

        logger.info("Found %d scheduled games with no date in past seasons", len(games))

        cancelled = 0
        updated = 0
        errors = 0
        skipped = 0

        for i, game in enumerate(games):
            try:
                detail = client.get_game_details(game.id)
                texts = _extract_cells_text(detail)

                if _is_cancelled(texts):
                    logger.info("Game %s (season %s): CANCELLED", game.id, game.season_id)
                    if not dry_run:
                        game.status = "cancelled"
                        game.completeness_status = "cancelled"
                    cancelled += 1
                else:
                    # Check if there's a score
                    home, away = _extract_score(texts)
                    if home is not None:
                        logger.info(
                            "Game %s (season %s): has score %s:%s",
                            game.id, game.season_id, home, away,
                        )
                        if not dry_run:
                            game.home_score = home
                            game.away_score = away
                            game.status = "finished"
                            game.completeness_status = "complete"
                        updated += 1
                    else:
                        # No score, no cancellation — likely truly cancelled but not marked
                        # For past seasons, mark as cancelled since the game never happened
                        logger.info(
                            "Game %s (season %s): no score, no cancel marker — marking cancelled (past season)",
                            game.id, game.season_id,
                        )
                        if not dry_run:
                            game.status = "cancelled"
                            game.completeness_status = "cancelled"
                        cancelled += 1

            except Exception as exc:
                # 400/404 = game doesn't exist in API → cancelled
                if hasattr(exc, "response") and exc.response is not None:
                    status_code = exc.response.status_code
                    if status_code in (400, 404):
                        logger.info(
                            "Game %s (season %s): API returned %s — marking cancelled",
                            game.id, game.season_id, status_code,
                        )
                        if not dry_run:
                            game.status = "cancelled"
                            game.completeness_status = "cancelled"
                        cancelled += 1
                        continue

                logger.warning("Game %s: API error: %s", game.id, exc)
                errors += 1

            # Rate limiting: be nice to the API
            if (i + 1) % 10 == 0:
                time.sleep(1)
                logger.info("Progress: %d/%d", i + 1, len(games))

        if not dry_run:
            # session_scope commits automatically
            pass

        logger.info(
            "DONE%s: %d cancelled, %d updated with score, %d errors, %d total",
            " (DRY RUN)" if dry_run else "",
            cancelled, updated, errors, len(games),
        )


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    backfill(dry_run=dry_run)
