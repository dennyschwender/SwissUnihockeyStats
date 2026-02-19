"""Check game details from database and verify API response."""
import sys
sys.path.insert(0, 'backend')

from app.services.database import get_database_service
from app.models.db_models import Game, Season, PlayerStatistics
from sqlalchemy import func, desc
from datetime import date

db = get_database_service()
with db.session_scope() as session:
    # Find active season
    active_season_row = (
        session.query(
            PlayerStatistics.season_id,
            func.count(PlayerStatistics.id).label('count')
        )
        .group_by(PlayerStatistics.season_id)
        .order_by(func.count(PlayerStatistics.id).desc())
        .first()
    )
    
    if active_season_row:
        active_season_id = active_season_row[0]
        print(f"Active season ID: {active_season_id}")
        
        # Get season details
        season = session.query(Season).filter(Season.id == active_season_id).first()
        if season:
            print(f"Season text: {season.text}")
        
        # Check game details
        print("\n" + "=" * 80)
        print("GAMES FOR ACTIVE SEASON")
        print("=" * 80)
        
        total = session.query(func.count(Game.id)).filter(Game.season_id == active_season_id).scalar()
        print(f"Total games: {total}")
        
        with_scores = session.query(func.count(Game.id)).filter(
            Game.season_id == active_season_id,
            Game.home_score.isnot(None)
        ).scalar()
        print(f"Games with scores: {with_scores}")
        
        # Check by status
        statuses = session.query(Game.status, func.count(Game.id)).filter(
            Game.season_id == active_season_id
        ).group_by(Game.status).all()
        
        print("\nGames by status:")
        for status, count in statuses:
            print(f"  {status or 'NULL'}: {count}")
        
        # Sample some games
        print("\nSample games (most recent 10):")
        recent = session.query(Game).filter(
            Game.season_id == active_season_id,
            Game.game_date.isnot(None)
        ).order_by(desc(Game.game_date)).limit(10).all()
        
        for g in recent:
            score = f"{g.home_score}:{g.away_score}" if g.home_score is not None else "no score"
            print(f"  Game {g.id}: {g.game_date} - {score} - Status: {g.status}")
        
        # Check if there are games in the past
        today = date.today()
        past_games = session.query(func.count(Game.id)).filter(
            Game.season_id == active_season_id,
            Game.game_date < today
        ).scalar()
        print(f"\nGames before today ({today}): {past_games}")
        
        past_with_scores = session.query(func.count(Game.id)).filter(
            Game.season_id == active_season_id,
            Game.game_date < today,
            Game.home_score.isnot(None)
        ).scalar()
        print(f"Past games WITH scores: {past_with_scores}")
        
        past_without_scores = session.query(func.count(Game.id)).filter(
            Game.season_id == active_season_id,
            Game.game_date < today,
            Game.home_score.is_(None)
        ).scalar()
        print(f"Past games WITHOUT scores: {past_without_scores}")
        
        # Show sample past games without scores
        if past_without_scores > 0:
            print("\nSample past games without scores (first 5):")
            past_no_score = session.query(Game).filter(
                Game.season_id == active_season_id,
                Game.game_date < today,
                Game.home_score.is_(None)
            ).order_by(desc(Game.game_date)).limit(5).all()
            
            for g in past_no_score:
                print(f"  Game {g.id}: {g.game_date} - Status: {g.status or 'NULL'}")
