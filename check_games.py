"""Check if there are any completed games in the database."""
import sys
sys.path.insert(0, 'backend')

from app.services.database import get_database_service
from app.models.db_models import Game
from sqlalchemy import func

db = get_database_service()
with db.session_scope() as session:
    # Count total games
    total_games = session.query(func.count(Game.id)).scalar()
    print(f"Total games in database: {total_games}")
    
    # Count games with scores
    games_with_scores = session.query(func.count(Game.id)).filter(Game.home_score.isnot(None)).scalar()
    print(f"Games with scores: {games_with_scores}")
    
    # Count games without scores
    games_without_scores = session.query(func.count(Game.id)).filter(Game.home_score.is_(None)).scalar()
    print(f"Games without scores: {games_without_scores}")
    
    # Get some sample completed games
    print("\nSample completed games:")
    completed = session.query(Game).filter(Game.home_score.isnot(None)).limit(5).all()
    for g in completed:
        print(f"  Game {g.id}: {g.game_date} - Score: {g.home_score}:{g.away_score}")
    
    # Get games by date
    from datetime import date
    today = date.today()
    print(f"\nToday's date: {today}")
    
    past_games = session.query(func.count(Game.id)).filter(
        Game.game_date.isnot(None),
        Game.game_date < today
    ).scalar()
    print(f"Games before today: {past_games}")
    
    completed_past_games = session.query(func.count(Game.id)).filter(
        Game.home_score.isnot(None),
        Game.game_date.isnot(None),
        Game.game_date < today
    ).scalar()
    print(f"Completed games before today: {completed_past_games}")
