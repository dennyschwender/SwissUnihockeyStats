"""SwissUnihockey API client package."""

from .client import SwissUnihockeyClient
from .endpoints import (
    get_clubs,
    get_leagues,
    get_seasons,
    get_games,
    get_rankings,
    get_topscorers,
    get_teams,
    get_players,
)

__all__ = [
    'SwissUnihockeyClient',
    'get_clubs',
    'get_leagues',
    'get_seasons',
    'get_games',
    'get_rankings',
    'get_topscorers',
    'get_teams',
    'get_players',
]
