"""
Main API v1 router - aggregates all endpoint routers
"""

from fastapi import APIRouter
from app.api.v1.endpoints import clubs, leagues, teams, games, players, rankings

api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(clubs.router, prefix="/clubs", tags=["clubs"])
api_router.include_router(leagues.router, prefix="/leagues", tags=["leagues"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(games.router, prefix="/games", tags=["games"])
api_router.include_router(players.router, prefix="/players", tags=["players"])
api_router.include_router(rankings.router, prefix="/rankings", tags=["rankings"])
