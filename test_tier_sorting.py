"""Test league tier sorting."""
import sys
sys.path.insert(0, 'backend')

from app.services.data_indexer import league_tier, LEAGUE_TIERS

print("League Tiers:")
print("=" * 60)

# Get all league IDs and their tiers
leagues = []
for league_id, tier in LEAGUE_TIERS.items():
    leagues.append((league_id, tier))

# Sort by tier
leagues.sort(key=lambda x: (x[1], x[0]))

for league_id, tier in leagues:
    print(f"League {league_id:2d} -> Tier {tier}")

print("\n" + "=" * 60)
print("Tier 1 = Top leagues (NLA)")
print("Tier 2 = NLB")
print("Tier 3 = 1. Liga")
print("Tier 4 = 2. Liga")
print("Tier 5 = 3. Liga")
print("Tier 6 = 4. Liga")
print("Tier 7 = Juniors (default)")
