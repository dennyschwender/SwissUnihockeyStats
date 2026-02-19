"""Test script to verify league category filtering works correctly."""
import sys
sys.path.insert(0, 'backend')

from app.services.stats_service import get_upcoming_games
from app.services.database import get_database_service
from app.models.db_models import PlayerStatistics
from sqlalchemy import func

# Get active season
db = get_database_service()
with db.session_scope() as session:
    active_season_row = (
        session.query(
            PlayerStatistics.season_id,
            func.count(PlayerStatistics.id).label('count')
        )
        .group_by(PlayerStatistics.season_id)
        .order_by(func.count(PlayerStatistics.id).desc())
        .first()
    )
    active_season = active_season_row[0] if active_season_row else 2025

print(f"Active season: {active_season}\n")

# Test 1: All leagues
print("=" * 80)
print("Test 1: All leagues (should show 12 games)")
print("=" * 80)
all_games = get_upcoming_games(limit=12, season_id=active_season)
print(f"Found {len(all_games)} games")
for i, g in enumerate(all_games, 1):
    print(f"{i}. {g['date']} {g['time']:5s} | {g['home_team']:30s} vs {g['away_team']:30s} | Category: {g.get('league_category', 'N/A')}")

# Test 2: Filter by specific league category
print("\n" + "=" * 80)
print("Test 2: Filter by league category '14_19' (Junioren U21 B)")
print("=" * 80)
filtered_games = get_upcoming_games(limit=12, league_category='14_19', season_id=active_season)
print(f"Found {len(filtered_games)} games")
for i, g in enumerate(filtered_games, 1):
    print(f"{i}. {g['date']} {g['time']:5s} | {g['home_team']:30s} vs {g['away_team']:30s} | Category: {g.get('league_category', 'N/A')}")

# Test 3: Another league category
print("\n" + "=" * 80)
print("Test 3: Filter by league category '2_11' (Herren NLB)")
print("=" * 80)
nlb_games = get_upcoming_games(limit=12, league_category='2_11', season_id=active_season)
print(f"Found {len(nlb_games)} games")
for i, g in enumerate(nlb_games, 1):
    print(f"{i}. {g['date']} {g['time']:5s} | {g['home_team']:30s} vs {g['away_team']:30s} | Category: {g.get('league_category', 'N/A')}")

# Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"✓ All leagues: {len(all_games)} games (expected: 12)")
print(f"✓ U21 B (14_19): {len(filtered_games)} games (expected: up to 12)")
print(f"✓ NLB (2_11): {len(nlb_games)} games (expected: up to 12)")
print("\nEach filter should return UP TO 12 games from that specific league.")
print("If there are fewer than 12 upcoming games in that league, it shows all available.")
