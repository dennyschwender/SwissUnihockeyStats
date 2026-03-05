"""
Games API endpoints
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
async def get_games(
    team: Optional[int] = Query(None, description="Filter by team ID"),
    league: Optional[int] = Query(None, description="Filter by league ID"),
    season: Optional[int] = Query(None, description="Filter by season"),
    mode: Optional[int] = Query(None, description="Filter by mode"),
    limit: Optional[int] = Query(None, description="Limit number of results", ge=1, le=1000)
):
    """
    Get list of games with optional filters

    - **team**: Filter by team ID
    - **league**: Filter by league ID
    - **season**: Filter by season year
    - **mode**: Filter by mode
    - **limit**: Limit number of results (1–1000)
    """
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        games_data = await loop.run_in_executor(
            None, lambda: client.get_games(team=team, league=league, season=season, mode=mode)
        )

        if not games_data or "entries" not in games_data:
            return {"total": 0, "games": []}

        games = games_data["entries"]

        if limit:
            games = games[:limit]

        return {"total": len(games), "games": games}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching games: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{game_id}")
async def get_game(game_id: int):
    """
    Get details of a specific game by ID

    - **game_id**: Game identifier
    """
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        game_data = await loop.run_in_executor(None, lambda: client.get_game_events(game_id=game_id))

        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

        return game_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching game %s: %s", game_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{game_id}/events")
async def get_game_events(game_id: int):
    """
    Get events for a specific game

    - **game_id**: Game identifier
    """
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        events_data = await loop.run_in_executor(None, lambda: client.get_game_events(game_id=game_id))

        if not events_data or "entries" not in events_data:
            raise HTTPException(status_code=404, detail=f"No events found for game {game_id}")

        return events_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching events for game %s: %s", game_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
