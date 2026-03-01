#!/usr/bin/env python3
"""One-time backfill script: populate Team.logo_url from /api/games/{id} responses.

Strategy: iterate over distinct finished games (newest first), call game details
API once per game, update BOTH the home and away team logos in a single pass.
Stop when all teams for the target season have logos.

Run from the project root:
    python scripts/backfill_team_logos.py [season_id]
    Default season_id: 2025
"""
import os
import sys
import time
import requests
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "swissunihockey.db")
API_BASE = "https://api-v2.swissunihockey.ch"
TARGET_SEASON = int(sys.argv[1]) if len(sys.argv) > 1 else 2025


def get_game_logos(game_id: int) -> dict:
    """Returns {team_id: logo_url, ...} for up to 2 teams."""
    try:
        r = requests.get(f"{API_BASE}/api/games/{game_id}", timeout=10)
        r.raise_for_status()
        d = r.json()
        regions = d.get("data", {}).get("regions", [])
        rows = regions[0].get("rows", []) if regions else []
        if not rows:
            return {}
        cells = rows[0].get("cells", [])
        result = {}
        # cells[0]=home_logo, cells[1]=home_name/id, cells[2]=away_logo, cells[3]=away_name/id
        for logo_idx, name_idx in [(0, 1), (2, 3)]:
            if len(cells) > max(logo_idx, name_idx):
                logo_url = (cells[logo_idx].get("image") or {}).get("url")
                team_ids = (cells[name_idx].get("link") or {}).get("ids", [])
                if logo_url and team_ids:
                    result[team_ids[0]] = logo_url
        return result
    except Exception as e:
        print(f"  [warn] game {game_id}: {e}", flush=True)
        return {}


def main():
    conn = sqlite3.connect(DB_PATH)

    # Teams in target season with no logo
    missing = set(
        r[0] for r in conn.execute(
            "SELECT id FROM teams WHERE season_id=? AND logo_url IS NULL",
            (TARGET_SEASON,)
        ).fetchall()
    )
    total_missing = len(missing)
    print(f"Season {TARGET_SEASON}: {total_missing} teams without logo_url", flush=True)
    if not missing:
        print("Nothing to do.")
        return

    # Iterate over finished games for this season, newest first
    games = conn.execute("""
        SELECT id, home_team_id, away_team_id
        FROM games
        WHERE season_id=? AND status='finished'
        ORDER BY game_date DESC
    """, (TARGET_SEASON,)).fetchall()

    print(f"Scanning {len(games)} finished games...", flush=True)

    updated = 0
    api_calls = 0

    for game_id, home_id, away_id in games:
        # Skip games where we already have both team logos
        needs = {tid for tid in (home_id, away_id) if tid in missing}
        if not needs:
            continue

        logos = get_game_logos(game_id)
        api_calls += 1
        time.sleep(0.05)  # ~20 req/s

        for team_id, logo_url in logos.items():
            if team_id in missing and logo_url:
                conn.execute(
                    "UPDATE teams SET logo_url=? WHERE id=? AND season_id=?",
                    (logo_url, team_id, TARGET_SEASON)
                )
                missing.discard(team_id)
                updated += 1

        if updated % 20 == 0 and updated > 0:
            conn.commit()
            pct = (total_missing - len(missing)) / total_missing * 100
            print(f"  {updated} updated, {len(missing)} remaining ({pct:.0f}%) — {api_calls} API calls", flush=True)

        if not missing:
            print("  All teams covered!", flush=True)
            break

    conn.commit()
    print(f"\nDone. Updated {updated} teams via {api_calls} API calls.")
    if missing:
        print(f"{len(missing)} teams still without logo (no finished games found).")

    samples = conn.execute(
        "SELECT id, name, logo_url FROM teams WHERE season_id=? AND logo_url IS NOT NULL LIMIT 5",
        (TARGET_SEASON,)
    ).fetchall()
    print("\nSample teams with logos:")
    for row in samples:
        url = row[2] or ""
        print(f"  team {row[0]}: {row[1]} → {url[:70]}")


if __name__ == "__main__":
    main()
