from app.services.database import get_database_service
from app.models.db_models import Player

db = get_database_service()
db.initialize()

with db.session_scope() as session:
    players = session.query(Player).limit(10).all()
    print(f"Total players in db: {session.query(Player).count()}")
    print("\nFirst 10 players:")
    for p in players:
        print(f"  {p.person_id}: {p.full_name}")
    
    # Try searching for Weber
    weber_players = session.query(Player).filter(Player.full_name.ilike('%Weber%')).all()
    print(f"\nPlayers matching 'Weber': {len(weber_players)}")
    for p in weber_players:
        print(f"  {p.person_id}: {p.full_name}")
