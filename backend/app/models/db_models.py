"""
Database models for Swiss Unihockey Stats
Implements hierarchical data structure matching API structure
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Boolean,
    JSON,
    Float,
    Text,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware). Used as column default."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all models"""

    pass


class Season(Base):
    """Season entity - top level of hierarchy"""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # API season ID (e.g., 2025)
    text: Mapped[Optional[str]] = mapped_column(String(50))  # Display name (e.g., "2025/26")
    highlighted: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)
    last_full_sync: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")

    # Relationships
    clubs = relationship("Club", back_populates="season", cascade="all, delete-orphan")
    leagues = relationship("League", back_populates="season", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_season_id", "id"),)


class Club(Base):
    """Club entity - belongs to season"""

    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # API club ID
    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seasons.id"), primary_key=True, nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(String(200))
    text: Mapped[Optional[str]] = mapped_column(String(200))
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    season = relationship("Season", back_populates="clubs")
    teams = relationship("Team", back_populates="club")

    __table_args__ = (Index("idx_club_name", "name"),)


class League(Base):
    """League entity - belongs to season"""

    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(Integer, ForeignKey("seasons.id"), nullable=False)
    league_id: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # API league ID (e.g., 2 for NLB)
    game_class: Mapped[Optional[int]] = mapped_column(Integer, nullable=False)  # 11=Men, 21=Women
    name: Mapped[Optional[str]] = mapped_column(String(200))
    text: Mapped[Optional[str]] = mapped_column(String(200))
    mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    season = relationship("Season", back_populates="leagues")
    groups = relationship("LeagueGroup", back_populates="league", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_league_season", "season_id"),
        Index("idx_league_unique", "season_id", "league_id", "game_class", unique=True),
    )


class LeagueGroup(Base):
    """League group entity - subdivision within a league"""

    __tablename__ = "league_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(Integer, ForeignKey("leagues.id"), nullable=False)
    group_id: Mapped[int] = mapped_column(Integer, nullable=False)  # API group ID
    name: Mapped[Optional[str]] = mapped_column(String(200))
    text: Mapped[Optional[str]] = mapped_column(String(200))
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)
    phase: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )  # e.g. 'Regelsaison', 'Playoff Viertelfinals'

    # Relationships
    league = relationship("League", back_populates="groups")
    games = relationship("Game", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_group_league", "league_id"),)


class Team(Base):
    """Team entity - belongs to club and participates in leagues"""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # API team ID
    club_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # Removed ForeignKey - using composite FK below
    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seasons.id"), primary_key=True, nullable=False
    )  # Composite PK with id
    league_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # API league ID
    game_class: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 11=Men, 21=Women
    name: Mapped[Optional[str]] = mapped_column(String(200))
    text: Mapped[Optional[str]] = mapped_column(String(200))
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)
    last_stats_update: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    club = relationship(
        "Club", back_populates="teams", foreign_keys="[Team.club_id, Team.season_id]"
    )
    season = relationship("Season", overlaps="club,clubs,leagues,teams")
    players = relationship("TeamPlayer", back_populates="team", cascade="all, delete-orphan")
    home_games = relationship(
        "Game",
        foreign_keys="Game.home_team_id",
        back_populates="home_team",
        overlaps="away_games,away_team",
    )
    away_games = relationship(
        "Game",
        foreign_keys="Game.away_team_id",
        back_populates="away_team",
        overlaps="home_games,home_team",
    )

    __table_args__ = (
        ForeignKeyConstraint(["club_id", "season_id"], ["clubs.id", "clubs.season_id"]),
        Index("idx_team_club", "club_id"),
        Index("idx_team_season", "season_id"),
        Index("idx_team_league", "league_id", "game_class"),
        Index("idx_team_name", "name"),
    )


class Player(Base):
    """Player entity - unique person across seasons"""

    __tablename__ = "players"

    person_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # API person_id
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(200))
    year_of_birth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # For search optimization
    name_normalized: Mapped[Optional[str]] = mapped_column(
        String(200)
    )  # Lowercase for case-insensitive search
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)
    api_failures: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    api_skip_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    height_cm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position_raw: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    license_raw: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    player_details_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    team_memberships = relationship(
        "TeamPlayer", back_populates="player", cascade="all, delete-orphan"
    )
    game_participations = relationship(
        "GamePlayer", back_populates="player", cascade="all, delete-orphan"
    )
    statistics = relationship(
        "PlayerStatistics", back_populates="player", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_player_name", "full_name"),
        Index("idx_player_name_normalized", "name_normalized"),
        Index("idx_player_last_name", "last_name"),
    )


class TeamPlayer(Base):
    """Association between players and teams (roster)"""

    __tablename__ = "team_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)  # Part of composite FK
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.person_id"), nullable=False)
    jersey_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # Forward, Defense, Goalie
    season_id: Mapped[int] = mapped_column(Integer, ForeignKey("seasons.id"), nullable=False)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    team = relationship(
        "Team", back_populates="players", foreign_keys="[TeamPlayer.team_id, TeamPlayer.season_id]"
    )
    player = relationship("Player", back_populates="team_memberships")
    season = relationship("Season", overlaps="clubs,leagues,players,team")

    __table_args__ = (
        ForeignKeyConstraint(["team_id", "season_id"], ["teams.id", "teams.season_id"]),
        Index("idx_teamplayer_team", "team_id"),
        Index("idx_teamplayer_player", "player_id"),
        Index("idx_teamplayer_unique", "team_id", "player_id", "season_id", unique=True),
    )


class Game(Base):
    """Game entity - belongs to group/league"""

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # API game ID
    group_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("league_groups.id"), nullable=True
    )
    season_id: Mapped[int] = mapped_column(Integer, ForeignKey("seasons.id"), nullable=False)
    home_team_id: Mapped[int] = mapped_column(Integer, nullable=False)  # Part of composite FK
    away_team_id: Mapped[int] = mapped_column(Integer, nullable=False)  # Part of composite FK
    game_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    game_time: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # scheduled, live, finished
    home_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    away_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    period: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    spectators: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    referee_1: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    referee_2: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)
    last_events_update: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completeness_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="upcoming", server_default="upcoming"
    )
    incomplete_fields: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    give_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completeness_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    group = relationship("LeagueGroup", back_populates="games")
    season = relationship("Season", overlaps="clubs,leagues")
    home_team = relationship(
        "Team",
        foreign_keys=[home_team_id, season_id],
        back_populates="home_games",
        overlaps="away_games,away_team,season",
    )
    away_team = relationship(
        "Team",
        foreign_keys=[away_team_id, season_id],
        back_populates="away_games",
        overlaps="home_games,home_team,season",
    )
    players = relationship("GamePlayer", back_populates="game", cascade="all, delete-orphan")
    events = relationship("GameEvent", back_populates="game", cascade="all, delete-orphan")

    __table_args__ = (
        ForeignKeyConstraint(["home_team_id", "season_id"], ["teams.id", "teams.season_id"]),
        ForeignKeyConstraint(["away_team_id", "season_id"], ["teams.id", "teams.season_id"]),
        Index("idx_game_season", "season_id"),
        Index("idx_game_teams", "home_team_id", "away_team_id"),
        Index("idx_game_date", "game_date"),
        Index("idx_game_status", "status"),
        Index("idx_game_completeness_status", "completeness_status"),
    )


class GameSyncFailure(Base):
    __tablename__ = "game_sync_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    season_id: Mapped[int] = mapped_column(Integer, nullable=False)
    abandoned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    missing_fields: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    can_retry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retried_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class UnresolvedPlayerEvent(Base):
    """Player name from GameEvent that could not be matched to a GamePlayer row."""

    __tablename__ = "unresolved_player_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    season_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("seasons.id"), nullable=True
    )
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["team_id", "season_id"], ["teams.id", "teams.season_id"]),
        Index("idx_unresolved_game", "game_id"),
        Index("idx_unresolved_unresolved", "resolved_at"),
    )


class GamePlayer(Base):
    """Association between games and players (lineup)"""

    __tablename__ = "game_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.person_id"), nullable=False)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)  # Part of composite FK
    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seasons.id"), nullable=False
    )  # For composite FK to team
    is_home_team: Mapped[bool] = mapped_column(Boolean, nullable=False)
    jersey_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    goals: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    assists: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    penalty_minutes: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    game = relationship("Game", back_populates="players")
    player = relationship("Player", back_populates="game_participations")
    team = relationship(
        "Team",
        foreign_keys="[GamePlayer.team_id, GamePlayer.season_id]",
        overlaps="away_games,away_team,home_games,home_team,season",
    )
    season = relationship("Season", overlaps="game,players,team")

    __table_args__ = (
        ForeignKeyConstraint(["team_id", "season_id"], ["teams.id", "teams.season_id"]),
        Index("idx_gameplayer_game", "game_id"),
        Index("idx_gameplayer_player", "player_id"),
        Index("idx_gameplayer_unique", "game_id", "player_id", unique=True),
    )


class GameEvent(Base):
    """Game event entity (goals, penalties, etc.)"""

    __tablename__ = "game_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # goal, penalty, timeout, etc.
    period: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    time: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # Game time (e.g., "12:34")
    team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Part of composite FK
    season_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("seasons.id"), nullable=True
    )  # For composite FK to team
    player_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("players.person_id"), nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    game = relationship("Game", back_populates="events")
    team = relationship(
        "Team",
        foreign_keys="[GameEvent.team_id, GameEvent.season_id]",
        overlaps="away_games,away_team,home_games,home_team,season",
    )
    player = relationship("Player")
    season = relationship("Season", overlaps="game,events,team")

    __table_args__ = (
        ForeignKeyConstraint(["team_id", "season_id"], ["teams.id", "teams.season_id"]),
        Index("idx_event_game", "game_id"),
        # idx_event_player intentionally removed: player_id is always NULL (API
        # provides only player names, not IDs), so indexing it wasted space.
    )


class PlayerStatistics(Base):
    """Aggregated player statistics"""

    __tablename__ = "player_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.person_id"), nullable=False)
    season_id: Mapped[int] = mapped_column(Integer, ForeignKey("seasons.id"), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Part of composite FK
    team_name: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # Club/team name text from API
    league_abbrev: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # League abbreviation from API
    games_played: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    goals: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    assists: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    points: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    penalty_minutes: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    pen_2min: Mapped[Optional[int]] = mapped_column(
        Integer, default=0
    )  # count of 2-minute penalties
    pen_5min: Mapped[Optional[int]] = mapped_column(
        Integer, default=0
    )  # count of 5-minute penalties
    pen_10min: Mapped[Optional[int]] = mapped_column(
        Integer, default=0
    )  # count of 10-minute penalties
    pen_match: Mapped[Optional[int]] = mapped_column(Integer, default=0)  # count of match penalties
    plus_minus: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    game_class: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # Gender/age class (mirrors Team.game_class)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)
    computed_from_local: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    local_computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    player = relationship("Player", back_populates="statistics")
    season = relationship("Season", overlaps="player,statistics,clubs,leagues")
    team = relationship(
        "Team",
        foreign_keys="[PlayerStatistics.team_id, PlayerStatistics.season_id]",
        overlaps="away_games,away_team,home_games,home_team,season",
    )

    __table_args__ = (
        ForeignKeyConstraint(["team_id", "season_id"], ["teams.id", "teams.season_id"]),
        Index("idx_stats_player", "player_id"),
        Index("idx_stats_season", "season_id"),
        # Unique per player+season+league (league_abbrev is never NULL; team_id was
        # previously used but is always NULL which lets SQLite store duplicates).
        Index("idx_stats_unique", "player_id", "season_id", "league_abbrev", unique=True),
        # New: for league-level top-scorer queries (filter by season+league, sort by points)
        Index("idx_stats_season_league_points", "season_id", "league_abbrev", "points"),
        # New: for overall top-scorers aggregation (group by player within season)
        Index("idx_stats_season_player", "season_id", "player_id"),
    )


class SyncStatus(Base):
    """Track sync status for different data types"""

    __tablename__ = "sync_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # seasons, clubs, leagues, players, games
    entity_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )  # e.g., "season:2025"
    last_sync: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    sync_status: Mapped[Optional[str]] = mapped_column(
        String(50), default="pending"
    )  # pending, in_progress, completed, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    records_synced: Mapped[Optional[int]] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("idx_sync_entity", "entity_type", "entity_id"),
        Index("idx_sync_status", "sync_status"),
        Index("idx_sync_last", "last_sync"),
    )
