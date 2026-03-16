"""
Teams API endpoints
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
async def get_teams(
    club: Optional[int] = Query(None, description="Filter by club ID"),
    league: Optional[int] = Query(None, description="Filter by league ID"),
    season: Optional[int] = Query(None, description="Filter by season"),
    limit: Optional[int] = Query(None, description="Limit number of results", ge=1, le=1000),
):
    """
    Get list of teams with optional filters

    - **club**: Filter by club ID
    - **league**: Filter by league ID
    - **season**: Filter by season year
    - **limit**: Limit number of results (1–1000)
    """
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        teams_data = await loop.run_in_executor(
            None, lambda: client.get_teams(club=club, league=league, season=season)
        )

        if not teams_data or "entries" not in teams_data:
            raise HTTPException(status_code=500, detail="Failed to fetch teams")

        teams = teams_data["entries"]

        if limit:
            teams = teams[:limit]

        return {"total": len(teams), "teams": teams}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching teams: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{team_id}")
async def get_team(team_id: int):
    """
    Get details of a specific team by ID

    - **team_id**: Team identifier
    """
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        teams_data = await loop.run_in_executor(None, client.get_teams)

        if not teams_data or "entries" not in teams_data:
            raise HTTPException(status_code=500, detail="Failed to fetch teams")

        team = None
        for t in teams_data["entries"]:
            team_context = t.get("set_in_context", {})
            if team_context.get("team_id") == team_id:
                team = {"team_id": team_id, "name": t.get("text", ""), **team_context}
                break

        if not team:
            raise HTTPException(status_code=404, detail=f"Team {team_id} not found")

        return team

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching team %s: %s", team_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
