"""
Hierarchical Data Indexer
Fetches data from Swiss Unihockey API following the documented hierarchy:
SEASONS → CLUBS → TEAMS → PLAYERS
SEASONS → LEAGUES → GROUPS → GAMES → PLAYERS
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.models.db_models import (
    Season, Club, Team, Player, TeamPlayer, League, LeagueGroup,
    Game, GamePlayer, GameEvent, PlayerStatistics, SyncStatus
)
from app.services.swissunihockey import get_swissunihockey_client
from app.services.database import get_database_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# League tier mapping  (lower number = higher competitive level)
# Note: the API groups all A-level youth under league_id 13 (U14A/U16A/U18A/U21A),
# all B-level under 14, all C-level under 15 — sub-categories cannot be split further.
#
#   Tier 1 — NLA / L-UPL                         (league_id 1, 10, 24)
#   Tier 2 — + NLB, all A-level youth            (league_id 2, 13)
#   Tier 3 — + 1. Liga, all B-level youth        (league_id 3, 14)
#   Tier 4 — + 2. Liga, all C-level youth        (league_id 4, 15)
#   Tier 5 — + 3. Liga, U21 D                    (league_id 5, 16)
#   Tier 6 — + 4./5. Liga, Supercup, Test, Regional  (league_id 6, 7, 12, 23, 25)
# ---------------------------------------------------------------------------
LEAGUE_TIERS: dict[int, int] = {
    1:  1,   # Herren/Damen NLA (legacy name)
    10: 1,   # Herren/Damen SML (NLA, intermediate name)
    24: 1,   # Herren/Damen L-UPL (NLA, current name)
    2:  2,   # Herren/Damen NLB
    13: 2,   # A-level youth: U14A, U16A, U18A, U21A, Juniorinnen U21A/U17A
    3:  3,   # 1. Liga (Herren/Damen)
    14: 3,   # B-level youth: U14B, U16B, U18B, U21B, Juniorinnen U21B/U17B
    4:  4,   # 2. Liga (Herren/Damen)
    15: 4,   # C-level youth: U16C, U18C, U21C
    5:  5,   # 3. Liga (Herren/Damen)
    16: 5,   # U21 D
    6:  6,   # 4. Liga
    7:  6,   # 5. Liga
    12: 6,   # Regional (Junioren A–E, Juniorinnen A–D, Senioren)
    23: 6,   # Supercup
    25: 6,   # Test / Cup
}
# Default tier for unknown league_ids (7 = no filter / include everything)
_DEFAULT_TIER = 7

TIER_LABELS: dict[int, str] = {
    1: "Tier 1 — NLA/L-UPL only",
    2: "Tier 2 — + NLB, U21A/U18A/U16A",
    3: "Tier 3 — + 1. Liga, U21B/U18B/U16B",
    4: "Tier 4 — + 2. Liga, U21C/U18C/U16C",
    5: "Tier 5 — + 3. Liga, U21D",
    6: "Tier 6 — + 4./5. Liga, Regional, Cups",
    7: "All leagues (no tier filter)",
}


def league_tier(league_id: int) -> int:
    """Return the tier (1=top) for a given API league_id."""
    return LEAGUE_TIERS.get(league_id, _DEFAULT_TIER)


class DataIndexer:
    """Hierarchical data indexer for Swiss Unihockey stats"""
    
    def __init__(self):
        self.client = get_swissunihockey_client()
        self.db_service = get_database_service()

    def cleanup_stale_sync_status(self) -> int:
        """Reset any in_progress rows left over from a previous server process."""
        with self.db_service.session_scope() as session:
            stale = session.query(SyncStatus).filter(
                SyncStatus.sync_status == "in_progress"
            ).all()
            for row in stale:
                row.sync_status = "failed"
                row.error_message = "Server restarted while job was running"
            session.commit()
            return len(stale)

    # ==================== UTILITY METHODS ====================
    
    def _should_update(self, entity_type: str, entity_id: str, max_age_hours: int = 24) -> bool:
        """Check if an entity needs updating based on last sync time
        
        Args:
            entity_type: Type of entity (e.g., "season", "club")
            entity_id: ID of specific entity
            max_age_hours: Maximum age in hours before update needed
        
        Returns:
            True if update is needed
        """
        with self.db_service.session_scope() as session:
            sync = session.query(SyncStatus).filter(
                SyncStatus.entity_type == entity_type,
                SyncStatus.entity_id == entity_id
            ).first()
            
            if not sync:
                return True
            
            last = sync.last_sync
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - last
            return age > timedelta(hours=max_age_hours)
    
    def _mark_sync_start(self, session: Session, entity_type: str, entity_id: str):
        """Mark synchronization as started"""
        sync = session.query(SyncStatus).filter(
            SyncStatus.entity_type == entity_type,
            SyncStatus.entity_id == entity_id
        ).first()
        
        if not sync:
            sync = SyncStatus(
                entity_type=entity_type,
                entity_id=entity_id
            )
            session.add(sync)
        
        sync.last_sync = datetime.now(timezone.utc)
        sync.sync_status = "in_progress"
        sync.error_message = None
        session.commit()
    
    def _mark_sync_complete(self, session: Session, entity_type: str, entity_id: str, records_count: int = 0):
        """Mark synchronization as completed (upsert — creates the row if it doesn't exist).

        _mark_sync_start is the historic row creator, but several indexer methods
        (teams, players, game_events, …) never call _mark_sync_start, so calling
        the old update-only version silently wrote nothing.  This version always
        creates the row when missing so the scheduler's freshness check works.
        """
        sync = session.query(SyncStatus).filter(
            SyncStatus.entity_type == entity_type,
            SyncStatus.entity_id == entity_id
        ).first()

        if not sync:
            sync = SyncStatus(entity_type=entity_type, entity_id=entity_id)
            session.add(sync)

        sync.sync_status    = "completed"
        sync.records_synced = records_count
        sync.last_sync      = datetime.now(timezone.utc)
        session.commit()
    
    def bulk_already_indexed(self, entity_type: str, entity_ids: list[str],
                              max_age_hours: int = 720) -> set[str]:
        """Return the set of *entity_ids* that already have a fresh 'success'
        SyncStatus row, so the caller can skip re-indexing them.

        This replaces N individual _should_update() calls (each a DB query)
        with a single IN-based query.
        """
        if not entity_ids:
            return set()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        try:
            with self.db_service.session_scope() as session:
                rows = (
                    session.query(SyncStatus.entity_id)
                    .filter(
                        SyncStatus.entity_type == entity_type,
                        SyncStatus.entity_id.in_(entity_ids),
                        SyncStatus.sync_status == "success",
                        SyncStatus.last_sync > cutoff,
                    )
                    .all()
                )
            return {r[0] for r in rows}
        except Exception:
            return set()

    def _mark_sync_failed(self, session: Session, entity_type: str, entity_id: str, error: str):
        """Mark synchronization as failed.

        The session may already be in a rolled-back state (e.g. after a
        sqlite3.OperationalError: database is locked).  Roll it back first
        so we can issue a fresh query, and swallow any secondary errors so
        the original exception propagates cleanly.
        """
        try:
            session.rollback()          # clear PendingRollbackError state
            sync = session.query(SyncStatus).filter(
                SyncStatus.entity_type == entity_type,
                SyncStatus.entity_id == entity_id
            ).first()
            if sync:
                sync.sync_status = "failed"
                sync.error_message = error[:500] if error else error
                session.commit()
        except Exception:
            # Best-effort: if we still can't write, silently ignore so the
            # original exception is not masked.
            pass

    def record_season_sync(self, entity_type: str, season_id: int, records: int = 0):
        """Upsert a season-level sync_status sentinel row.

        The scheduler's _last_sync_for() queries sync_status for a row matching
        entity_type + entity_id LIKE '%{season}%'.  Several tasks (league_groups,
        games, game_events) write per-entity rows whose entity_id does NOT contain
        the season year, so _last_sync_for always returns None and the scheduler
        re-queues those jobs on every tick.

        Calling this method after a season-wide task completes writes:
            entity_type = <entity_type>
            entity_id   = "season:<season_id>"
            sync_status = "completed"
        which the scheduler will find on the next freshness check.
        """
        entity_id = f"season:{season_id}"
        try:
            with self.db_service.session_scope() as session:
                sync = session.query(SyncStatus).filter(
                    SyncStatus.entity_type == entity_type,
                    SyncStatus.entity_id   == entity_id,
                ).first()
                if not sync:
                    sync = SyncStatus(entity_type=entity_type, entity_id=entity_id)
                    session.add(sync)
                sync.sync_status    = "completed"
                sync.records_synced = records
                sync.last_sync      = datetime.now(timezone.utc)
                session.commit()
                logger.debug(
                    "record_season_sync: %s / %s = %d records",
                    entity_type, entity_id, records,
                )
        except Exception as exc:
            logger.warning("record_season_sync failed for %s season %s: %s", entity_type, season_id, exc)

    def _extract_table_data(self, api_response: Dict[str, Any]) -> List[Dict]:
        """Extract data from API table format: data.regions[0].rows"""
        if not isinstance(api_response, dict):
            return []
        
        data = api_response.get("data", {})
        if isinstance(data, dict) and "regions" in data:
            regions = data.get("regions", [])
            if regions and len(regions) > 0:
                rows = regions[0].get("rows", [])
                return rows if isinstance(rows, list) else []
        
        # Fallback to entries format
        return api_response.get("entries", [])
    
    # ==================== LEVEL 1: SEASONS ====================
    
    def index_seasons(self, force: bool = False) -> int:
        """Index all seasons from API
        
        Args:
            force: Force update even if recently synced
        
        Returns:
            Number of seasons indexed
        """
        if not force and not self._should_update("seasons", "all", max_age_hours=720):  # 30 days
            logger.info("Seasons recently synced, skipping")
            return 0
        
        logger.info("Indexing seasons...")
        
        with self.db_service.session_scope() as session:
            self._mark_sync_start(session, "seasons", "all")
            
            try:
                # Fetch seasons from API
                seasons_data = self.client.get_seasons()
                entries = seasons_data.get("entries", [])
                
                count = 0
                for entry in entries:
                    context = entry.get("set_in_context", {})
                    season_id = context.get("season")
                    
                    if not season_id:
                        continue
                    
                    # Check if season exists
                    season = session.query(Season).filter(Season.id == season_id).first()
                    
                    if not season:
                        season = Season(id=season_id)
                        # Only honour the API's highlight flag for brand-new seasons;
                        # existing seasons keep whatever the admin manually selected.
                        season.highlighted = entry.get("highlight", False)
                        session.add(season)
                    
                    season.text = entry.get("text", f"{season_id}/{season_id+1}")
                    season.last_updated = datetime.now(timezone.utc)
                    count += 1
                
                session.commit()
                self._mark_sync_complete(session, "seasons", "all", count)
                logger.info(f"✓ Indexed {count} seasons")
                return count
                
            except Exception as e:
                logger.error(f"Failed to index seasons: {e}", exc_info=True)
                self._mark_sync_failed(session, "seasons", "all", str(e))
                raise
    
    # ==================== LEVEL 2: CLUBS ====================
    
    def index_clubs(self, season_id: int, force: bool = False) -> int:
        """Index clubs for a specific season
        
        Args:
            season_id: Season ID to index clubs for
            force: Force update even if recently synced
        
        Returns:
            Number of clubs indexed
        """
        entity_id = f"season:{season_id}"
        if not force and not self._should_update("clubs", entity_id, max_age_hours=168):  # 7 days
            logger.debug(f"Clubs for season {season_id} recently synced, skipping")
            return 0
        
        logger.info(f"Indexing clubs for season {season_id}...")
        
        with self.db_service.session_scope() as session:
            self._mark_sync_start(session, "clubs", entity_id)
            
            try:
                # Fetch clubs from API
                clubs_data = self.client.get_clubs(season=season_id)
                entries = self._extract_table_data(clubs_data)
                
                count = 0
                for entry in entries:
                    # Club ID is in set_in_context
                    context = entry.get("set_in_context", {})
                    club_id = context.get("club_id")
                    if not club_id:
                        continue
                    
                    # Check if club exists for this season
                    club = session.query(Club).filter(
                        Club.id == club_id,
                        Club.season_id == season_id
                    ).first()
                    
                    if not club:
                        club = Club(id=club_id, season_id=season_id)
                        session.add(club)
                    
                    club.name = entry.get("text", "")
                    club.text = entry.get("text", "")
                    club.region = entry.get("region")
                    club.last_updated = datetime.now(timezone.utc)
                    count += 1
                
                session.commit()
                self._mark_sync_complete(session, "clubs", entity_id, count)
                logger.info(f"✓ Indexed {count} clubs for season {season_id}")
                return count
                
            except Exception as e:
                logger.error(f"Failed to index clubs for season {season_id}: {e}", exc_info=True)
                self._mark_sync_failed(session, "clubs", entity_id, str(e))
                return 0
    
    # ==================== LEVEL 3: TEAMS ====================
    
    def index_teams_for_club(self, club_id: int, season_id: int, force: bool = False) -> tuple[int, list[int]]:
        """Index teams for a specific club
        
        Args:
            club_id: Club ID
            season_id: Season ID
            force: Force update
        
        Returns:
            Tuple of (number of teams indexed, list of team IDs)
        """
        entity_id = f"club:{club_id}:season:{season_id}"
        if not force and not self._should_update("teams", entity_id, max_age_hours=72):  # 3 days
            return (0, [])
        
        logger.debug(f"Indexing teams for club {club_id}, season {season_id}...")
        
        team_ids = []
        with self.db_service.session_scope() as session:
            try:
                # Fetch teams from API (without mode parameter - it returns empty with mode="by_club")
                teams_data = self.client.get_teams(season=season_id, club=club_id)
                rows = self._extract_table_data(teams_data)
                
                count = 0
                for row in rows:
                    # Team ID is directly in the row
                    team_id = row.get("id")
                    if not team_id:
                        continue
                    
                    # Check if team exists for this season (composite PK: id + season_id)
                    team = session.query(Team).filter(
                        Team.id == team_id,
                        Team.season_id == season_id
                    ).first()
                    
                    if not team:
                        team = Team(id=team_id, club_id=club_id, season_id=season_id)
                        session.add(team)
                    # Do NOT overwrite club_id if team already exists - teams are shared
                    # across clubs in a season (league standings), first write wins
                    
                    # Extract team name from cells
                    cells = row.get("cells", [])
                    team_name = "Unknown Team"
                    if cells and len(cells) > 0:
                        first_cell = cells[0]
                        if isinstance(first_cell, dict):
                            text_value = first_cell.get("text", "Unknown Team")
                            # text_value might be a list like ['Chur Unihockey']
                            if isinstance(text_value, list) and text_value:
                                team_name = text_value[0]
                            else:
                                team_name = str(text_value) if text_value else "Unknown Team"
                    
                    team.name = team_name
                    team.text = team_name
                    team.last_updated = datetime.now(timezone.utc)
                    team_ids.append(team_id)
                    count += 1
                
                session.commit()
                self._mark_sync_complete(session, "teams", entity_id, count)
                return (count, team_ids)
                
            except Exception as e:
                logger.debug(f"Failed to index teams for club {club_id}: {e}")
                self._mark_sync_failed(session, "teams", entity_id, str(e))
                return (0, team_ids)
    
    # ==================== LEVEL 4: PLAYERS ====================
    
    def index_players_for_team(self, team_id: int, season_id: int, force: bool = False) -> int:
        """Index players for a specific team
        
        Args:
            team_id: Team ID
            season_id: Season ID
            force: Force update
        
        Returns:
            Number of players indexed
        """
        entity_id = f"team:{team_id}:season:{season_id}"
        if not force and not self._should_update("players", entity_id, max_age_hours=24):
            return 0
        
        logger.debug(f"Indexing players for team {team_id}...")
        
        with self.db_service.session_scope() as session:
            try:
                # Fetch players from API
                players_data = self.client.get_team_players(team_id)
                rows = self._extract_table_data(players_data)
                
                if not rows or (isinstance(rows, str) and rows == ""):
                    logger.debug(f"No players found for team {team_id}")
                    return 0
                
                count = 0
                for row in rows:
                    # Player ID is in cells[2].link.ids[0] (player name cell)
                    person_id = None
                    player_name = "Unknown Player"
                    
                    cells = row.get("cells", [])
                    if len(cells) >= 3:
                        # cells[2] usually contains player name with link to player detail
                        name_cell = cells[2]
                        if isinstance(name_cell, dict):
                            # Get player name
                            if "text" in name_cell and name_cell["text"]:
                                player_name = name_cell["text"][0] if isinstance(name_cell["text"], list) else name_cell["text"]
                            # Get player ID from link
                            if "link" in name_cell:
                                link = name_cell["link"]
                                if isinstance(link, dict) and "ids" in link and link["ids"]:
                                    person_id = link["ids"][0]
                    
                    if not person_id:
                        logger.debug(f"Could not extract person_id from row: {row}")
                        continue
                    
                    # Get or create player
                    player = session.query(Player).filter(Player.person_id == person_id).first()
                    
                    if not player:
                        player = Player(
                            person_id=person_id,
                            full_name=player_name,
                            name_normalized=player_name.lower()
                        )
                        session.add(player)
                    
                    player.last_updated = datetime.now(timezone.utc)
                    
                    # Create or update team roster entry
                    team_player = session.query(TeamPlayer).filter(
                        TeamPlayer.team_id == team_id,
                        TeamPlayer.player_id == person_id,
                        TeamPlayer.season_id == season_id
                    ).first()
                    
                    if not team_player:
                        team_player = TeamPlayer(
                            team_id=team_id,
                            player_id=person_id,
                            season_id=season_id
                        )
                        session.add(team_player)
                    
                    # Extract additional info from cells: [0]=jersey#, [1]=position
                    if len(cells) >= 1:
                        num_cell = cells[0]
                        num_txt = num_cell.get("text", "") if isinstance(num_cell, dict) else ""
                        if isinstance(num_txt, list): num_txt = num_txt[0] if num_txt else ""
                        try:
                            team_player.jersey_number = int(num_txt) if num_txt else None
                        except (ValueError, TypeError):
                            team_player.jersey_number = None
                    else:
                        team_player.jersey_number = row.get("number")
                    if len(cells) >= 2:
                        pos_cell = cells[1]
                        pos_txt = pos_cell.get("text", "") if isinstance(pos_cell, dict) else ""
                        if isinstance(pos_txt, list): pos_txt = pos_txt[0] if pos_txt else ""
                        team_player.position = pos_txt or None
                    else:
                        team_player.position = row.get("position")
                    team_player.last_updated = datetime.now(timezone.utc)
                    
                    count += 1
                
                session.commit()
                self._mark_sync_complete(session, "players", entity_id, count)
                logger.debug(f"✓ Indexed {count} players for team {team_id}")
                return count
                
            except Exception as e:
                logger.debug(f"Failed to index players for team {team_id}: {e}")
                self._mark_sync_failed(session, "players", entity_id, str(e))
                return 0
    
    # ------------------------------------------------------------------
    # Internal helper shared by both the single-player and full-season
    # stats indexing paths.
    # ------------------------------------------------------------------

    def _upsert_player_stats_from_api(
        self,
        person_id: int,
        season_id: int,
        season_label: str,
        session,
        staged: dict,
    ) -> int:
        """Fetch /api/players/:id/statistics and upsert matching rows.

        Uses the caller-supplied session so it can be embedded in a larger
        transaction (season loop) or a standalone one (single-player call).
        Returns the number of rows upserted for this player.

        Cell layout (0-indexed):
          0 – season text (e.g. "2025/26")
          1 – league name
          2 – club/team name
          3 – games played
          4 – goals
          5 – assists
          6 – points
          7 – 2-min penalties
          8 – 5-min penalties
          9 – 10-min penalties
         10 – match penalties
        """
        try:
            stats_data = self.client.get_player_stats(person_id)
        except Exception as exc:
            logger.debug("Could not fetch stats for player %s: %s", person_id, exc)
            return 0

        regions = stats_data.get("data", {}).get("regions", [])
        count = 0
        for region in regions:
            for row in region.get("rows", []):
                cells = row.get("cells", [])
                if len(cells) < 4:
                    continue

                def _txt(idx, _c=cells):
                    v = _c[idx].get("text") if len(_c) > idx else None
                    if isinstance(v, list):
                        v = v[0] if v else None
                    return (v or "").strip()

                def _int(idx, _c=cells):
                    try:
                        return int(_txt(idx, _c))
                    except (ValueError, TypeError):
                        return 0

                row_season = _txt(0)
                if season_label and row_season != season_label:
                    continue

                league_abbrev   = _txt(1)
                team_name_txt   = _txt(2)
                games_played    = _int(3)
                goals           = _int(4)
                assists         = _int(5)
                points          = _int(6)
                pen_2min        = _int(7)
                pen_5min        = _int(8)
                pen_10min       = _int(9)
                pen_match       = _int(10)
                penalty_minutes = pen_2min * 2 + pen_5min * 5 + pen_10min * 10
                now             = datetime.now(timezone.utc)
                key             = (person_id, season_id, league_abbrev)

                def _apply(obj):
                    obj.league_abbrev   = league_abbrev
                    obj.team_name       = team_name_txt
                    obj.games_played    = games_played
                    obj.goals           = goals
                    obj.assists         = assists
                    obj.points          = points
                    obj.penalty_minutes = penalty_minutes
                    obj.pen_2min        = pen_2min
                    obj.pen_5min        = pen_5min
                    obj.pen_10min       = pen_10min
                    obj.pen_match       = pen_match
                    obj.last_updated    = now

                if key in staged:
                    _apply(staged[key])
                    count += 1
                    continue

                with session.no_autoflush:
                    existing = (
                        session.query(PlayerStatistics)
                        .filter(
                            PlayerStatistics.player_id == person_id,
                            PlayerStatistics.season_id == season_id,
                            PlayerStatistics.league_abbrev == league_abbrev,
                        ).first()
                    )

                if existing:
                    _apply(existing)
                    staged[key] = existing
                else:
                    obj = PlayerStatistics(
                        player_id       = person_id,
                        season_id       = season_id,
                        league_abbrev   = league_abbrev,
                        team_name       = team_name_txt,
                        games_played    = games_played,
                        goals           = goals,
                        assists         = assists,
                        points          = points,
                        penalty_minutes = penalty_minutes,
                        pen_2min        = pen_2min,
                        pen_5min        = pen_5min,
                        pen_10min       = pen_10min,
                        pen_match       = pen_match,
                        last_updated    = now,
                    )
                    session.add(obj)
                    staged[key] = obj
                count += 1
        return count

    def index_player_stats_one(self, player_id: int, season_id: int, force: bool = False) -> int:
        """Index statistics for a single player in one season.

        Useful for targeted refreshes (e.g. after a game) without running the
        full season sweep.  Returns the number of stat rows upserted.
        """
        entity_id = f"player:{player_id}:{season_id}"
        if not force and not self._should_update("player_stats_one", entity_id, max_age_hours=1):
            return 0

        from app.models.db_models import Season as SeasonModel
        with self.db_service.session_scope() as session:
            season_row = session.get(SeasonModel, season_id)
            season_label = season_row.text if season_row and season_row.text else str(season_id)
            staged: dict[tuple, PlayerStatistics] = {}
            count = self._upsert_player_stats_from_api(player_id, season_id, season_label, session, staged)
            session.commit()
            if count:
                self._mark_sync_complete(session, "player_stats_one", entity_id, count)
        return count

    def index_player_stats_for_season(self, season_id: int, force: bool = False) -> int:
        """Index player statistics for every known player in a season."""
        entity_id = f"season:{season_id}"
        if not force and not self._should_update("player_stats", entity_id, max_age_hours=4):
            return 0

        logger.info("Indexing player stats for season %s...", season_id)

        with self.db_service.session_scope() as session:
            try:
                from app.models.db_models import Season as SeasonModel, GamePlayer as _GamePlayer
                season_row = session.get(SeasonModel, season_id)
                season_label = season_row.text if season_row and season_row.text else str(season_id)

                tp_ids = {
                    r[0] for r in
                    session.query(TeamPlayer.player_id)
                    .filter(TeamPlayer.season_id == season_id)
                    .distinct().all()
                }
                gp_ids = {
                    r[0] for r in
                    session.query(_GamePlayer.player_id)
                    .filter(_GamePlayer.season_id == season_id)
                    .distinct().all()
                }
                player_ids = list(tp_ids | gp_ids)

                if not player_ids:
                    logger.info("No players found for season %s", season_id)
                    return 0

                count = 0
                staged: dict[tuple, PlayerStatistics] = {}
                for person_id in player_ids:
                    count += self._upsert_player_stats_from_api(
                        person_id, season_id, season_label, session, staged
                    )

                session.commit()
                self._mark_sync_complete(session, "player_stats", entity_id, count)
                logger.info("✓ Indexed %d player stat rows for season %s", count, season_id)
                return count

            except Exception as e:
                logger.error("Failed to index player stats for season %s: %s", season_id, e, exc_info=True)
                self._mark_sync_failed(session, "player_stats", entity_id, str(e))
                return 0

    # ==================== LEAGUES PATH ====================

    def index_leagues(self, season_id: int, force: bool = False) -> int:
        """Index all leagues for a season (from the flat /api/leagues endpoint).

        The leagues endpoint does NOT accept a season parameter — it returns all
        leagues across all seasons.  We filter by comparing against known seasons
        pulled from the DB; since the API only returns current/recent leagues we
        store every entry and tag it with the requested season_id so it can be
        used as the anchor for group/game indexing.

        Returns:
            Number of new League rows inserted.
        """
        entity_id = f"season:{season_id}"
        if not force and not self._should_update("leagues", entity_id, max_age_hours=168):
            logger.debug(f"Leagues for season {season_id} recently synced, skipping")
            return 0

        logger.info(f"Indexing leagues for season {season_id}...")

        with self.db_service.session_scope() as session:
            self._mark_sync_start(session, "leagues", entity_id)
            try:
                leagues_data = self.client.get_leagues()
                entries = leagues_data.get("entries", [])

                count = 0
                for entry in entries:
                    context = entry.get("set_in_context", {})
                    league_id = context.get("league")
                    game_class = context.get("game_class")
                    if not league_id or not game_class:
                        continue

                    league = session.query(League).filter(
                        League.season_id == season_id,
                        League.league_id == league_id,
                        League.game_class == game_class
                    ).first()

                    if not league:
                        league = League(
                            season_id=season_id,
                            league_id=league_id,
                            game_class=game_class,
                        )
                        session.add(league)

                    league.name = entry.get("text", "")
                    league.text = entry.get("text", "")
                    league.mode = context.get("mode")
                    league.last_updated = datetime.now(timezone.utc)
                    count += 1

                session.commit()
                self._mark_sync_complete(session, "leagues", entity_id, count)
                logger.info(f"✓ Indexed {count} leagues for season {season_id}")
                return count

            except Exception as e:
                logger.error(f"Failed to index leagues for season {season_id}: {e}", exc_info=True)
                self._mark_sync_failed(session, "leagues", entity_id, str(e))
                return 0

    def index_groups_for_league(self, league_db_id: int, season_id: int,
                                 league_id: int, game_class: int,
                                 force: bool = False) -> int:
        """Index groups (divisions) for a league.

        Returns:
            Number of new LeagueGroup rows inserted.
        """
        entity_id = f"league:{league_db_id}"
        if not force and not self._should_update("groups", entity_id, max_age_hours=24):
            return 0

        logger.debug(f"Indexing groups for league {league_id} game_class {game_class} season {season_id}")

        with self.db_service.session_scope() as session:
            try:
                groups_data = self.client.get_groups(
                    season=season_id, league=league_id, game_class=game_class
                )
                entries = groups_data.get("entries", [])
                count = 0
                for entry in entries:
                    ctx = entry.get("set_in_context", {})
                    group_name = entry.get("text", "") or ctx.get("group", "")
                    # Use a stable integer key: hash the string group name
                    # (the API doesn't give a numeric group ID directly)
                    group_key = abs(hash(f"{league_db_id}:{group_name}")) % (10 ** 9)

                    grp = session.query(LeagueGroup).filter(
                        LeagueGroup.league_id == league_db_id,
                        LeagueGroup.group_id == group_key
                    ).first()

                    if not grp:
                        grp = LeagueGroup(
                            league_id=league_db_id,
                            group_id=group_key,
                            name=group_name,
                            text=group_name,
                        )
                        session.add(grp)
                    else:
                        grp.name = group_name
                        grp.text = group_name
                    grp.last_updated = datetime.now(timezone.utc)
                    count += 1

                session.commit()
                logger.debug(f"✓ Indexed {count} groups for league {league_id}")
                return count

            except Exception as e:
                logger.error(f"Failed to index groups for league {league_id}: {e}", exc_info=True)
                return 0

    def index_games_for_league(self, league_db_id: int, season_id: int,
                                league_id: int, game_class: int,
                                group_name: str = None, group_db_id: int = None,
                                force: bool = False) -> int:
        """Index all games for a league/game_class/season/group combination.

        Parses the table-format response from /api/games?mode=list.
        Columns (0-indexed):
          0 – date/time  (link → game_id)
          1 – venue
          2 – home team name  (link → home_team_id)
          3 – home team logo  (empty text, link → home_team_id)
          4 – separator  (text: "-")
          5 – away team logo  (empty text, link → away_team_id)
          6 – away team name  (link → away_team_id)
          7 – score/result  (text: "3:2" or "3:2 n.V.", "-" / empty if not played)
          8 – broadcast icon

        Args:
            group_name: The group text string (e.g. "Gruppe 1") used as the
                        ``group`` query parameter so the API filters to that
                        specific division. When None the API returns only the
                        next ~10 upcoming games regardless of group.
            group_db_id: The primary-key of the matching LeagueGroup row to use
                         as the FK on every Game row inserted.

        Returns:
            Number of new/updated Game rows.
        """
        group_tag = f":{group_name}" if group_name else ""
        entity_id = f"games:league:{league_db_id}{group_tag}"
        if not force and not self._should_update("games", entity_id, max_age_hours=1):
            return 0

        logger.info(
            f"Indexing games for league {league_id} game_class {game_class} "
            f"season {season_id} group={group_name!r}"
        )

        with self.db_service.session_scope() as session:
            try:
                base_kwargs: dict = dict(season=season_id, league=league_id, game_class=game_class, mode="list")
                if group_name:
                    base_kwargs["group"] = group_name

                # Walk slider pages in both directions to collect all rounds:
                # - backwards (latest → first) via slider.prev
                # - forwards  (latest → last)  via slider.next (captures future rounds)
                count = 0
                visited_rounds: set = set()
                round_id = None  # None = start from the latest (current) round
                forward_start_round = None  # will be set from first response's next link

                while True:
                    call_kwargs = {**base_kwargs}
                    if round_id is not None:
                        call_kwargs["round"] = round_id

                    games_data = self.client.get_games(**call_kwargs)
                    d = games_data.get("data", {})
                    slider = d.get("slider", {})

                    # On the very first call, capture the forward starting point
                    if round_id is None and forward_start_round is None:
                        forward_start_round = (slider.get("next") or {}).get("set_in_context", {}).get("round")
                    regions = d.get("regions", [])

                    for region in regions:
                        for row in region.get("rows", []):
                            cells = row.get("cells", [])
                            if not cells:
                                continue

                            # --- game_id ---
                            game_id = None
                            date_cell = cells[0] if len(cells) > 0 else {}
                            link = date_cell.get("link", {})
                            if link.get("ids"):
                                game_id = link["ids"][0]
                            if not game_id:
                                continue

                            # --- date/time ---
                            date_text = ""
                            if date_cell.get("text"):
                                date_text = date_cell["text"][0] if isinstance(date_cell["text"], list) else date_cell["text"]

                            game_date = None
                            game_time_str = None
                            if date_text:
                                try:
                                    game_date = datetime.strptime(date_text.strip(), "%d.%m.%Y %H:%M")
                                    game_time_str = game_date.strftime("%H:%M")
                                except ValueError:
                                    pass

                            # --- venue ---
                            venue = None
                            if len(cells) > 1:
                                v = cells[1].get("text", [])
                                venue = (v[0] if isinstance(v, list) else v) or None

                            # --- home team ---
                            home_team_id = None
                            home_team_name = None
                            if len(cells) > 2:
                                hl = cells[2].get("link", {})
                                if hl.get("ids"):
                                    home_team_id = hl["ids"][0]
                                t = cells[2].get("text", [])
                                home_team_name = (t[0] if isinstance(t, list) else t) or None

                            # --- away team ---
                            away_team_id = None
                            away_team_name = None
                            if len(cells) > 6:
                                al = cells[6].get("link", {})
                                if al.get("ids"):
                                    away_team_id = al["ids"][0]
                                t = cells[6].get("text", [])
                                away_team_name = (t[0] if isinstance(t, list) else t) or None
                            elif len(cells) > 5:
                                # fallback: some rows have logo at 5, team at 6
                                al = cells[5].get("link", {})
                                if al.get("ids"):
                                    away_team_id = al["ids"][0]
                                t = cells[5].get("text", [])
                                away_team_name = (t[0] if isinstance(t, list) else t) or None

                            if not home_team_id or not away_team_id:
                                continue

                            # --- score / status ---
                            home_score = None
                            away_score = None
                            status = "scheduled"
                            period = None
                            # Score is at cell[7] ("Resultat" column);
                            # cell[4] is just the "-" separator between logos.
                            if len(cells) > 7:
                                score_text = cells[7].get("text", ["-"])
                                score_text = score_text[0] if isinstance(score_text, list) else score_text
                                if score_text and score_text not in ("-", ""):
                                    import re as _re
                                    # Handles "3:2", "3:2 n.V." (OT), "3:2 n.P." (SO)
                                    _m = _re.match(r'(\d+)\s*:\s*(\d+)\s*(n\.V\.|n\.P\.)?', score_text.strip(), _re.I)
                                    if _m:
                                        home_score = int(_m.group(1))
                                        away_score = int(_m.group(2))
                                        _sfx = (_m.group(3) or "").upper()
                                        period = "SO" if "P" in _sfx else ("OT" if "V" in _sfx else None)
                                        status = "finished"

                            # Ensure teams exist (create stubs if not in our DB)
                            # and update names when available from the game row
                            team_name_map = {
                                home_team_id: home_team_name,
                                away_team_id: away_team_name,
                            }
                            for tid in (home_team_id, away_team_id):
                                from app.models.db_models import Team
                                tname = team_name_map.get(tid)
                                existing = session.get(Team, (tid, season_id))
                                if not existing:
                                    stub = Team(
                                        id=tid,
                                        season_id=season_id,
                                        league_id=league_id,
                                        game_class=game_class,
                                        name=tname,
                                        text=tname,
                                    )
                                    session.add(stub)
                                    try:
                                        session.flush()
                                    except Exception:
                                        session.rollback()
                                elif tname and not existing.name:
                                    # Backfill name on existing nameless stub
                                    existing.name = tname
                                    existing.text = tname

                            # Upsert game
                            game = session.get(Game, game_id)
                            if not game:
                                game = Game(
                                    id=game_id,
                                    season_id=season_id,
                                    group_id=group_db_id,
                                    home_team_id=home_team_id,
                                    away_team_id=away_team_id,
                                )
                                session.add(game)
                                try:
                                    session.flush()
                                except IntegrityError:
                                    # Another concurrent job beat us to this game_id
                                    session.rollback()
                                    game = session.get(Game, game_id)
                                    if not game:
                                        continue  # can't proceed without the row

                            game.game_date = game_date
                            game.game_time = game_time_str
                            game.venue = venue
                            # Only overwrite score/status when the API returned a real
                            # result; never clobber an existing stored score with None
                            # (this prevents re-indexing from wiping completed games).
                            if home_score is not None:
                                game.home_score = home_score
                                game.away_score = away_score
                                game.status = status
                                if period:
                                    game.period = period
                            elif game.status != "finished":
                                game.status = status
                            game.last_updated = datetime.now(timezone.utc)
                            count += 1

                    # Advance to the previous round via the slider
                    visited_rounds.add(round_id)
                    prev_round = (slider.get("prev") or {}).get("set_in_context", {}).get("round")
                    if prev_round is None or prev_round in visited_rounds:
                        break  # reached the first round (no more prev)
                    round_id = prev_round

                # Now walk forward from the initial "next" to pick up future rounds
                round_id = forward_start_round
                while round_id and round_id not in visited_rounds:
                    call_kwargs = {**base_kwargs, "round": round_id}
                    games_data = self.client.get_games(**call_kwargs)
                    d = games_data.get("data", {})
                    slider = d.get("slider", {})
                    regions = d.get("regions", [])

                    for region in regions:
                        for row in region.get("rows", []):
                            cells = row.get("cells", [])
                            if not cells:
                                continue

                            game_id = None
                            date_cell = cells[0] if len(cells) > 0 else {}
                            link = date_cell.get("link", {})
                            if link.get("ids"):
                                game_id = link["ids"][0]
                            if not game_id:
                                continue

                            # Parse date/time, venue, teams, score — reuse same logic
                            # For future games score will be None (scheduled)
                            game_date, game_time_str, venue = None, None, None
                            date_texts = date_cell.get("text", [])
                            date_text = date_texts[0] if isinstance(date_texts, list) else date_texts
                            if date_text:
                                from datetime import datetime as _dt
                                for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%y %H:%M"):
                                    try:
                                        parsed = _dt.strptime(date_text.strip(), fmt)
                                        game_date = parsed
                                        game_time_str = parsed.strftime("%H:%M")
                                        break
                                    except ValueError:
                                        pass

                            if len(cells) > 1:
                                v = cells[1].get("text", "")
                                venue = (v[0] if isinstance(v, list) else v) or None

                            home_team_id, away_team_id = None, None
                            home_team_name, away_team_name = None, None
                            if len(cells) > 2:
                                hl = cells[2].get("link", {})
                                if hl.get("ids"):
                                    home_team_id = hl["ids"][0]
                                t = cells[2].get("text", [])
                                home_team_name = (t[0] if isinstance(t, list) else t) or None
                            if len(cells) > 6:
                                al = cells[6].get("link", {})
                                if al.get("ids"):
                                    away_team_id = al["ids"][0]
                                t = cells[6].get("text", [])
                                away_team_name = (t[0] if isinstance(t, list) else t) or None

                            if not home_team_id or not away_team_id:
                                continue

                            home_score, away_score, status, period = None, None, "scheduled", None
                            if len(cells) > 7:
                                score_text = cells[7].get("text", ["-"])
                                score_text = score_text[0] if isinstance(score_text, list) else score_text
                                if score_text and score_text != "-":
                                    import re as _re
                                    # Handles "3:2", "3:2 n.V." (OT), "3:2 n.P." (SO)
                                    _m = _re.match(r'(\d+)\s*:\s*(\d+)\s*(n\.V\.|n\.P\.)?', score_text.strip(), _re.I)
                                    if _m:
                                        home_score = int(_m.group(1))
                                        away_score = int(_m.group(2))
                                        _sfx = (_m.group(3) or "").upper()
                                        period = "SO" if "P" in _sfx else ("OT" if "V" in _sfx else None)
                                        status = "finished"

                            for tid in (home_team_id, away_team_id):
                                from app.models.db_models import Team
                                tname = {home_team_id: home_team_name, away_team_id: away_team_name}.get(tid)
                                existing = session.get(Team, (tid, season_id))
                                if not existing:
                                    stub = Team(id=tid, season_id=season_id, league_id=league_id,
                                                game_class=game_class, name=tname, text=tname)
                                    session.add(stub)
                                    try:
                                        session.flush()
                                    except Exception:
                                        session.rollback()
                                else:
                                    # Backfill name if missing
                                    if tname and not existing.name:
                                        existing.name = tname
                                        existing.text = tname
                                    # Backfill league_id / game_class if not yet set
                                    # (teams indexed via clubs path never get these)
                                    if not existing.league_id:
                                        existing.league_id = league_id
                                    if not existing.game_class:
                                        existing.game_class = game_class

                            game = session.get(Game, game_id)
                            if not game:
                                game = Game(id=game_id, season_id=season_id, group_id=group_db_id,
                                            home_team_id=home_team_id, away_team_id=away_team_id)
                                session.add(game)
                                try:
                                    session.flush()
                                except IntegrityError:
                                    session.rollback()
                                    game = session.get(Game, game_id)
                                    if not game:
                                        continue

                            game.game_date = game_date
                            game.game_time = game_time_str
                            game.venue = venue
                            if home_score is not None:
                                game.home_score = home_score
                                game.away_score = away_score
                                game.status = status
                                if period:
                                    game.period = period
                            elif game.status != "finished":
                                game.status = status
                            game.last_updated = datetime.now(timezone.utc)
                            count += 1

                    visited_rounds.add(round_id)
                    next_round = (slider.get("next") or {}).get("set_in_context", {}).get("round")
                    if not next_round or next_round in visited_rounds:
                        break
                    round_id = next_round

                session.commit()
                self._mark_sync_complete(session, "games", entity_id, count)
                logger.info(
                    f"✓ Indexed {count} games for league {league_id} "
                    f"group={group_name!r} ({len(visited_rounds)} rounds)"
                )
                return count

            except Exception as e:
                logger.error(f"Failed to index games for league {league_id}: {e}", exc_info=True)
                self._mark_sync_failed(session, "games", entity_id, str(e))
                return 0

    def index_game_events(self, game_id: int, season_id: int,
                          force: bool = False) -> int:
        """Fetch and store events (goals, penalties) for a single finished game.

        API calls are made *before* the DB session is opened so that the
        write lock is held for the minimum possible time.

        Returns:
            Number of events stored.
        """
        entity_id = f"game:{game_id}:events"
        if not force and not self._should_update("game_events", entity_id, max_age_hours=720):
            return 0

        # ── 1. Fetch from API (no DB lock held) ───────────────────────────
        try:
            events_data = self.client.get_game_events_by_id(game_id)
        except Exception as e:
            logger.debug(f"Failed to fetch events for game {game_id}: {e}")
            return 0

        rows = self._extract_table_data(events_data)
        if not rows:
            rows = events_data.get("data", {}).get("regions", [{}])[0].get("rows", []) if events_data.get("data") else []

        # Try to get score + confirm finished via summary title
        # Title format: "Team A - Team B 3:2 (1:0, 2:2, 0:0)"
        game_is_finished = False
        home_score_val = None
        away_score_val = None
        try:
            summary = self.client.get_game_summary(game_id)
            title = summary.get("data", {}).get("title", "") or ""
            import re as _re
            m = _re.search(r'(\d+):(\d+)', title)
            if m:
                home_score_val = int(m.group(1))
                away_score_val = int(m.group(2))
                game_is_finished = True
        except Exception:
            pass

        # ── 2. Parse / deduplicate (pure CPU, no I/O) ─────────────────────
        # Columns from /api/game_events/{id}:
        #   0 – clock time ("32:16", "")
        #   1 – event type text ("Torschütze", "Strafe", …)
        #   2 – team name
        #   3 – player name / note
        SKIP_EVENTS = {"spielende", "spielbeginn", "beginn", "ende", ""}
        raw_events: list[dict] = []
        for row in rows:
            cells = row.get("cells", [])
            if not cells:
                continue

            def _txt(cell):
                v = cell.get("text", "")
                return (v[0] if isinstance(v, list) and v else (v if not isinstance(v, list) else "")) or ""

            time_str    = _txt(cells[0]) if len(cells) > 0 else None
            event_type  = _txt(cells[1]) if len(cells) > 1 else "unknown"
            team_name   = _txt(cells[2]) if len(cells) > 2 else None
            player_name = _txt(cells[3]) if len(cells) > 3 else None

            if event_type.lower() in SKIP_EVENTS:
                continue

            raw_events.append({
                "event_type": event_type,
                "time": time_str,
                "team": team_name,
                "player": player_name,
            })

        # Goals: API emits 2 rows per assisted goal (scorer-only, then
        # scorer+assist). Merge by (time, team), keeping the richer player.
        # Penalties: API emits 2 identical rows — keep only one.
        deduped: list[dict] = []
        seen_pen: set[tuple] = set()
        for ev in raw_events:
            etype_lo = ev["event_type"].lower()
            is_goal    = etype_lo.startswith(("torschütze", "eigentor"))
            is_penalty = "'-strafe" in etype_lo

            if is_penalty:
                key = (ev["event_type"], ev["time"], ev["team"])
                if key in seen_pen:
                    continue
                seen_pen.add(key)
                deduped.append(ev)
            elif is_goal:
                found = False
                for d in deduped:
                    if (d["time"] == ev["time"] and d["team"] == ev["team"]
                            and d["event_type"].lower().startswith(
                                ("torschütze", "eigentor"))):
                        if len(ev["player"] or "") > len(d["player"] or ""):
                            d["player"] = ev["player"]
                        found = True
                        break
                if not found:
                    deduped.append(ev)
            else:
                deduped.append(ev)

        # ── 3. Write to DB (short critical section, no network I/O) ───────
        with self.db_service.session_scope() as session:
            try:
                # Delete stale events so re-indexing is idempotent
                session.query(GameEvent).filter(GameEvent.game_id == game_id).delete()
                session.flush()

                # Update game status/score if we got a result
                if game_is_finished:
                    game_row = session.get(Game, game_id)
                    if game_row:
                        game_row.status = "finished"
                        game_row.home_score = home_score_val
                        game_row.away_score = away_score_val

                count = 0
                for ev in deduped:
                    evt = GameEvent(
                        game_id=game_id,
                        event_type=str(ev["event_type"])[:50],
                        period=None,
                        time=ev["time"] or None,
                        team_id=None,
                        season_id=None,
                        player_id=None,
                        raw_data=ev,
                        last_updated=datetime.now(timezone.utc),
                    )
                    session.add(evt)
                    count += 1

                session.commit()
                self._mark_sync_complete(session, "game_events", entity_id, count)
                return count

            except Exception as e:
                logger.debug(f"Failed to write events for game {game_id}: {e}")
                return 0

    def index_game_lineup(self, game_id: int, season_id: int,
                          force: bool = False) -> int:
        """Fetch and store home + away lineups for a single finished game.

        Both API calls are made *before* the DB session is opened so that
        the write lock is held for the minimum possible time.

        Returns number of GamePlayer rows inserted/updated.
        """
        entity_id = f"game:{game_id}:lineup"
        if not force and not self._should_update("game_lineup", entity_id, max_age_hours=720):
            return 0

        # ── 1. Fetch both lineups from API (no DB lock held) ──────────────
        # API: is_home=0 → HOME lineup, is_home=1 → AWAY lineup.
        lineup_raw: dict[int, dict] = {}
        for is_home_flag in (1, 0):
            try:
                lineup_raw[is_home_flag] = self.client.get_game_lineup(game_id, is_home_flag)
            except Exception:
                lineup_raw[is_home_flag] = {}

        # ── 2. Write to DB (short critical section, no network I/O) ───────
        with self.db_service.session_scope() as session:
            try:
                # Delete stale lineup so re-indexing is idempotent
                session.query(GamePlayer).filter(GamePlayer.game_id == game_id).delete()
                session.flush()

                game_row = session.get(Game, game_id)
                if game_row is None:
                    return 0
                home_team_id = game_row.home_team_id
                away_team_id = game_row.away_team_id

                # Pre-fetch valid FK sets to avoid IntegrityError on unknown players/teams
                from app.models.db_models import Player as _Player, Team as _Team
                valid_players: set[int] = {
                    r[0] for r in session.query(_Player.person_id).all()
                }
                valid_teams: set[tuple] = {
                    (r[0], r[1])
                    for r in session.query(_Team.id, _Team.season_id).all()
                }

                count = 0
                with session.no_autoflush:
                    for is_home_flag in (1, 0):
                        team_id = away_team_id if is_home_flag else home_team_id
                        resp = lineup_raw.get(is_home_flag, {})

                        regions = resp.get("data", {}).get("regions", [])
                        for region in regions:
                            for row in region.get("rows", []):
                                cells = row.get("cells", [])
                                if not cells:
                                    continue

                                def _txt(cell):
                                    v = cell.get("text", "")
                                    return (v[0] if isinstance(v, list) and v
                                            else (v if not isinstance(v, list) else "")) or ""

                                jersey_raw = _txt(cells[0]) if len(cells) > 0 else ""
                                position   = _txt(cells[1]) if len(cells) > 1 else None
                                player_raw = cells[2] if len(cells) > 2 else {}

                                # Extract player_id from link
                                player_id = None
                                link = player_raw.get("link", {})
                                if link:
                                    ids = link.get("ids", [])
                                    if ids:
                                        player_id = ids[0]

                                jersey = None
                                try:
                                    jersey = int(jersey_raw)
                                except (ValueError, TypeError):
                                    pass

                                if player_id is None:
                                    continue

                                # Auto-create a player stub if not yet in the table
                                if player_id not in valid_players:
                                    player_name = _txt(player_raw)
                                    parts = player_name.split(" ", 1)
                                    stub = _Player(
                                        person_id=player_id,
                                        first_name=parts[0] if parts else None,
                                        last_name=parts[1] if len(parts) > 1 else None,
                                        full_name=player_name or f"Player {player_id}",
                                        name_normalized=(player_name or "").lower(),
                                        last_updated=datetime.now(timezone.utc),
                                    )
                                    session.add(stub)
                                    valid_players.add(player_id)
                                    logger.debug(
                                        f"Lineup: created player stub {player_id} '{player_name}'"
                                    )

                                if (team_id, season_id) not in valid_teams:
                                    logger.debug(
                                        f"Lineup skip: team ({team_id},{season_id}) not in teams table"
                                    )
                                    continue

                                existing_gp = session.query(GamePlayer).filter_by(
                                    game_id=game_id, player_id=player_id
                                ).first()
                                if not existing_gp:
                                    gp = GamePlayer(
                                        game_id=game_id,
                                        player_id=player_id,
                                        team_id=team_id,
                                        season_id=season_id,
                                        is_home_team=not bool(is_home_flag),  # flag=0→home, flag=1→away
                                        jersey_number=jersey,
                                        position=str(position)[:50] if position else None,
                                        goals=0,
                                        assists=0,
                                        penalty_minutes=0,
                                        last_updated=datetime.now(timezone.utc),
                                    )
                                    session.add(gp)
                                    count += 1

                session.commit()
                self._mark_sync_complete(session, "game_lineup", entity_id, count)
                return count

            except Exception as e:
                logger.debug(f"Failed to write lineup for game {game_id}: {e}")
                return 0

    def backfill_team_names(self, season_id: int, force: bool = False) -> int:
        """Backfill Team.name for stub rows that have no name.

        Calls the rankings API for every league in the season and records
        the (team_id → name) mapping returned by the API into the local DB.

        Returns number of Team rows updated.
        """
        entity_id = f"backfill_team_names:{season_id}"
        if not force and not self._should_update("team_names", entity_id, max_age_hours=24):
            logger.debug(f"Team names for season {season_id} recently backfilled, skipping")
            return 0

        logger.info(f"Backfilling team names for season {season_id}...")
        updated = 0

        with self.db_service.session_scope() as session:
            leagues = session.query(League).filter(League.season_id == season_id).all()
            name_map: dict[int, str] = {}  # team_id → name (across all leagues)

            for lg in leagues:
                try:
                    data = self.client.get_rankings(
                        league=lg.league_id,
                        game_class=lg.game_class,
                        season=season_id,
                    )
                    regions = data.get("data", {}).get("regions", [])
                    for region in regions:
                        for row in region.get("rows", []):
                            row_data = row.get("data", {})
                            team_info = row_data.get("team", {})
                            tid = team_info.get("id")
                            tname = team_info.get("name")
                            if tid and tname:
                                name_map[tid] = tname
                except Exception as e:
                    logger.warning(f"Rankings fetch failed for league {lg.league_id}: {e}")

            logger.info(f"Resolved {len(name_map)} team names from rankings API")

            # Bulk-update all nameless Team stubs in this season
            for team_id, name in name_map.items():
                team = session.get(Team, (team_id, season_id))
                if team and not team.name:
                    team.name = name
                    team.text = name
                    updated += 1

            session.commit()
            self._mark_sync_complete(session, "team_names", entity_id, updated)
            logger.info(f"✓ Backfilled names for {updated} teams in season {season_id}")
            return updated

    def backfill_team_league_attrs(self, season_id: int) -> int:
        """Backfill Team.league_id and Team.game_class from existing game records.

        Teams indexed via the clubs path never have league_id / game_class set.
        This method resolves them using the game → group → league chain that was
        already stored during the leagues indexing pass.

        Returns number of Team rows updated.
        """
        logger.info(f"Backfilling team league attrs for season {season_id}...")
        updated = 0
        with self.db_service.session_scope() as session:
            # Build team_id → (league_id, game_class) from all games in the season
            rows = (
                session.query(
                    Game.home_team_id,
                    Game.away_team_id,
                    League.league_id,
                    League.game_class,
                )
                .join(LeagueGroup, Game.group_id == LeagueGroup.id)
                .join(League, LeagueGroup.league_id == League.id)
                .filter(Game.season_id == season_id)
                .all()
            )
            team_attrs: dict[int, tuple[int, int]] = {}
            for home_id, away_id, l_id, gc in rows:
                for tid in (home_id, away_id):
                    if tid and tid not in team_attrs:
                        team_attrs[tid] = (l_id, gc)

            for team_id, (l_id, gc) in team_attrs.items():
                team = session.get(Team, (team_id, season_id))
                if team and (not team.league_id or not team.game_class):
                    if not team.league_id:
                        team.league_id = l_id
                    if not team.game_class:
                        team.game_class = gc
                    updated += 1

            session.commit()
        logger.info(f"✓ Backfilled league attrs for {updated} teams in season {season_id}")
        return updated

    def index_leagues_path(self, season_id: int = 2025,
                           index_games: bool = True,
                           index_events: bool = False,
                           force: bool = False) -> Dict[str, int]:
        """Full leagues → groups → games (→ events) indexing orchestration.

        Args:
            season_id:     Season to index.
            index_games:   Also fetch games for every league/group.
            index_events:  Also fetch game events for finished games (slow!).
            force:         Ignore existing sync timestamps.

        Returns:
            Dict with counts: leagues, groups, games, events.
        """
        stats: Dict[str, int] = {"leagues": 0, "groups": 0, "games": 0, "team_names": 0, "events": 0}

        logger.info(f"=== LEAGUES PATH starting for season {season_id} ===")

        # 1. Index leagues
        stats["leagues"] = self.index_leagues(season_id, force=force)

        # 2. Load league rows from DB
        with self.db_service.session_scope() as session:
            league_rows = [
                (lg.id, lg.league_id, lg.game_class)
                for lg in session.query(League).filter(League.season_id == season_id).all()
            ]

        logger.info(f"Processing {len(league_rows)} leagues...")

        for league_db_id, league_id, game_class in league_rows:
            # 3. Index groups
            g_count = self.index_groups_for_league(
                league_db_id, season_id, league_id, game_class, force=force
            )
            stats["groups"] += g_count

            if not index_games:
                continue

            # 4. Index games – one API call per group so all divisions are fetched
            with self.db_service.session_scope() as _gs:
                group_rows = [
                    (grp.id, grp.name)
                    for grp in _gs.query(LeagueGroup).filter(
                        LeagueGroup.league_id == league_db_id
                    ).all()
                ]
            # Fall back to a single ungrouped call if no groups were stored
            if not group_rows:
                group_rows = [(None, None)]
            for grp_db_id, grp_name in group_rows:
                gm_count = self.index_games_for_league(
                    league_db_id, season_id, league_id, game_class,
                    group_name=grp_name, group_db_id=grp_db_id,
                    force=force,
                )
                stats["games"] += gm_count

        # 5. Backfill team names from rankings API (fills stubs created during game indexing)
        if index_games:
            stats["team_names"] = self.backfill_team_names(season_id, force=force)
            # Also backfill league_id / game_class on teams that were indexed
            # via the clubs path (which never sets these fields)
            self.backfill_team_league_attrs(season_id)

        # 6. Optionally index events for past games (game_date < now, regardless of stored status)
        if index_events:
            now = datetime.now(timezone.utc)
            with self.db_service.session_scope() as session:
                past_ids = [
                    (g.id, g.season_id)
                    for g in session.query(Game).filter(
                        Game.season_id == season_id,
                        Game.game_date < now,
                    ).all()
                ]
            logger.info(f"Fetching events for {len(past_ids)} past games...")
            for game_id, sid in past_ids:
                stats["events"] += self.index_game_events(game_id, sid, force=force)

        logger.info(f"=== LEAGUES PATH complete === stats: {stats}")
        return stats

    # ==================== FULL INDEXING ORCHESTRATION ====================
    
    def index_current_season_clubs_path(self, season_id: int = 2025, max_clubs: int = None) -> Dict[str, int]:
        """Index current season following clubs → teams → players path
        
        Args:
            season_id: Season to index (default: 2025)
            max_clubs: Maximum number of clubs to process (for testing)
        
        Returns:
            Dict with counts of indexed entities
        """
        logger.info(f"=== Starting CLUBS PATH indexing for season {season_id} ===")
        
        stats = {
            "seasons": 0,
            "clubs": 0,
            "teams": 0,
            "players": 0
        }
        
        # 1. Ensure season exists
        stats["seasons"] = self.index_seasons()
        
        # 2. Index clubs for season (first time only)
        stats["clubs"] = self.index_clubs(season_id, force=False)
        
        # 3. Get list of club IDs (detached from session)
        with self.db_service.session_scope() as session:
            club_ids = [(c.id, c.name) for c in session.query(Club).filter(Club.season_id == season_id).all()]
        
        if max_clubs:
            club_ids = club_ids[:max_clubs]
        
        logger.info(f"Processing {len(club_ids)} clubs...")
        
        # 4. Process each club in separate sessions
        for i, (club_id, club_name) in enumerate(club_ids, 1):
            logger.info(f"[{i}/{len(club_ids)}] Processing club: {club_name} (ID: {club_id})")
            
            # Index teams for this club
            teams_count, team_ids = self.index_teams_for_club(club_id, season_id)
            stats["teams"] += teams_count
            
            # Index players for each team
            for team_id in team_ids:
                players_count = self.index_players_for_team(team_id, season_id)
                stats["players"] += players_count
        
        logger.info(f"=== CLUBS PATH indexing complete ===")
        logger.info(f"Stats: {stats}")
        return stats

    # ==================== PLAYER GAME STATS PATH ====================

    def index_player_game_stats(self, player_id: int, season_id: int, force: bool = False) -> int:
        """Update game_players.goals/assists/penalty_minutes for one player using
        GET /api/players/:id/overview (per-game breakdown).

        Overview cell layout (0-indexed):
          0 – date, 1 – location, 2 – status/time,
          3 – home team, 4 – away team, 5 – score,
          6 – goals (T), 7 – assists (A), 8 – points (P), 9 – penalty minutes (SM)

        Returns the number of game_players rows updated.
        """
        entity_id = f"player_game_stats:{player_id}:{season_id}"
        if not force and not self._should_update("player_game_stats", entity_id, max_age_hours=4):
            return 0

        try:
            data = self.client.get_player_overview(player_id, season=season_id)
            regions = data.get("data", {}).get("regions", [])
        except Exception as exc:
            logger.debug("Could not fetch overview for player %s: %s", player_id, exc)
            return 0

        # Build mapping: game_id -> (goals, assists, pim)
        game_stats: dict[int, tuple[int, int, int]] = {}
        for region in regions:
            for row in region.get("rows", []):
                row_id = row.get("id")
                if not row_id:
                    continue
                cells = row.get("cells", [])
                if len(cells) < 10:
                    continue

                def _txt(idx, _c=cells):
                    v = _c[idx].get("text") if len(_c) > idx else None
                    if isinstance(v, list):
                        v = v[0] if v else None
                    return (v or "").strip()

                # Skip rows where player did not play
                if _txt(6) in ("Nicht gespielt", ""):
                    continue

                def _int(idx, _c=cells):
                    try:
                        return int(_txt(idx, _c))
                    except (ValueError, TypeError):
                        return 0

                game_stats[row_id] = (_int(6), _int(7), _int(9))  # goals, assists, pim

        if not game_stats:
            return 0

        updated = 0
        with self.db_service.session_scope() as session:
            try:
                for game_id, (goals, assists, pim) in game_stats.items():
                    n = (
                        session.query(GamePlayer)
                        .filter(
                            GamePlayer.game_id == game_id,
                            GamePlayer.player_id == player_id,
                        )
                        .update({"goals": goals, "assists": assists, "penalty_minutes": pim})
                    )
                    updated += n or 0
                session.commit()
                if updated:
                    self._mark_sync_complete(session, "player_game_stats", entity_id, updated)
            except Exception as exc:
                logger.error("Failed updating game stats for player %s: %s", player_id, exc, exc_info=True)
        return updated

    def index_player_game_stats_for_season(self, season_id: int, force: bool = False) -> int:
        """Update game_players G/A/PIM for all known players in a season.

        Iterates every player active in the season (from team_players union
        game_players) and calls index_player_game_stats() for each.
        Returns total game_players rows updated.
        """
        entity_id = f"season_game_stats:{season_id}"
        if not force and not self._should_update("player_game_stats_season", entity_id, max_age_hours=4):
            return 0

        with self.db_service.session_scope() as session:
            tp_ids = {
                r[0] for r in
                session.query(TeamPlayer.player_id)
                .filter(TeamPlayer.season_id == season_id)
                .distinct().all()
            }
            gp_ids = {
                r[0] for r in
                session.query(GamePlayer.player_id)
                .filter(GamePlayer.season_id == season_id)
                .distinct().all()
            }
            player_ids = list(tp_ids | gp_ids)

        if not player_ids:
            logger.info("No players found for season %s", season_id)
            return 0

        logger.info("Updating per-game G/A/PIM for %d players in season %s...", len(player_ids), season_id)
        total = 0
        for pid in player_ids:
            n = self.index_player_game_stats(pid, season_id=season_id, force=force)
            total += n

        with self.db_service.session_scope() as session:
            self._mark_sync_complete(session, "player_game_stats_season", entity_id, total)
        logger.info("\u2713 Updated %d game_players rows with G/A/PIM for season %s", total, season_id)
        return total

    def get_indexing_stats(self) -> Dict[str, Any]:
        """Get current indexing statistics
        
        Returns:
            Dict with entity counts and sync status
        """
        with self.db_service.session_scope() as session:
            return {
                "seasons": session.query(func.count(Season.id)).scalar(),
                "clubs": session.query(Club).count(),  # Use count() for composite PK
                "teams": session.query(func.count(Team.id)).scalar(),
                "players": session.query(func.count(Player.person_id)).scalar(),
                "team_players": session.query(func.count(TeamPlayer.id)).scalar(),
                "leagues": session.query(func.count(League.id)).scalar(),
                "games": session.query(func.count(Game.id)).scalar(),
                "last_updated": datetime.now(timezone.utc).isoformat()
            }


# Global indexer instance
_indexer: DataIndexer = None


def get_data_indexer() -> DataIndexer:
    """Get the global data indexer instance"""
    global _indexer
    if _indexer is None:
        _indexer = DataIndexer()
    return _indexer
