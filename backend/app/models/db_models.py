"""
Database models for Swiss Unihockey Stats
Implements hierarchical data structure matching API structure
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, ForeignKeyConstraint, Boolean, JSON, Float, Text, Index
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


class Season(Base):
    """Season entity - top level of hierarchy"""
    __tablename__ = "seasons"
    
    id = Column(Integer, primary_key=True)  # API season ID (e.g., 2025)
    text = Column(String(50))  # Display name (e.g., "2025/26")
    highlighted = Column(Boolean, default=False)
    last_updated = Column(DateTime, default=datetime.utcnow)
    last_full_sync = Column(DateTime, nullable=True)
    
    # Relationships
    clubs = relationship("Club", back_populates="season", cascade="all, delete-orphan")
    leagues = relationship("League", back_populates="season", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_season_id', 'id'),
    )


class Club(Base):
    """Club entity - belongs to season"""
    __tablename__ = "clubs"
    
    id = Column(Integer, primary_key=True)  # API club ID
    season_id = Column(Integer, ForeignKey("seasons.id"), primary_key=True, nullable=False)
    name = Column(String(200))
    text = Column(String(200))
    region = Column(String(100), nullable=True)
    logo_url = Column(String(500), nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    season = relationship("Season", back_populates="clubs")
    teams = relationship("Team", back_populates="club")
    
    __table_args__ = (
        Index('idx_club_name', 'name'),
    )


class League(Base):
    """League entity - belongs to season"""
    __tablename__ = "leagues"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=False)
    league_id = Column(Integer, nullable=False)  # API league ID (e.g., 2 for NLB)
    game_class = Column(Integer, nullable=False)  # 11=Men, 21=Women
    name = Column(String(200))
    text = Column(String(200))
    mode = Column(String(50), nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    season = relationship("Season", back_populates="leagues")
    groups = relationship("LeagueGroup", back_populates="league", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_league_season', 'season_id'),
        Index('idx_league_unique', 'season_id', 'league_id', 'game_class', unique=True),
    )


class LeagueGroup(Base):
    """League group entity - subdivision within a league"""
    __tablename__ = "league_groups"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    group_id = Column(Integer, nullable=False)  # API group ID
    name = Column(String(200))
    text = Column(String(200))
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    league = relationship("League", back_populates="groups")
    games = relationship("Game", back_populates="group", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_group_league', 'league_id'),
    )


class Team(Base):
    """Team entity - belongs to club and participates in leagues"""
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True)  # API team ID
    club_id = Column(Integer, nullable=True)  # Removed ForeignKey - using composite FK below
    season_id = Column(Integer, ForeignKey("seasons.id"), primary_key=True, nullable=False)  # Composite PK with id
    league_id = Column(Integer, nullable=True)  # API league ID
    game_class = Column(Integer, nullable=True)  # 11=Men, 21=Women
    name = Column(String(200))
    text = Column(String(200))
    logo_url = Column(String(500), nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    last_stats_update = Column(DateTime, nullable=True)
    
    # Relationships
    club = relationship("Club", back_populates="teams", foreign_keys="[Team.club_id, Team.season_id]")
    season = relationship("Season", overlaps="club,clubs,leagues,teams")
    players = relationship("TeamPlayer", back_populates="team", cascade="all, delete-orphan")
    home_games = relationship("Game", foreign_keys="Game.home_team_id", back_populates="home_team", overlaps="away_games,away_team")
    away_games = relationship("Game", foreign_keys="Game.away_team_id", back_populates="away_team", overlaps="home_games,home_team")
    
    __table_args__ = (
        ForeignKeyConstraint(['club_id', 'season_id'], ['clubs.id', 'clubs.season_id']),
        Index('idx_team_club', 'club_id'),
        Index('idx_team_season', 'season_id'),
        Index('idx_team_league', 'league_id', 'game_class'),
        Index('idx_team_name', 'name'),
    )


class Player(Base):
    """Player entity - unique person across seasons"""
    __tablename__ = "players"
    
    person_id = Column(Integer, primary_key=True)  # API person_id
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    full_name = Column(String(200))
    year_of_birth = Column(Integer, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # For search optimization
    name_normalized = Column(String(200))  # Lowercase for case-insensitive search
    
    # Relationships
    team_memberships = relationship("TeamPlayer", back_populates="player", cascade="all, delete-orphan")
    game_participations = relationship("GamePlayer", back_populates="player", cascade="all, delete-orphan")
    statistics = relationship("PlayerStatistics", back_populates="player", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_player_name', 'full_name'),
        Index('idx_player_name_normalized', 'name_normalized'),
        Index('idx_player_last_name', 'last_name'),
    )


class TeamPlayer(Base):
    """Association between players and teams (roster)"""
    __tablename__ = "team_players"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, nullable=False)  # Part of composite FK
    player_id = Column(Integer, ForeignKey("players.person_id"), nullable=False)
    jersey_number = Column(Integer, nullable=True)
    position = Column(String(50), nullable=True)  # Forward, Defense, Goalie
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    team = relationship("Team", back_populates="players", foreign_keys="[TeamPlayer.team_id, TeamPlayer.season_id]")
    player = relationship("Player", back_populates="team_memberships")
    season = relationship("Season", overlaps="clubs,leagues,players,team")
    
    __table_args__ = (
        ForeignKeyConstraint(['team_id', 'season_id'], ['teams.id', 'teams.season_id']),
        Index('idx_teamplayer_team', 'team_id'),
        Index('idx_teamplayer_player', 'player_id'),
        Index('idx_teamplayer_unique', 'team_id', 'player_id', 'season_id', unique=True),
    )


class Game(Base):
    """Game entity - belongs to group/league"""
    __tablename__ = "games"
    
    id = Column(Integer, primary_key=True)  # API game ID
    group_id = Column(Integer, ForeignKey("league_groups.id"), nullable=True)
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=False)
    home_team_id = Column(Integer, nullable=False)  # Part of composite FK
    away_team_id = Column(Integer, nullable=False)  # Part of composite FK
    game_date = Column(DateTime, nullable=True)
    game_time = Column(String(20), nullable=True)
    venue = Column(String(200), nullable=True)
    status = Column(String(50), nullable=True)  # scheduled, live, finished
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    period = Column(String(20), nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    last_events_update = Column(DateTime, nullable=True)
    
    # Relationships
    group = relationship("LeagueGroup", back_populates="games")
    season = relationship("Season", overlaps="clubs,leagues")
    home_team = relationship("Team", foreign_keys=[home_team_id, season_id], back_populates="home_games", overlaps="away_games,away_team,season")
    away_team = relationship("Team", foreign_keys=[away_team_id, season_id], back_populates="away_games", overlaps="home_games,home_team,season")
    players = relationship("GamePlayer", back_populates="game", cascade="all, delete-orphan")
    events = relationship("GameEvent", back_populates="game", cascade="all, delete-orphan")
    
    __table_args__ = (
        ForeignKeyConstraint(['home_team_id', 'season_id'], ['teams.id', 'teams.season_id']),
        ForeignKeyConstraint(['away_team_id', 'season_id'], ['teams.id', 'teams.season_id']),
        Index('idx_game_season', 'season_id'),
        Index('idx_game_teams', 'home_team_id', 'away_team_id'),
        Index('idx_game_date', 'game_date'),
        Index('idx_game_status', 'status'),
    )


class GamePlayer(Base):
    """Association between games and players (lineup)"""
    __tablename__ = "game_players"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.person_id"), nullable=False)
    team_id = Column(Integer, nullable=False)  # Part of composite FK
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=False)  # For composite FK to team
    is_home_team = Column(Boolean, nullable=False)
    jersey_number = Column(Integer, nullable=True)
    position = Column(String(50), nullable=True)
    goals = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    penalty_minutes = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    game = relationship("Game", back_populates="players")
    player = relationship("Player", back_populates="game_participations")
    team = relationship("Team", foreign_keys="[GamePlayer.team_id, GamePlayer.season_id]", overlaps="away_games,away_team,home_games,home_team,season")
    season = relationship("Season", overlaps="game,players,team")
    
    __table_args__ = (
        ForeignKeyConstraint(['team_id', 'season_id'], ['teams.id', 'teams.season_id']),
        Index('idx_gameplayer_game', 'game_id'),
        Index('idx_gameplayer_player', 'player_id'),
        Index('idx_gameplayer_unique', 'game_id', 'player_id', unique=True),
    )


class GameEvent(Base):
    """Game event entity (goals, penalties, etc.)"""
    __tablename__ = "game_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    event_type = Column(String(50), nullable=False)  # goal, penalty, timeout, etc.
    period = Column(Integer, nullable=True)
    time = Column(String(20), nullable=True)  # Game time (e.g., "12:34")
    team_id = Column(Integer, nullable=True)  # Part of composite FK (will get season from game)
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=True)  # For composite FK to team
    player_id = Column(Integer, ForeignKey("players.person_id"), nullable=True)
    description = Column(Text, nullable=True)
    raw_data = Column(JSON, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    game = relationship("Game", back_populates="events")
    team = relationship("Team", foreign_keys="[GameEvent.team_id, GameEvent.season_id]", overlaps="away_games,away_team,home_games,home_team,season")
    player = relationship("Player")
    season = relationship("Season", overlaps="game,events,team")
    
    __table_args__ = (
        ForeignKeyConstraint(['team_id', 'season_id'], ['teams.id', 'teams.season_id']),
        Index('idx_event_game', 'game_id'),
        Index('idx_event_player', 'player_id'),
    )


class PlayerStatistics(Base):
    """Aggregated player statistics"""
    __tablename__ = "player_statistics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.person_id"), nullable=False)
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=False)
    team_id = Column(Integer, nullable=True)  # Part of composite FK
    team_name = Column(String, nullable=True)     # Club/team name text from API
    league_abbrev = Column(String, nullable=True)  # League abbreviation from API (e.g. "NLB", "NLA")
    games_played = Column(Integer, default=0)
    goals = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    points = Column(Integer, default=0)
    penalty_minutes = Column(Integer, default=0)
    pen_2min  = Column(Integer, default=0)   # count of 2-minute penalties
    pen_5min  = Column(Integer, default=0)   # count of 5-minute penalties
    pen_10min = Column(Integer, default=0)   # count of 10-minute penalties
    pen_match = Column(Integer, default=0)   # count of match penalties
    plus_minus = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    player = relationship("Player", back_populates="statistics")
    season = relationship("Season", overlaps="player,statistics,clubs,leagues")
    team = relationship("Team", foreign_keys="[PlayerStatistics.team_id, PlayerStatistics.season_id]", overlaps="away_games,away_team,home_games,home_team,season")
    
    __table_args__ = (
        ForeignKeyConstraint(['team_id', 'season_id'], ['teams.id', 'teams.season_id']),
        Index('idx_stats_player', 'player_id'),
        Index('idx_stats_season', 'season_id'),
        # Unique per player+season+league (league_abbrev is never NULL; team_id was
        # previously used but is always NULL which lets SQLite store duplicates).
        Index('idx_stats_unique', 'player_id', 'season_id', 'league_abbrev', unique=True),
    )


class SyncStatus(Base):
    """Track sync status for different data types"""
    __tablename__ = "sync_status"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(50), nullable=False)  # seasons, clubs, leagues, players, games
    entity_id = Column(String(100), nullable=True)  # e.g., "season:2025", "club:463820"
    last_sync = Column(DateTime, nullable=False, default=datetime.utcnow)
    sync_status = Column(String(50), default="pending")  # pending, in_progress, completed, failed
    error_message = Column(Text, nullable=True)
    records_synced = Column(Integer, default=0)
    
    __table_args__ = (
        Index('idx_sync_entity', 'entity_type', 'entity_id'),
        Index('idx_sync_status', 'sync_status'),
        Index('idx_sync_last', 'last_sync'),
    )
