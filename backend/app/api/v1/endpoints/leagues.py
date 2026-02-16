"""
Leagues API endpoints
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()


@router.get("/")
async def get_leagues(
    mode: Optional[int] = Query(None, description="Filter by mode"),
    limit: Optional[int] = Query(None, description="Limit number of results")
):
    """
    Get list of all leagues/game classes
    
    - **mode**: Optional filter by mode
    - **limit**: Optional limit on number of results
    """
    try:
        client = get_swissunihockey_client()
        leagues_data = client.get_leagues()
        
        if not leagues_data or "entries" not in leagues_data:
            raise HTTPException(status_code=500, detail="Failed to fetch leagues")
        
        leagues = leagues_data["entries"]
        
        # Filter by mode if provided
        if mode is not None:
            leagues = [
                league for league in leagues
                if league.get("mode") == mode
            ]
        
        # Limit results if specified
        if limit:
            leagues = leagues[:limit]
        
        return {
            "total": len(leagues),
            "leagues": leagues
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{league_id}")
async def get_league(league_id: int):
    """
    Get details of a specific league by ID
    
    - **league_id**: League identifier
    """
    try:
        client = get_swissunihockey_client()
        leagues_data = client.get_leagues()
        
        if not leagues_data or "entries" not in leagues_data:
            raise HTTPException(status_code=500, detail="Failed to fetch leagues")
        
        # Find league by ID
        league = next(
            (l for l in leagues_data["entries"] if l.get("id") == league_id),
            None
        )
        
        if not league:
            raise HTTPException(status_code=404, detail=f"League {league_id} not found")
        
        return league
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
