"""Example script demonstrating how to fetch data from SwissUnihockey API."""

import json
import os
import sys
from datetime import datetime

# Add parent directory to path to enable imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from api import SwissUnihockeyClient


def main():
    """Fetch and display sample data from SwissUnihockey API."""
    
    print("=" * 80)
    print("SwissUnihockey API Data Fetcher")
    print("=" * 80)
    print()
    
    # Initialize client
    client = SwissUnihockeyClient(locale="de-CH")
    
    try:
        # 1. Fetch all clubs
        print("1. Fetching all clubs...")
        clubs_data = client.get_clubs()
        if clubs_data.get("entries"):
            print(f"   ✓ Found {len(clubs_data['entries'])} clubs")
            print(f"   Example clubs:")
            for club in clubs_data['entries'][:5]:
                club_name = club.get('text', 'Unknown')
                club_id = club.get('set_in_context', {}).get('club_id', 'N/A')
                print(f"   - {club_name} (ID: {club_id})")
        print()
        
        # 2. Fetch all leagues
        print("2. Fetching all leagues...")
        leagues_data = client.get_leagues()
        if leagues_data.get("entries"):
            print(f"   ✓ Found {len(leagues_data['entries'])} leagues")
            print(f"   Example leagues:")
            for league in leagues_data['entries'][:5]:
                league_name = league.get('text', 'Unknown')
                context = league.get('set_in_context', {})
                print(f"   - {league_name} (league: {context.get('league')}, class: {context.get('game_class')})")
        print()
        
        # 3. Fetch all seasons
        print("3. Fetching all seasons...")
        seasons_data = client.get_seasons()
        if seasons_data.get("entries"):
            print(f"   ✓ Found {len(seasons_data['entries'])} seasons")
            print(f"   Available seasons:")
            for season in seasons_data['entries'][:5]:
                season_name = season.get('text', 'Unknown')
                season_year = season.get('set_in_context', {}).get('season', 'N/A')
                print(f"   - {season_name} (year: {season_year})")
        print()
        
        # 4. Fetch rankings for NLB Men (league=2, game_class=11) for current season
        print("4. Fetching NLB Men rankings for season 2025/26...")
        try:
            rankings_data = client.get_rankings(
                league=2,
                game_class=11,
                season=2025
            )
            print(f"   ✓ Rankings data type: {rankings_data.get('type', 'unknown')}")
            
            # Try to display standings if available
            if rankings_data.get('type') == 'table' and rankings_data.get('data'):
                table_data = rankings_data.get('data', {})
                rows = table_data.get('rows', [])
                if rows:
                    print(f"   ✓ Found {len(rows)} teams in standings")
                    print(f"   Top 5 teams:")
                    for i, row in enumerate(rows[:5], 1):
                        # Row structure varies, try to extract team info
                        team_name = row[1] if len(row) > 1 else "Unknown"
                        points = row[-1] if len(row) > 1 else "?"
                        print(f"   {i}. {team_name} - {points} pts")
        except Exception as e:
            print(f"   ✗ Could not fetch rankings: {str(e)}")
        print()
        
        # 5. Fetch top scorers
        print("5. Fetching top scorers for NLB Men 2025/26...")
        try:
            topscorers_data = client.get_topscorers(
                league=2,
                game_class=11,
                season=2025
            )
            print(f"   ✓ Top scorers data type: {topscorers_data.get('type', 'unknown')}")
            
            if topscorers_data.get('type') == 'table' and topscorers_data.get('data'):
                table_data = topscorers_data.get('data', {})
                rows = table_data.get('rows', [])
                if rows:
                    print(f"   ✓ Found {len(rows)} players in top scorers")
                    print(f"   Top 5 scorers:")
                    for i, row in enumerate(rows[:5], 1):
                        player_name = row[0] if len(row) > 0 else "Unknown"
                        goals = row[1] if len(row) > 1 else "?"
                        print(f"   {i}. {player_name} - {goals} goals")
        except Exception as e:
            print(f"   ✗ Could not fetch top scorers: {str(e)}")
        print()
        
        # Save raw data to files
        print("6. Saving raw data to JSON files...")
        data_dir = os.path.join(parent_dir, "data", "raw")
        os.makedirs(data_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        files_saved = []
        for name, data in [
            ("clubs", clubs_data),
            ("leagues", leagues_data),
            ("seasons", seasons_data),
        ]:
            filename = f"{name}_{timestamp}.json"
            filepath = os.path.join(data_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            files_saved.append(filename)
            print(f"   ✓ Saved {filename}")
        
        print()
        print("=" * 80)
        print("Summary:")
        print(f"✓ Successfully fetched data from SwissUnihockey API")
        print(f"✓ Saved {len(files_saved)} files to {data_dir}")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        client.close()


if __name__ == "__main__":
    main()
