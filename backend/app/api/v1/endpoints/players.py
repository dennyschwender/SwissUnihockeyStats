"""
Players API endpoints
"""

import logging
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.services.swissunihockey import get_swissunihockey_client
from app.services.stats_service import get_player_recent_games as _get_recent_games

router = APIRouter()
logger = logging.getLogger(__name__)

_templates_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "templates")
_templates = Jinja2Templates(directory=os.path.abspath(_templates_dir))


@router.get("/")
async def search_players(
    name: Optional[str] = Query(None, description="Search by player name"),
    team: Optional[int] = Query(None, description="Filter by team ID"),
    club: Optional[int] = Query(None, description="Filter by club ID"),
    limit: Optional[int] = Query(100, description="Limit number of results", ge=1, le=1000),
):
    """
    Search for players

    - **name**: Search by player name (searches in results)
    - **team**: Filter by team ID
    - **club**: Filter by club ID
    - **limit**: Limit number of results (1–1000, default 100)
    """
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        players_data = await loop.run_in_executor(
            None, lambda: client.get_players(team=team, club=club)
        )

        if not players_data or "entries" not in players_data:
            return {"total": 0, "players": []}

        players = players_data["entries"]

        if name:
            name_lower = name.lower()
            players = [p for p in players if name_lower in p.get("text", "").lower()]

        if limit:
            players = players[:limit]

        return {"total": len(players), "players": players}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error searching players: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{player_id}/games", response_class=HTMLResponse)
async def get_player_games(
    request: Request,
    player_id: int,
    offset: int = Query(0, ge=0, description="Number of rows to skip"),
    limit: int = Query(10, ge=1, le=50, description="Rows per page"),
    locale: str = Query("de", description="Locale for translated content"),
):
    """Return an HTML fragment of recent game rows for HTMX pagination."""
    import asyncio

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: _get_recent_games(player_id, offset=offset, limit=limit)
        )
        return _templates.TemplateResponse(
            "partials/player_games_fragment.html",
            {
                "request": request,
                "rows": result["rows"],
                "has_more": result["has_more"],
                "player_id": player_id,
                "locale": locale,
                "next_offset": offset + limit,
            },
        )
    except Exception as e:
        logger.error("Error fetching games for player %s: %s", player_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{player_id}")
async def get_player(player_id: int):
    """
    Get details of a specific player by ID

    - **player_id**: Player identifier (person_id)
    """
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        player_data = await loop.run_in_executor(
            None, lambda: client.get_players(person_id=player_id)
        )

        if not player_data or "entries" not in player_data:
            raise HTTPException(status_code=404, detail=f"Player {player_id} not found")

        players = player_data["entries"]

        if not players:
            raise HTTPException(status_code=404, detail=f"Player {player_id} not found")

        player = players[0]
        return {
            "player_id": player_id,
            "name": player.get("text", ""),
            **player.get("set_in_context", {}),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching player %s: %s", player_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
