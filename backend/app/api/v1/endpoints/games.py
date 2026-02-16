"""
Games API endpoints
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.swissunihockey import get_swissunihockey_client

router = APIRouter()


@router.get("/")
async def get_games(
    team: Optional[int] = Query(None, description="Filter by team ID"),
    league: Optional[int] = Query(None, description="Filter by league ID"),
    season: Optional[int] = Query(None, description="Filter by season"),
    mode: Optional[int] = Query(None, description="Filter by mode"),
    limit: Optional[int] = Query(None, description="Limit number of results")
):
    """
    Get list of games with optional filters
    
    - **team**: Filter by team ID
    - **league**: Filter by league ID
    - **season**: Filter by season year
    - **mode**: Filter by mode
    - **limit**: Limit number of results
    """
    try:
        client = get_swissunihockey_client()
        games_data = client.get_games(
            team=team,
            league=league,
            season=season,
            mode=mode
        )
        
        if not games_data or "entries" not in games_data:
            raise HTTPException(status_code=500, detail="Failed to fetch games")
        
        games = games_data["entries"]
        
        # Limit results if specified
        if limit:
            games = games[:limit]
        
        return {
            "total": len(games),
            "games": games
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{game_id}")
async def get_game(game_id: int):
    """
    Get details of a specific game by ID
    
    - **game_id**: Game identifier
    """
    try:
        client = get_swissunihockey_client()
        # Would need to filter games or have specific endpoint
        raise HTTPException(status_code=501, detail="Game details endpoint not yet implemented")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{game_id}/events")
async def get_game_events(game_id: int):
    """
    Get events for a specific game
    
    - **game_id**: Game identifier
    """
    try:
        client = get_swissunihockey_client()
        events_data = client.get_game_events(game_id=game_id)
        
        if not events_data or "entries" not in events_data:
            raise HTTPException(status_code=404, detail=f"No events found for game {game_id}")
        
        return events_data
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
