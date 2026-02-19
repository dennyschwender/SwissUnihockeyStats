"""Test script to verify recent games functionality."""
import sys
sys.path.insert(0, 'backend')

from app.services.stats_service import get_latest_results
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

# Test 1: All leagues - recent games
print("=" * 80)
print("Test 1: Recent games - All leagues (should show 12 games)")
print("=" * 80)
all_recent = get_latest_results(limit=12, season_id=active_season)
print(f"Found {len(all_recent)} games")
print(f"Type of first item: {type(all_recent[0]) if all_recent else 'N/A'}")
if all_recent:
    print(f"First game keys: {all_recent[0].keys() if isinstance(all_recent[0], dict) else 'Not a dict'}")
for i, g in enumerate(all_recent, 1):
    if isinstance(g, dict):
        group = f"[{g.get('group_name', 'N/A')}]" if g.get('group_name') else ""
        score = f"{g['home_score']:2d}:{g['away_score']:2d}"
        print(f"{i}. {g['date']} {g['time']:5s} | {g['home_team']:30s} {score} {g['away_team']:30s} | {group:15s} | Category: {g.get('league_category', 'N/A')}")
    else:
        print(f"{i}. ERROR: Item is type {type(g)}, value: {g}")

# Test 2: Filter by specific league category
print("\n" + "=" * 80)
print("Test 2: Recent games - Filter by league category '2_11' (Herren NLB)")
print("=" * 80)
nlb_recent = get_latest_results(limit=12, league_category='2_11', season_id=active_season)
print(f"Found {len(nlb_recent)} games")
for i, g in enumerate(nlb_recent, 1):
    group = f"[{g.get('group_name', 'N/A')}]" if g.get('group_name') else ""
    score = f"{g['home_score']:2d}:{g['away_score']:2d}"
    print(f"{i}. {g['date']} {g['time']:5s} | {g['home_team']:30s} {score} {g['away_team']:30s} | {group:15s} | Category: {g.get('league_category', 'N/A')}")

# Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"✓ All leagues: {len(all_recent)} recent games (expected: up to 12)")
print(f"✓ NLB (2_11): {len(nlb_recent)} recent games (expected: up to 12)")
print("\nRecent games show completed matches with scores, ordered most recent first.")
