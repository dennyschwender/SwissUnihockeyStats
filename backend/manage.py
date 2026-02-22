"""
Management CLI for database operations and data indexing
"""
import click
import logging
from datetime import datetime

from app.services.database import get_database_service
from app.services.data_indexer import get_data_indexer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """Swiss Unihockey Stats - Database Management CLI"""
    pass


@cli.command()
def init_db():
    """Initialize the database (create tables)"""
    click.echo("Initializing database...")
    db_service = get_database_service()
    db_service.initialize()
    click.echo("✓ Database initialized successfully")


@cli.command()
@click.confirmation_option(prompt="Are you sure you want to drop all tables?")
def reset_db():
    """Drop and recreate all database tables (WARNING: deletes all data!)"""
    click.echo("Resetting database...")
    db_service = get_database_service()
    db_service.recreate_all_tables()
    click.echo("✓ Database reset successfully")


@cli.command()
def index_seasons():
    """Index all seasons from API"""
    click.echo("Indexing seasons...")
    indexer = get_data_indexer()
    count = indexer.index_seasons(force=True)
    click.echo(f"✓ Indexed {count} seasons")


@cli.command()
@click.option("--season", default=2025, help="Season ID to index")
@click.option("--max-clubs", default=None, type=int, help="Maximum number of clubs to process (for testing)")
def index_clubs_path(season: int, max_clubs: int):
    """Index following CLUBS → TEAMS → PLAYERS path"""
    click.echo(f"Starting CLUBS PATH indexing for season {season}...")
    if max_clubs:
        click.echo(f"(Limited to {max_clubs} clubs for testing)")
    
    indexer = get_data_indexer()
    stats = indexer.index_current_season_clubs_path(season_id=season, max_clubs=max_clubs)
    
    click.echo("\n=== Indexing Complete ===")
    click.echo(f"Seasons: {stats['seasons']}")
    click.echo(f"Clubs: {stats['clubs']}")
    click.echo(f"Teams: {stats['teams']}")
    click.echo(f"Players: {stats['players']}")


@cli.command()
@click.option("--season", default=2025, help="Season ID to index")
def index_leagues(season: int):
    """Index leagues only (no groups/games)"""
    click.echo(f"Indexing leagues for season {season}...")
    indexer = get_data_indexer()
    count = indexer.index_leagues(season_id=season, force=True)
    click.echo(f"✓ Indexed {count} leagues")


@cli.command()
@click.option("--season", default=2025, help="Season ID to index")
@click.option("--events", is_flag=True, default=False, help="Also fetch game events (slow)")
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def index_leagues_path(season: int, events: bool, force: bool):
    """Index full leagues hierarchy: leagues → groups → games [→ events]"""
    click.echo(f"Indexing leagues path for season {season} (events={events}, force={force})...")
    indexer = get_data_indexer()
    stats = indexer.index_leagues_path(
        season_id=season,
        index_games=True,
        index_events=events,
        force=force,
    )
    click.echo(f"Done: leagues={stats['leagues']}  groups={stats['groups']}  games={stats['games']}  team_names={stats['team_names']}  events={stats['events']}")


@cli.command()
@click.option("--season", default=2025, help="Season ID")
@click.option("--force", is_flag=True, default=False, help="Force even if recently synced")
def backfill_team_names(season: int, force: bool):
    """Backfill Team.name for stub rows using the rankings API"""
    click.echo(f"Backfilling team names for season {season} (force={force})...")
    indexer = get_data_indexer()
    n = indexer.backfill_team_names(season_id=season, force=force)
    click.echo(f"Done: {n} team rows updated")


@cli.command()
@click.option("--season", default=2025, help="Season ID")
@click.option("--team-id", default=None, type=int, help="Index a single team only")
@click.option("--league-ids", default=None, help="Comma-separated league DB IDs (e.g. 1,2,3). Default: all.")
@click.option("--max-tier", default=7, help="Max league tier (1=NLA, 2=+NLB, 3=+1.Liga … 7=all). Default: 7.")
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def index_team_rosters(season: int, team_id: int, league_ids: str, max_tier: int, force: bool):
    """Index player rosters for teams.

    Tier reference: 1=NLA/L-UPL, 2=NLB, 3=1.Liga, 4=2.Liga,
    5=3.Liga, 6=4./5.Liga, 7=Youth/Regional.

    With --team-id: updates a single team immediately (ignores --max-tier/--league-ids).
    """
    from app.services.database import get_database_service
    from app.models.db_models import Team, League
    from app.services.data_indexer import league_tier

    db = get_database_service()
    indexer = get_data_indexer()

    if team_id:
        click.echo(f"Indexing roster for team {team_id}, season {season}...")
        n = indexer.index_players_for_team(team_id=team_id, season_id=season, force=force)
        click.echo(f"✓ {n} players indexed")
        return

    click.echo(f"Indexing team rosters for season {season} (tier ≤ {max_tier}, force={force})...")
    with db.session_scope() as session:
        if league_ids:
            ids = [int(x.strip()) for x in league_ids.split(",")]
            rows = (
                session.query(Team.id)
                .filter(Team.season_id == season)
                .join(League, (Team.league_id == League.league_id) & (Team.season_id == League.season_id))
                .filter(League.id.in_(ids))
                .distinct()
                .all()
            )
            team_ids = sorted(r[0] for r in rows)
        else:
            rows = session.query(Team.id, Team.league_id).filter(Team.season_id == season).distinct().all()
            team_ids = sorted(r[0] for r in rows if league_tier(r[1] or 0) <= max_tier)

    click.echo(f"Found {len(team_ids)} teams (tier ≤ {max_tier}). Indexing rosters...")
    total = 0
    for i, tid in enumerate(team_ids, 1):
        n = indexer.index_players_for_team(team_id=tid, season_id=season, force=force)
        total += n
        if n > 0 or i % 20 == 0:
            click.echo(f"  [{i}/{len(team_ids)}] Team {tid}: {n} players")
    click.echo(f"\n✓ Total players indexed: {total}")


@cli.command()
@click.option("--season", default=2025, help="Season ID")
@click.option("--player-id", default=None, type=int, help="Index a single player only (person_id)")
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def index_player_stats(season: int, player_id: int, force: bool):
    """Index player statistics from /api/players/:id/statistics.

    Without --player-id: processes every known player in the season (~1 API call/player).
    With --player-id: updates a single player immediately.
    """
    indexer = get_data_indexer()
    if player_id:
        click.echo(f"Indexing stats for player {player_id}, season {season}...")
        count = indexer.index_player_stats_one(player_id=player_id, season_id=season, force=force)
        click.echo(f"✓ {count} stat rows upserted")
    else:
        click.echo(f"Indexing player stats for season {season} (force={force})...")
        count = indexer.index_player_stats_for_season(season_id=season, force=force)
        click.echo(f"✓ Indexed {count} player stat rows")


@cli.command()
@click.option("--season", default=2025, help="Season ID")
@click.option("--player-id", default=None, type=int, help="Update a single player only (person_id)")
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def index_player_game_stats(season: int, player_id: int, force: bool):
    """Update game_players G/A/PIM from /api/players/:id/overview.

    Without --player-id: processes every known player in the season.
    With --player-id: updates a single player immediately.
    """
    indexer = get_data_indexer()
    if player_id:
        click.echo(f"Updating per-game G/A/PIM for player {player_id}, season {season}...")
        count = indexer.index_player_game_stats(player_id=player_id, season_id=season, force=force)
        click.echo(f"✓ Updated {count} game_players rows")
    else:
        click.echo(f"Updating per-game G/A/PIM for season {season} (force={force})...")
        count = indexer.index_player_game_stats_for_season(season_id=season, force=force)
        click.echo(f"✓ Updated {count} game_players rows with G/A/PIM")


@cli.command()
@click.option("--season", default=2025, help="Season ID")
@click.option("--game-id", default=None, type=int, help="Index a single game only")
@click.option("--since", default=None, help="Only process games on or after this date (YYYY-MM-DD)")
@click.option("--max-tier", default=3, help="Max league tier to include (default: 3)")
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def index_game_lineups(season: int, game_id: int, since: str, max_tier: int, force: bool):
    """Index home+away player lineups for scored games.

    With --game-id: updates a single game immediately.
    With --since YYYY-MM-DD: only processes games played on or after that date
      (useful for incremental nightly runs).
    Without either: processes all scored games in the season up to --max-tier.
    """
    from app.services.database import get_database_service
    from app.models.db_models import Game, Team
    from app.services.data_indexer import league_tier
    from datetime import date as date_type

    indexer = get_data_indexer()
    db = get_database_service()

    if game_id:
        click.echo(f"Indexing lineup for game {game_id} (season {season})...")
        n = indexer.index_game_lineup(game_id, season_id=season, force=force)
        click.echo(f"✓ {n} game-player rows indexed")
        return

    since_date = None
    if since:
        try:
            since_date = date_type.fromisoformat(since)
        except ValueError:
            click.echo(f"ERROR: --since must be YYYY-MM-DD, got '{since}'", err=True)
            raise SystemExit(1)

    click.echo(f"Indexing game lineups for season {season} (max_tier={max_tier}"
               + (f", since={since}" if since_date else "") + f", force={force})...")

    total = 0
    skipped = 0
    with db.session_scope() as session:
        rows = session.query(Team.id, Team.league_id).filter(Team.season_id == season).distinct().all()
        team_ids = {r[0] for r in rows if league_tier(r[1] or 0) <= max_tier}

        q = (
            session.query(Game.id)
            .filter(
                Game.season_id == season,
                Game.home_score.isnot(None),
                (Game.home_team_id.in_(team_ids)) | (Game.away_team_id.in_(team_ids)),
            )
        )
        if since_date:
            q = q.filter(Game.game_date >= since_date)
        game_ids = [g.id for g in q.all()]

    click.echo(f"  Found {len(game_ids)} scored games to process...")
    for gid in game_ids:
        n = indexer.index_game_lineup(gid, season_id=season, force=force)
        if n > 0:
            total += n
        else:
            skipped += 1

    click.echo(f"✓ Indexed {total} game-player rows ({skipped} games skipped/cached)")


@cli.command()
@click.option("--season", default=2025, help="Season ID")
@click.option("--max-tier", default=3, help="Max league tier (1=NLA, 2=+NLB, 3=+1.Liga). Default: 3.")
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def full_sync(season: int, max_tier: int, force: bool):
    """Run the complete indexing pipeline for a season in dependency order.

    Step order (each step depends on the previous):

    \b
      1. index-seasons          (anchor for all season-scoped queries)
      2. index-leagues           (league hierarchy)
      3. index-leagues-path      (groups + games, no events)
      4. index-clubs-path        (clubs → teams → official rosters)
      5. index-team-rosters      (per-team player lists, tier ≤ max-tier)
      6. index-game-lineups      (player-game rows, tier ≤ max-tier)
      7. index-player-stats      (aggregate stats per player per league)
      8. index-player-game-stats (per-game G/A/PIM from overview API)

    Run individual steps for faster incremental refreshes.
    """
    click.echo(f"\n{'='*55}")
    click.echo(f"  Full sync  season={season}  max_tier={max_tier}  force={force}")
    click.echo(f"{'='*55}\n")

    indexer = get_data_indexer()

    def step(label, fn, *args, **kwargs):
        click.echo(f"[{label}] starting...")
        result = fn(*args, **kwargs)
        click.echo(f"[{label}] done → {result}")
        return result

    from app.services.data_indexer import league_tier
    from app.services.database import get_database_service
    from app.models.db_models import Team, Game

    step("1/8 seasons",     indexer.index_seasons, force=force)
    step("2/8 leagues",     indexer.index_leagues, season_id=season, force=force)
    step("3/8 leagues-path", indexer.index_leagues_path,
         season_id=season, index_games=True, index_events=False, force=force)
    step("4/8 clubs-path",  indexer.index_current_season_clubs_path, season_id=season)

    db = get_database_service()
    with db.session_scope() as session:
        rows = session.query(Team.id, Team.league_id).filter(Team.season_id == season).distinct().all()
        team_ids = sorted(r[0] for r in rows if league_tier(r[1] or 0) <= max_tier)

    click.echo(f"[5/8 team-rosters] {len(team_ids)} teams (tier ≤ {max_tier})...")
    roster_total = 0
    for i, tid in enumerate(team_ids, 1):
        roster_total += indexer.index_players_for_team(team_id=tid, season_id=season, force=force)
    click.echo(f"[5/8 team-rosters] done → {roster_total} players")

    with db.session_scope() as session:
        team_id_set = set(team_ids)
        game_ids = [
            g.id for g in
            session.query(Game.id)
            .filter(
                Game.season_id == season,
                Game.home_score.isnot(None),
                (Game.home_team_id.in_(team_id_set)) | (Game.away_team_id.in_(team_id_set)),
            ).all()
        ]

    click.echo(f"[6/8 game-lineups] {len(game_ids)} games...")
    lineup_total = 0
    for gid in game_ids:
        lineup_total += max(0, indexer.index_game_lineup(gid, season_id=season, force=force))
    click.echo(f"[6/8 game-lineups] done → {lineup_total} game-player rows")

    step("7/8 player-stats",     indexer.index_player_stats_for_season,  season_id=season, force=force)
    step("8/8 player-game-stats", indexer.index_player_game_stats_for_season, season_id=season, force=force)

    click.echo(f"\n{'='*55}")
    click.echo("  Full sync complete.")
    click.echo(f"{'='*55}\n")


@cli.command()
@click.option("--season", required=True, type=int, help="Reference season ID")
@click.option(
    "--mode",
    type=click.Choice(["exact", "older", "older-or-equal", "newer", "newer-or-equal"]),
    default="exact",
    show_default=True,
    help=(
        "Which seasons to purge relative to --season:\n\n"
        "  exact           – only that season\n"
        "  older           – seasons with id < season\n"
        "  older-or-equal  – seasons with id <= season\n"
        "  newer           – seasons with id > season\n"
        "  newer-or-equal  – seasons with id >= season"
    ),
)
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be deleted without deleting")
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompt")
def purge_season(season: int, mode: str, dry_run: bool, yes: bool):
    """Delete all data for one or more seasons from the database.

    Removes data in dependency order (leaf tables first) so foreign-key
    constraints are never violated. Orphaned players (no team memberships
    left after the purge) are removed automatically.

    SQLite's 999-variable limit is handled transparently by batching large
    IN (...) clauses into chunks of 500.

    Examples:\n
      # delete only season 2022\n
      python manage.py purge-season --season 2022\n\n
      # delete seasons 2020, 2021, 2022 (everything older-or-equal to 2022)\n
      python manage.py purge-season --season 2022 --mode older-or-equal\n\n
      # dry-run: show counts without touching the DB\n
      python manage.py purge-season --season 2022 --mode older --dry-run
    """
    from app.services.database import get_database_service
    from app.models.db_models import (
        Season, Club, League, LeagueGroup, Team, Player,
        TeamPlayer, Game, GamePlayer, GameEvent, PlayerStatistics, SyncStatus,
    )
    from sqlalchemy import func, or_ as sa_or

    # SQLite bind-variable limit; stay well below 999
    CHUNK = 500

    def batched_count(session, model, col, ids: list) -> int:
        """Count rows where col IN ids, chunked to avoid SQLite variable limit."""
        if not ids:
            return 0
        total = 0
        for i in range(0, len(ids), CHUNK):
            total += session.query(func.count(model.id)).filter(
                col.in_(ids[i : i + CHUNK])
            ).scalar() or 0
        return total

    def batched_delete(session, model, col, ids: list) -> int:
        """Delete rows where col IN ids, chunked to avoid SQLite variable limit."""
        if not ids:
            return 0
        total = 0
        for i in range(0, len(ids), CHUNK):
            total += session.query(model).filter(
                col.in_(ids[i : i + CHUNK])
            ).delete(synchronize_session=False)
        return total

    op_map = {
        "exact":          lambda col: col == season,
        "older":          lambda col: col < season,
        "older-or-equal": lambda col: col <= season,
        "newer":          lambda col: col > season,
        "newer-or-equal": lambda col: col >= season,
    }
    season_filter = op_map[mode]

    db = get_database_service()

    with db.session_scope() as session:
        target_season_ids = [
            r[0] for r in
            session.query(Season.id).filter(season_filter(Season.id)).all()
        ]

    if not target_season_ids:
        click.echo(f"No seasons found matching mode='{mode}' season={season}.")
        return

    click.echo(f"\nSeasons to purge ({len(target_season_ids)}): {sorted(target_season_ids)}")

    with db.session_scope() as session:
        game_ids = [
            r[0] for r in
            session.query(Game.id).filter(
                Game.season_id.in_(target_season_ids)
            ).all()
        ]
        league_ids = [
            r[0] for r in
            session.query(League.id).filter(
                League.season_id.in_(target_season_ids)
            ).all()
        ]
        sync_filters = sa_or(*[
            SyncStatus.entity_id.like(f"%:{s}:%") | SyncStatus.entity_id.like(f"%:{s}")
            for s in target_season_ids
        ]) if target_season_ids else (SyncStatus.id == -1)

        counts = {
            "GameEvent":        batched_count(session, GameEvent,        GameEvent.game_id,            game_ids),
            "GamePlayer":       batched_count(session, GamePlayer,       GamePlayer.game_id,           game_ids),
            "PlayerStatistics": batched_count(session, PlayerStatistics, PlayerStatistics.season_id,   target_season_ids),
            "TeamPlayer":       batched_count(session, TeamPlayer,       TeamPlayer.season_id,         target_season_ids),
            "Game":             len(game_ids),
            "LeagueGroup":      batched_count(session, LeagueGroup,      LeagueGroup.league_id,        league_ids),
            "Team":             batched_count(session, Team,             Team.season_id,               target_season_ids),
            "Club":             batched_count(session, Club,             Club.season_id,               target_season_ids),
            "League":           len(league_ids),
            "SyncStatus":       session.query(func.count(SyncStatus.id)).filter(sync_filters).scalar() or 0,
            "Season":           len(target_season_ids),
        }

    click.echo("\nRows that will be deleted:")
    total = 0
    for name, n in counts.items():
        click.echo(f"  {name:20s}: {n:>8,}")
        total += n
    click.echo(f"  {'TOTAL':20s}: {total:>8,}")

    if dry_run:
        click.echo("\n[dry-run] Nothing deleted.")
        return

    if not yes:
        click.confirm(f"\nPermanently delete {total:,} rows across {len(target_season_ids)} season(s)?", abort=True)

    click.echo("\nDeleting...")
    with db.session_scope() as session:
        game_ids = [
            r[0] for r in
            session.query(Game.id).filter(
                Game.season_id.in_(target_season_ids)
            ).all()
        ]
        league_ids = [
            r[0] for r in
            session.query(League.id).filter(
                League.season_id.in_(target_season_ids)
            ).all()
        ]

        n = batched_delete(session, GameEvent,        GameEvent.game_id,            game_ids)
        click.echo(f"  Deleted {n:,} GameEvent rows")

        n = batched_delete(session, GamePlayer,       GamePlayer.game_id,           game_ids)
        click.echo(f"  Deleted {n:,} GamePlayer rows")

        n = batched_delete(session, PlayerStatistics, PlayerStatistics.season_id,   target_season_ids)
        click.echo(f"  Deleted {n:,} PlayerStatistics rows")

        n = batched_delete(session, TeamPlayer,       TeamPlayer.season_id,         target_season_ids)
        click.echo(f"  Deleted {n:,} TeamPlayer rows")

        n = batched_delete(session, Game,             Game.season_id,               target_season_ids)
        click.echo(f"  Deleted {n:,} Game rows")

        n = batched_delete(session, LeagueGroup,      LeagueGroup.league_id,        league_ids)
        click.echo(f"  Deleted {n:,} LeagueGroup rows")

        n = batched_delete(session, Team,             Team.season_id,               target_season_ids)
        click.echo(f"  Deleted {n:,} Team rows")

        n = batched_delete(session, Club,             Club.season_id,               target_season_ids)
        click.echo(f"  Deleted {n:,} Club rows")

        n = batched_delete(session, League,           League.season_id,             target_season_ids)
        click.echo(f"  Deleted {n:,} League rows")

        sync_filters = sa_or(*[
            SyncStatus.entity_id.like(f"%:{s}:%") | SyncStatus.entity_id.like(f"%:{s}")
            for s in target_season_ids
        ]) if target_season_ids else (SyncStatus.id == -1)
        n = session.query(SyncStatus).filter(sync_filters).delete(synchronize_session=False)
        click.echo(f"  Deleted {n:,} SyncStatus rows")

        n = batched_delete(session, Season, Season.id, target_season_ids)
        click.echo(f"  Deleted {n:,} Season rows")

        # Remove orphaned players (no TeamPlayer rows remaining anywhere)
        orphan_ids = [
            r[0] for r in
            session.query(Player.person_id)
            .outerjoin(TeamPlayer, TeamPlayer.player_id == Player.person_id)
            .filter(TeamPlayer.player_id.is_(None))
            .all()
        ]
        if orphan_ids:
            n = batched_delete(session, Player, Player.person_id, orphan_ids)
            click.echo(f"  Deleted {n:,} orphaned Player rows")

    click.echo("\n✓ Purge complete.")


@cli.command()
def stats():
    """Show database statistics"""
    from app.services.database import get_database_service
    from app.models.db_models import LeagueGroup, GameEvent
    from sqlalchemy import func
    indexer = get_data_indexer()
    s = indexer.get_indexing_stats()
    db = get_database_service()
    with db.session_scope() as session:
        groups = session.query(func.count(LeagueGroup.id)).scalar() or 0
        events = session.query(func.count(GameEvent.id)).scalar() or 0

    click.echo("\n=== Database Statistics ===")
    click.echo(f"Seasons:       {s['seasons']}")
    click.echo(f"Clubs:         {s['clubs']}")
    click.echo(f"Teams:         {s['teams']}")
    click.echo(f"Players:       {s['players']}")
    click.echo(f"Team-Players:  {s['team_players']}")
    click.echo(f"Leagues:       {s['leagues']}")
    click.echo(f"League Groups: {groups}")
    click.echo(f"Games:         {s['games']}")
    click.echo(f"Game Events:   {events}")
    click.echo(f"\nLast updated: {s['last_updated']}")


@cli.command()
@click.argument("query")
def search_players(query: str):
    """Search for players by name"""
    from app.services.database import get_database_service
    from app.models.db_models import Player
    from sqlalchemy import or_
    
    db_service = get_database_service()
    with db_service.session_scope() as session:
        players = session.query(Player).filter(
            or_(
                Player.full_name.ilike(f"%{query}%"),
                Player.name_normalized.like(f"%{query.lower()}%")
            )
        ).limit(20).all()
        
        if not players:
            click.echo(f"No players found matching '{query}'")
            return
        
        click.echo(f"\nFound {len(players)} players matching '{query}':\n")
        for player in players:
            click.echo(f"  [{player.person_id}] {player.full_name}")
            # Show teams
            for tp in player.team_memberships[:3]:  # Show first 3 teams
                click.echo(f"      → {tp.team.name if tp.team else 'Unknown Team'}")


if __name__ == "__main__":
    cli()
