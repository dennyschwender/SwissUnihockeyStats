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
