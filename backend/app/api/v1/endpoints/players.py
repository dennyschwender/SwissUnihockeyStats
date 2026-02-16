"""
Players API endpoints
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()


@router.get("/")
async def search_players(
    name: Optional[str] = Query(None, description="Search by player name"),
    club: Optional[int] = Query(None, description="Filter by club ID"),
    limit: Optional[int] = Query(100, description="Limit number of results")
):
    """
    Search for players
    
    - **name**: Search by player name
    - **club**: Filter by club ID
    - **limit**: Limit number of results (default: 100)
    """
    try:
        client = get_swissunihockey_client()
        
        # Note: The API client doesn't have a direct search method yet
        # This would need to be implemented or we'd query from a database
        raise HTTPException(
            status_code=501,
            detail="Player search not yet implemented. Use /api/v1/rankings for top scorers."
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{player_id}")
async def get_player(player_id: int):
    """
    Get details of a specific player by ID
    
    - **player_id**: Player identifier
    """
    try:
        raise HTTPException(status_code=501, detail="Player details endpoint not yet implemented")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
