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
    team: Optional[int] = Query(None, description="Filter by team ID"),
    club: Optional[int] = Query(None, description="Filter by club ID"),
    limit: Optional[int] = Query(100, description="Limit number of results")
):
    """
    Search for players
    
    - **name**: Search by player name (searches in results)
    - **team**: Filter by team ID
    - **club**: Filter by club ID
    - **limit**: Limit number of results (default: 100)
    """
    try:
        client = get_swissunihockey_client()
        
        # Fetch players with filters
        players_data = client.get_players(team=team, club=club)
        
        if not players_data or "entries" not in players_data:
            return {"total": 0, "players": []}
        
        players = players_data["entries"]
        
        # Filter by name if provided
        if name:
            name_lower = name.lower()
            players = [
                p for p in players
                if name_lower in p.get("text", "").lower()
            ]
        
        # Limit results
        if limit:
            players = players[:limit]
        
        return {
            "total": len(players),
            "players": players
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{player_id}")
async def get_player(player_id: int):
    """
    Get details of a specific player by ID
    
    - **player_id**: Player identifier (person_id)
    """
    try:
        client = get_swissunihockey_client()
        
        # Fetch player by person_id
        player_data = client.get_players(person_id=player_id)
        
        if not player_data or "entries" not in player_data:
            raise HTTPException(status_code=404, detail=f"Player {player_id} not found")
        
        players = player_data["entries"]
        
        if not players:
            raise HTTPException(status_code=404, detail=f"Player {player_id} not found")
        
        # Return the first player (should be unique by person_id)
        player = players[0]
        
        return {
            "player_id": player_id,
            "name": player.get("text", ""),
            **player.get("set_in_context", {})
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
