#!/usr/bin/env python
"""Test club detail functionality"""
import sys
sys.path.insert(0, r'c:\Users\denny.schwender\OneDrive - HCL TECHNOLOGIES LIMITED\10 - Maintenance Factory\10 - Command Center\99 - Scripting')

from app.services.swissunihockey import get_swissunihockey_client
from app.services.data_cache import get_cached_clubs
import asyncio

async def test_club_detail():
    club_id = 453009
    
    print(f"Testing club detail for ID {club_id}...")
    
    # Test client
    client = get_swissunihockey_client()
    print("✓ Got SwissUnihockey client")
    
    # Test cached clubs
    all_clubs = await get_cached_clubs()
    print(f"✓ Got {len(all_clubs)} clubs from cache")
    
    # Find club
    matching_clubs = [c for c in all_clubs if c.get("set_in_context", {}).get("club_id") == club_id]
    print(f"✓ Found {len(matching_clubs)} matching clubs")
    
    if matching_clubs:
        club = matching_clubs[0]
        print(f"  Club: {club.get('text')}")
        
        # Test teams AP I
        print(f"Fetching teams for club {club_id}...")
        try:
            teams_data = client.get_teams(club=club_id)
            print(f"✓ Teams API returned: {type(teams_data)}")
            print(f"  Keys: {list(teams_data.keys()) if isinstance(teams_data, dict) else 'not a dict'}")
            teams = teams_data.get("entries", teams_data.get("data", [])) if isinstance(teams_data, dict) else []
            print(f"✓ Extracted {len(teams)} teams")
            print(f"  Teams type: {type(teams)}")
            if teams:
                if isinstance(teams, list) and len(teams) > 0:
                    print(f"\nFirst team structure:")
                    print(f"  Type: {type(teams[0])}")
                    if isinstance(teams[0], dict):
                        print(f"  Keys: {list(teams[0].keys())}")
                        print(f"  'text' field: {teams[0].get('text', 'MISSING')}")
                        print(f"  'id' field: {teams[0].get('id', 'MISSING')}")
                        import json
                        print(f"\nFull team #1:")
                        print(json.dumps(teams[0], indent=2)[:500])
                elif isinstance(teams, dict):
                    print(f"  Teams is a dict, not a list! Keys: {list(teams.keys())}")
                else:
                    print(f"  Teams is type: {type(teams)}")
                    print(f"  Content preview: {str(teams)[:500]}")
        except Exception as e:
            print(f"✗ Error fetching teams: {e}")
            import traceback
            traceback.print_exc()
    
    print("\nTest complete!")

if __name__ == "__main__":
    asyncio.run(test_club_detail())
