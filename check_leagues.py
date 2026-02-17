import asyncio
import sys
sys.path.insert(0, "C:/Users/denny/Development/SwissUnihockeyStats/backend")

from app.services.data_cache import get_cached_leagues

async def main():
    leagues = await get_cached_leagues()
    print(f"Total leagues: {len(leagues)}")
    print("\nFirst 5 leagues:")
    for i, league in enumerate(leagues[:5]):
        print(f"\n{i}. {league.get('text')}")
        print(f"   ID in data: {league.get('id', 'N/A')}")
        ctx = league.get('set_in_context', {})
        print(f"   league_id: {ctx.get('league_id', 'N/A')}")
        print(f"   mode: {ctx.get('mode', 'N/A')}")
        print(f"   type: {ctx.get('type', 'N/A')}")

if __name__ == "__main__":
    asyncio.run(main())
