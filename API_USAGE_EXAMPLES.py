"""Quick reference guide for using the SwissUnihockey API."""

# =============================================================================
# BASIC USAGE
# =============================================================================

# Import the client
from api import SwissUnihockeyClient

# Initialize client
client = SwissUnihockeyClient(locale="de-CH")  # Options: en, de-CH, fr-CH, it-CH

# =============================================================================
# COMMON QUERIES
# =============================================================================

# 1. GET ALL CLUBS
clubs = client.get_clubs()
# Returns: {"type": "dropdown", "entries": [{"text": "Club Name", "set_in_context": {"club_id": 123}}]}

# 2. GET ALL LEAGUES
leagues = client.get_leagues()
# Returns league/game_class combinations

# 3. GET ALL SEASONS
seasons = client.get_seasons()
# Returns: {"entries": [{"text": "2025/26", "set_in_context": {"season": 2025}}]}

# 4. GET LEAGUE STANDINGS/RANKINGS
# Required params: league, game_class, season
# Optional: group
rankings = client.get_rankings(
    league=2,          # 2 = NLB (National League B)
    game_class=11,     # 11 = Men/Herren, 21 = Women/Damen
    season=2025        # 2025 = season 2025/26
)

# 5. GET TOP SCORERS
# Same params as rankings
topscorers = client.get_topscorers(
    league=2,
    game_class=11,
    season=2025
)

# 6. GET GAMES
# Optional params: team_id, league, season, from_date, to_date
games = client.get_games(
    league=2,
    game_class=11,
    season=2025
)

# 7. GET GAME EVENTS (detailed play-by-play)
# Required: game_id
game_events = client.get_game_events(game_id=12345)

# 8. GET TEAMS
# Optional: club_id, league, season
teams = client.get_teams(club_id=463820)

# 9. GET PLAYERS
# Optional: team_id, club_id
players = client.get_players(club_id=463820)

# =============================================================================
# LEAGUE CODES
# =============================================================================

LEAGUES = {
    2: "NLB (National League B)",
    3: "1. Liga",
    4: "2. Liga", 
    5: "3. Liga",
    6: "4. Liga",
    7: "5. Liga",
    12: "Regional",
    13: "Interregional A",
    14: "Interregional B",
    23: "Supercup",
    24: "L-UPL",
}

# =============================================================================
# GAME CLASS CODES
# =============================================================================

GAME_CLASSES = {
    11: "Herren (Men)",
    12: "Herren (Men) - alternate",
    21: "Damen (Women)",
    22: "Damen (Women) - alternate",
    31: "Junioren A (Junior A)",
    32: "Junioren B (Junior B)",
    33: "Junioren C (Junior C)",
    34: "Junioren D (Junior D)",
    35: "Junioren E (Junior E)",
    36: "Junioren D+ (Junior D+)",
    41: "Juniorinnen A (Junior Women A)",
    42: "Juniorinnen B (Junior Women B)",
    43: "Juniorinnen C (Junior Women C)",
    44: "Juniorinnen D (Junior Women D)",
    51: "Senioren (Seniors)",
}

# =============================================================================
# EXAMPLE: GET NLB MEN STANDINGS FOR CURRENT SEASON
# =============================================================================

from api import SwissUnihockeyClient

with SwissUnihockeyClient() as client:
    # Get NLB Men standings
    standings = client.get_rankings(
        league=2,        # NLB
        game_class=11,   # Men
        season=2025      # 2025/26 season
    )
    
    # Get top scorers for same league
    scorers = client.get_topscorers(
        league=2,
        game_class=11,
        season=2025
    )
    
    # Get all games
    games = client.get_games(
        league=2,
        game_class=11,
        season=2025
    )

# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# You can also use convenience functions that read from config.ini
from api import get_clubs, get_leagues, get_seasons, get_rankings

clubs = get_clubs()
rankings = get_rankings(league=2, game_class=11, season=2025)

# =============================================================================
# ERROR HANDLING
# =============================================================================

from api import SwissUnihockeyClient
import requests

client = SwissUnihockeyClient()

try:
    data = client.get_rankings(league=2, game_class=11, season=2025)
except requests.exceptions.Timeout:
    print("Request timed out")
except requests.exceptions.HTTPError as e:
    print(f"HTTP error: {e}")
except requests.exceptions.RequestException as e:
    print(f"Request failed: {e}")
finally:
    client.close()

# =============================================================================
# CONTEXT MANAGER (RECOMMENDED)
# =============================================================================

# Automatically closes connection when done
with SwissUnihockeyClient() as client:
    data = client.get_clubs()
    # Process data
    # Connection automatically closed

# =============================================================================
# SAVE DATA TO FILE
# =============================================================================

import json
from api import SwissUnihockeyClient

with SwissUnihockeyClient() as client:
    clubs = client.get_clubs()
    
    # Save as JSON
    with open("clubs.json", "w", encoding="utf-8") as f:
        json.dump(clubs, f, indent=2, ensure_ascii=False)

# =============================================================================
# RESPONSE TYPES
# =============================================================================

# The API returns different response types:
# - DROPDOWN: Selection lists (clubs, leagues, seasons)
# - TABLE: Tabular data (rankings, top scorers)
# - ATTRIBUTE_LIST: Key-value pairs
# - MULTI_TABLE: Multiple tables

# Example TABLE response structure:
{
    "type": "table",
    "data": {
        "headers": ["Pos", "Team", "Games", "Wins", "Losses", "Points"],
        "rows": [
            [1, "Team A", 20, 15, 5, 45],
            [2, "Team B", 20, 14, 6, 42],
        ]
    }
}

# Example DROPDOWN response structure:
{
    "type": "dropdown",
    "entries": [
        {
            "text": "Club Name",
            "set_in_context": {"club_id": 123},
            "highlight": False
        }
    ]
}
