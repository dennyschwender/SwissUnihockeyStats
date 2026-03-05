"""
Leagues API endpoints
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
async def get_leagues(
    mode: Optional[int] = Query(None, description="Filter by mode"),
    limit: Optional[int] = Query(None, description="Limit number of results", ge=1, le=1000)
):
    """
    Get list of all leagues/game classes

    - **mode**: Optional filter by mode
    - **limit**: Optional limit on number of results (1–1000)
    """
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        leagues_data = await loop.run_in_executor(None, client.get_leagues)

        if not leagues_data or "entries" not in leagues_data:
            raise HTTPException(status_code=500, detail="Failed to fetch leagues")

        leagues = leagues_data["entries"]

        if mode is not None:
            leagues = [lg for lg in leagues if lg.get("mode") == mode]

        if limit:
            leagues = leagues[:limit]

        return {"total": len(leagues), "leagues": leagues}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching leagues: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{league_id}")
async def get_league(league_id: int):
    """
    Get details of a specific league by ID

    - **league_id**: League identifier
    """
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        leagues_data = await loop.run_in_executor(None, client.get_leagues)

        if not leagues_data or "entries" not in leagues_data:
            raise HTTPException(status_code=500, detail="Failed to fetch leagues")

        league = next((lg for lg in leagues_data["entries"] if lg.get("id") == league_id), None)

        if not league:
            raise HTTPException(status_code=404, detail=f"League {league_id} not found")

        return league

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching league %s: %s", league_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
