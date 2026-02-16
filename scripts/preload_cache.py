"""Preload cache with commonly used data."""

import sys
from pathlib import Path

# Add parent directory to path
current_dir = Path(__file__).parent
parent_dir = current_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from api import SwissUnihockeyClient


def preload_cache():
    """Download and cache commonly used data."""
    
    print("=" * 80)
    print("CACHE PRELOADER")
    print("=" * 80)
    print("\nDownloading and caching commonly used data...")
    print()
    
    client = SwissUnihockeyClient(use_cache=True)
    
    # Static data (30-day cache)
    print("📦 Static Data (30-day cache):")
    print("  • Clubs...", end=" ", flush=True)
    try:
        clubs = client.get_clubs()
        club_count = len(clubs.get("entries", []))
        print(f"✓ ({club_count} clubs)")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print("  • Leagues...", end=" ", flush=True)
    try:
        leagues = client.get_leagues()
        league_count = len(leagues.get("entries", []))
        print(f"✓ ({league_count} leagues)")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print("  • Seasons...", end=" ", flush=True)
    try:
        seasons = client.get_seasons()
        season_count = len(seasons.get("entries", []))
        print(f"✓ ({season_count} seasons)")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print()
    
    # Dynamic data for current season (1-hour cache)
    print("📊 Dynamic Data (1-hour cache):")
    current_season = 2025
    leagues_to_cache = [
        (1, "NLA"),
        (2, "NLB"),
        (3, "1. Liga"),
    ]
    
    for league_id, league_name in leagues_to_cache:
        print(f"  • {league_name} Rankings...", end=" ", flush=True)
        try:
            client.get_rankings(league=league_id, game_class=11, season=current_season)
            print("✓")
        except Exception as e:
            print(f"✗ ({str(e)[:50]})")
        
        print(f"  • {league_name} Top Scorers...", end=" ", flush=True)
        try:
            client.get_topscorers(league=league_id, game_class=11, season=current_season)
            print("✓")
        except Exception as e:
            print(f"✗ ({str(e)[:50]})")
    
    print()
    
    # Display cache statistics
    print("=" * 80)
    print("CACHE STATISTICS")
    print("=" * 80)
    stats = client.cache.get_stats()
    
    print(f"  Total entries:  {stats['total_entries']}")
    print(f"  Total files:    {stats['total_files']}")
    print(f"  Total size:     {stats['total_size_mb']} MB")
    print()
    print("  Categories:")
    for category, count in stats['categories'].items():
        print(f"    • {category:15} {count} entries")
    
    print()
    print("=" * 80)
    print("✓ Cache preloaded successfully!")
    print("=" * 80)
    print()
    print("Your application will now run much faster! 🚀")
    print("Use client.get_clubs(), client.get_leagues(), etc. without API calls.")
    print()


if __name__ == "__main__":
    try:
        preload_cache()
    except KeyboardInterrupt:
        print("\n\n⚠️  Preload interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
