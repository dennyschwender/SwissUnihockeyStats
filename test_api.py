"""Test script to verify API client is working."""

import os
import sys

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from api import SwissUnihockeyClient


def test_connection():
    """Test basic API connection."""
    print("Testing SwissUnihockey API connection...")
    print("-" * 60)
    
    client = SwissUnihockeyClient()
    
    try:
        # Test 1: Fetch clubs
        print("\n1. Testing /api/clubs endpoint...")
        clubs = client.get_clubs()
        if clubs and clubs.get("entries"):
            print(f"   ✓ SUCCESS: Found {len(clubs['entries'])} clubs")
        else:
            print("   ✗ FAILED: No clubs data returned")
        
        # Test 2: Fetch leagues
        print("\n2. Testing /api/leagues endpoint...")
        leagues = client.get_leagues()
        if leagues and leagues.get("entries"):
            print(f"   ✓ SUCCESS: Found {len(leagues['entries'])} leagues")
        else:
            print("   ✗ FAILED: No leagues data returned")
        
        # Test 3: Fetch seasons
        print("\n3. Testing /api/seasons endpoint...")
        seasons = client.get_seasons()
        if seasons and seasons.get("entries"):
            print(f"   ✓ SUCCESS: Found {len(seasons['entries'])} seasons")
            current_season = seasons['entries'][0]
            print(f"   Current season: {current_season.get('text', 'Unknown')}")
        else:
            print("   ✗ FAILED: No seasons data returned")
        
        print("\n" + "-" * 60)
        print("✓ All basic tests passed!")
        print("\nYou can now:")
        print("  1. Run: python scripts\\example_fetch_data.py")
        print("  2. Install dependencies: pip install -r requirements.txt")
        print("  3. Start building your statistics website!")
        
    except Exception as e:
        print(f"\n✗ Error during testing: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        client.close()


if __name__ == "__main__":
    test_connection()
