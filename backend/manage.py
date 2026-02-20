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
@click.option("--league-ids", default=None, help="Comma-separated league DB IDs to index (e.g. 1,2,3). Default: all leagues in season.")
@click.option("--max-tier", default=7, help="Max league tier to index (1=NLA/L-UPL only, 2=+NLB, 3=+1.Liga … 7=all). Default: 7 (all).")
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def index_team_rosters(season: int, league_ids: str, max_tier: int, force: bool):
    """Index player rosters for all teams filtered by league tier.

    Tier reference: 1=NLA/L-UPL, 2=NLB, 3=1.Liga, 4=2.Liga,
    5=3.Liga, 6=4./5.Liga, 7=Youth/Regional
    """
    from app.services.database import get_database_service
    from app.models.db_models import Team, League
    from app.services.data_indexer import league_tier

    click.echo(f"Indexing team rosters for season {season} (tier ≤ {max_tier}, force={force})...")
    db = get_database_service()
    indexer = get_data_indexer()

    with db.session_scope() as session:
        if league_ids:
            # Filter by explicit league DB IDs
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
            # Filter by tier using Team.league_id (API league_id)
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
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def index_player_stats(season: int, force: bool):
    """Index player statistics for all known players in a season."""
    click.echo(f"Indexing player stats for season {season} (force={force})...")
    indexer = get_data_indexer()
    count = indexer.index_player_stats_for_season(season_id=season, force=force)
    click.echo(f"✓ Indexed {count} player stat rows")


@cli.command()
@click.option("--season", default=2025, help="Season ID")
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def index_player_game_stats(season: int, force: bool):
    """Update game_players G/A/PIM for all known players using the overview API."""
    click.echo(f"Updating per-game G/A/PIM for season {season} (force={force})...")
    indexer = get_data_indexer()
    count = indexer.index_player_game_stats_for_season(season_id=season, force=force)
    click.echo(f"✓ Updated {count} game_players rows with G/A/PIM")


@cli.command()
@click.option("--season", default=2025, help="Season ID")
@click.option("--max-tier", default=3, help="Max league tier to include (default: 3)")
@click.option("--force", is_flag=True, default=False, help="Force re-index even if recently synced")
def index_game_lineups(season: int, max_tier: int, force: bool):
    """Index home+away player lineups for all scored games in a season."""
    from app.services.database import get_database_service
    from app.models.db_models import Game, Team
    from app.services.data_indexer import league_tier
    click.echo(f"Indexing game lineups for season {season} (max_tier={max_tier}, force={force})...")
    indexer = get_data_indexer()
    db = get_database_service()
    total = 0
    skipped = 0
    with db.session_scope() as session:
        # Collect team IDs in leagues up to max_tier
        rows = session.query(Team.id, Team.league_id).filter(Team.season_id == season).distinct().all()
        team_ids = {r[0] for r in rows if league_tier(r[1] or 0) <= max_tier}

        games = (
            session.query(Game.id)
            .filter(
                Game.season_id == season,
                Game.home_score.isnot(None),
                (Game.home_team_id.in_(team_ids)) | (Game.away_team_id.in_(team_ids)),
            )
            .all()
        )
        game_ids = [g.id for g in games]

    click.echo(f"  Found {len(game_ids)} scored games to process...")
    for game_id in game_ids:
        n = indexer.index_game_lineup(game_id, season_id=season, force=force)
        if n > 0:
            total += n
        else:
            skipped += 1

    click.echo(f"✓ Indexed {total} game-player rows ({skipped} games skipped/cached)")


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
