"""
Clubs API endpoints
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
async def get_clubs(
    name: Optional[str] = Query(None, description="Filter by club name"),
    region: Optional[str] = Query(None, description="Filter by region"),
    limit: Optional[int] = Query(None, description="Limit number of results", ge=1, le=1000),
):
    """
    Get list of all clubs

    - **name**: Optional filter by club name (partial match)
    - **region**: Optional filter by region
    - **limit**: Optional limit on number of results (1–1000)
    """
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        clubs_data = await loop.run_in_executor(None, client.get_clubs)

        if not clubs_data or "entries" not in clubs_data:
            raise HTTPException(status_code=500, detail="Failed to fetch clubs")

        clubs = clubs_data["entries"]

        if name:
            name_lower = name.lower()
            clubs = [c for c in clubs if name_lower in c.get("text", "").lower()]

        if region:
            region_lower = region.lower()
            clubs = [c for c in clubs if region_lower in str(c.get("region", "")).lower()]

        if limit:
            clubs = clubs[:limit]

        return {"total": len(clubs), "clubs": clubs}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching clubs: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{club_id}")
async def get_club(club_id: int):
    """
    Get details of a specific club by ID

    - **club_id**: Club identifier
    """
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        client = get_swissunihockey_client()
        clubs_data = await loop.run_in_executor(None, client.get_clubs)

        if not clubs_data or "entries" not in clubs_data:
            raise HTTPException(status_code=500, detail="Failed to fetch clubs")

        club = next((c for c in clubs_data["entries"] if c.get("id") == club_id), None)

        if not club:
            raise HTTPException(status_code=404, detail=f"Club {club_id} not found")

        return club

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching club %s: %s", club_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
