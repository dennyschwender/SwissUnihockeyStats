from api import SwissUnihockeyClient
import json

client = SwissUnihockeyClient(use_cache=True, cache_dir='data/cache')

team_id = 429607
print(f"Fetching data for team {team_id}...")

# Test players API
print("\n=== PLAYERS API ===")
try:
    players_data = client.get_players(team=team_id)
    print("Response keys:", players_data.keys() if isinstance(players_data, dict) else "Not a dict")
    
    if isinstance(players_data, dict):
        data = players_data.get('data', {})
        print("\nData keys:", data.keys())
        
        context = data.get('context', {})
        print("\nContext:", json.dumps(context, indent=2))
        
        title = data.get('title')
        print("\nTitle:", title)
        
        regions = data.get('regions', [])
        print(f"\nRegions count: {len(regions)}")
        if regions:
            rows = regions[0].get('rows', [])
            print(f"Players count: {len(rows)}")
except Exception as e:
    print(f"Error: {e}")

# Test teams from multiple leagues to find this team
print("\n\n=== SEARCHING FOR TEAM IN LEAGUES ===")
for league_num in [1, 2, 3, 4, 5]:
    for game_class in [11, 12, 21, 22, 31]:
        try:
            teams_data = client.get_teams(league=league_num, game_class=game_class)
            regions = teams_data.get('data', {}).get('regions', [])
            if regions:
                rows = regions[0].get('rows', [])
                for team in rows:
                    if team.get('id') == team_id:
                        print(f"\n✓ Found team {team_id} in league {league_num}, class {game_class}:")
                        print("Team structure:")
                        print(json.dumps(team, indent=2, default=str))
                        break
        except Exception as e:
            pass  # Skip errors for leagues/classes that don't exist
