"""
Rankings API endpoints
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
async def get_rankings(
    league: Optional[int] = Query(None, description="League ID"),
    game_class: Optional[int] = Query(None, description="Game class ID"),
    group: Optional[int] = Query(None, description="Group ID"),
    season: Optional[int] = Query(None, description="Season year", le=2030),
    mode: Optional[int] = Query(None, description="Mode (e.g., 1=championship, 2=cup)")
):
    """
    Get league standings/rankings

    - **league**: League ID (e.g., 1=NLA, 2=NLB)
    - **game_class**: Game class ID (e.g., 11=Men, 12=Women)
    - **group**: Group ID for specific group standings
    - **season**: Season year (e.g., 2025 for 2025/26 season)
    - **mode**: Mode (1=championship, 2=cup, etc.)

    Example: `/api/v1/rankings?league=2&game_class=11&season=2025`
    """
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        rankings_data = await loop.run_in_executor(
            None, lambda: client.get_rankings(
                league=league, game_class=game_class, group=group, season=season, mode=mode
            )
        )

        if not rankings_data or "entries" not in rankings_data:
            raise HTTPException(
                status_code=404,
                detail="No rankings found for the specified criteria"
            )

        return {
            "total": len(rankings_data["entries"]),
            "rankings": rankings_data["entries"],
            "filters": {
                "league": league,
                "game_class": game_class,
                "group": group,
                "season": season,
                "mode": mode,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching rankings: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/topscorers")
async def get_topscorers(
    league: Optional[int] = Query(None, description="League ID"),
    game_class: Optional[int] = Query(None, description="Game class ID"),
    season: Optional[int] = Query(None, description="Season year"),
    limit: Optional[int] = Query(50, description="Limit number of results", ge=1, le=500)
):
    """
    Get top scorers for a league

    - **league**: League ID
    - **game_class**: Game class ID
    - **season**: Season year
    - **limit**: Limit number of results (1–500, default 50)
    """
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        topscorers_data = await loop.run_in_executor(
            None, lambda: client.get_topscorers(
                league=league, game_class=game_class, season=season
            )
        )

        if not topscorers_data or "entries" not in topscorers_data:
            raise HTTPException(
                status_code=404,
                detail="No top scorers found for the specified criteria"
            )

        scorers = topscorers_data["entries"]

        if limit:
            scorers = scorers[:limit]

        return {
            "total": len(scorers),
            "topscorers": scorers,
            "filters": {"league": league, "game_class": game_class, "season": season}
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching topscorers: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
