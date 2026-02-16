"""
Teams API endpoints
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()


@router.get("/")
async def get_teams(
    club: Optional[int] = Query(None, description="Filter by club ID"),
    league: Optional[int] = Query(None, description="Filter by league ID"),
    season: Optional[int] = Query(None, description="Filter by season"),
    limit: Optional[int] = Query(None, description="Limit number of results")
):
    """
    Get list of teams with optional filters
    
    - **club**: Filter by club ID
    - **league**: Filter by league ID
    - **season**: Filter by season year
    - **limit**: Limit number of results
    """
    try:
        client = get_swissunihockey_client()
        teams_data = client.get_teams(club=club, league=league, season=season)
        
        if not teams_data or "entries" not in teams_data:
            raise HTTPException(status_code=500, detail="Failed to fetch teams")
        
        teams = teams_data["entries"]
        
        # Limit results if specified
        if limit:
            teams = teams[:limit]
        
        return {
            "total": len(teams),
            "teams": teams
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{team_id}")
async def get_team(team_id: int):
    """
    Get details of a specific team by ID
    
    - **team_id**: Team identifier
    """
    try:
        client = get_swissunihockey_client()
        # Would need specific team endpoint - this is a simplified version
        raise HTTPException(status_code=501, detail="Team details endpoint not yet implemented")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
