"""
Clubs API endpoints
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()


@router.get("/")
async def get_clubs(
    name: Optional[str] = Query(None, description="Filter by club name"),
    limit: Optional[int] = Query(None, description="Limit number of results")
):
    """
    Get list of all Swiss Unihockey clubs
    
    - **name**: Optional filter by club name (case-insensitive)
    - **limit**: Optional limit on number of results
    """
    try:
        client = get_swissunihockey_client()
        clubs_data = client.get_clubs()
        
        if not clubs_data or "entries" not in clubs_data:
            raise HTTPException(status_code=500, detail="Failed to fetch clubs")
        
        clubs = clubs_data["entries"]
        
        # Filter by name if provided
        if name:
            clubs = [
                club for club in clubs
                if name.lower() in club.get("text", "").lower()
            ]
        
        # Limit results if specified
        if limit:
            clubs = clubs[:limit]
        
        return {
            "total": len(clubs),
            "clubs": clubs
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{club_id}")
async def get_club(club_id: int):
    """
    Get details of a specific club by ID
    
    - **club_id**: Club identifier
    """
    try:
        client = get_swissunihockey_client()
        clubs_data = client.get_clubs()
        
        if not clubs_data or "entries" not in clubs_data:
            raise HTTPException(status_code=500, detail="Failed to fetch clubs")
        
        # Find club by ID
        club = next(
            (c for c in clubs_data["entries"] if c.get("id") == club_id),
            None
        )
        
        if not club:
            raise HTTPException(status_code=404, detail=f"Club {club_id} not found")
        
        return club
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
