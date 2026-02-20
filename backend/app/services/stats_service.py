"""
DB-backed stats service for Swiss Unihockey Stats frontend.

All functions query the local SQLite database (via SQLAlchemy) and return
plain Python dicts / lists ready to be passed to Jinja2 templates.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import case, func, or_

from app.models.db_models import (
    Game,
    GameEvent,
    GamePlayer,
    League,
    LeagueGroup,
    Player,
    PlayerStatistics,
    Season,
    Team,
    TeamPlayer,
)
from app.services.database import get_database_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_current_season_id(session) -> int:
    """Return the season id marked as highlighted (current), fallback to max."""
    row = session.query(Season).filter(Season.highlighted == True).first()  # noqa: E712
    if row:
        return row.id
    row = session.query(func.max(Season.id)).scalar()
    return row or 2025


# ---------------------------------------------------------------------------
# 1. Language-list helpers
# ---------------------------------------------------------------------------

def get_all_seasons() -> list[dict]:
    """Return all seasons ordered descending, with current flag."""
    db = get_database_service()
    with db.session_scope() as session:
        rows = session.query(Season).order_by(Season.id.desc()).all()
        current_id = _get_current_season_id(session)
        return [
            {"id": s.id, "name": s.text or str(s.id), "current": s.id == current_id}
            for s in rows
        ]


def get_seasons_with_teams() -> list[dict]:
    """Return only seasons that have at least one team indexed, ordered descending."""
    db = get_database_service()
    with db.session_scope() as session:
        current_id = _get_current_season_id(session)
        rows = (
            session.query(Season.id, Season.text, func.count(Team.id).label("tc"))
            .outerjoin(Team, Team.season_id == Season.id)
            .group_by(Season.id)
            .having(func.count(Team.id) > 0)
            .order_by(Season.id.desc())
            .all()
        )
        return [
            {"id": r.id, "name": r.text or str(r.id), "current": r.id == current_id}
            for r in rows
        ]


def get_leagues_from_db(season_id: Optional[int] = None) -> list[dict]:
    """Return all leagues for a season, grouped metadata for template use."""
    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        rows = (
            session.query(League)
            .filter(League.season_id == season_id)
            .order_by(League.game_class, League.name)
            .all()
        )

        result = []
        for lg in rows:
            result.append(
                {
                    "id": lg.id,
                    "league_id": lg.league_id,
                    "season_id": lg.season_id,
                    "game_class": lg.game_class,
                    "name": lg.name or lg.text or f"League {lg.league_id}",
                    "text": lg.text or lg.name or f"League {lg.league_id}",
                    "mode": lg.mode,
                    "group_count": len(lg.groups),
                }
            )
        return result


# Mapping from API game_class int to human-readable category label
_GAME_CLASS_LABEL = {11: "Men", 21: "Women"}


def _tier_order_expr():
    """Return a SQLAlchemy CASE expression that maps league names to a sort order (lower = higher tier)."""
    return case(
        (League.name.ilike("%NLA%"), 1),
        (League.name.ilike("%NLB%"), 2),
        (League.name.ilike("%L-UPL%"), 3),
        (League.name.ilike("%Supercup%"), 4),
        (League.name.ilike("%1. Liga%"), 5),
        (League.name.ilike("%2. Liga%"), 6),
        (League.name.ilike("%3. Liga%"), 7),
        (League.name.ilike("%4. Liga%"), 8),
        (League.name.ilike("%5. Liga%"), 9),
        (League.name.ilike("%Junioren A%"), 20),
        (League.name.ilike("%Juniorinnen A%"), 20),
        (League.name.ilike("%Junioren U21%"), 21),
        (League.name.ilike("%Juniorinnen U21%"), 21),
        (League.name.ilike("%Junioren B%"), 22),
        (League.name.ilike("%Juniorinnen B%"), 22),
        (League.name.ilike("%Junioren U18%"), 23),
        (League.name.ilike("%Juniorinnen U18%"), 23),
        (League.name.ilike("%Junioren C%"), 24),
        (League.name.ilike("%Juniorinnen C%"), 24),
        (League.name.ilike("%Junioren U16%"), 25),
        (League.name.ilike("%Juniorinnen U16%"), 25),
        (League.name.ilike("%Junioren U14%"), 26),
        (League.name.ilike("%Juniorinnen U14%"), 26),
        (League.name.ilike("%Junioren D%"), 27),
        (League.name.ilike("%Juniorinnen D%"), 27),
        (League.name.ilike("%Junioren E%"), 28),
        (League.name.ilike("%Juniorinnen E%"), 28),
        else_=50,
    )


def get_teams_list(
    season_id: Optional[int] = None,
    q: str = "",
    sort: str = "league",
    league_names: Optional[list] = None,
    limit: int = 200,
    all_seasons: bool = False,
) -> list[dict]:
    """Return teams from DB enriched with league name and category.

    sort: 'name' | 'league'
    league_names: list of league name prefixes (OR'd ilike); e.g. ['Herren NLB', 'Damen NLB']
    all_seasons: if True, return teams across all seasons that have data (includes season_name in results)
    """
    db = get_database_service()
    with db.session_scope() as session:
        if all_seasons:
            query = (
                session.query(Team, League, Season)
                .outerjoin(
                    League,
                    (Team.league_id == League.league_id)
                    & (Team.season_id == League.season_id)
                    & (Team.game_class == League.game_class),
                )
                .join(Season, Team.season_id == Season.id)
            )
        else:
            if season_id is None:
                season_id = _get_current_season_id(session)
            query = (
                session.query(Team, League, Season)
                .outerjoin(
                    League,
                    (Team.league_id == League.league_id)
                    & (Team.season_id == League.season_id)
                    & (Team.game_class == League.game_class),
                )
                .join(Season, Team.season_id == Season.id)
                .filter(Team.season_id == season_id)
            )

        # Multi-select league name filter — each value used as ilike prefix
        if league_names:
            query = query.filter(
                or_(*[League.name.ilike(f"{n}%") for n in league_names])
            )

        if q:
            query = query.filter(
                or_(Team.name.ilike(f"%{q}%"), League.name.ilike(f"%{q}%"))
            )

        if sort == "league":
            # Sort by tier level first, then season desc, then league name, then team name
            order = [_tier_order_expr(), func.coalesce(League.name, "~~~~"), Team.name]
            if all_seasons:
                order.insert(1, Season.id.desc())
            query = query.order_by(*order)
        else:
            order = [Team.name]
            if all_seasons:
                order.insert(0, Season.id.desc())
            query = query.order_by(*order)

        results = []
        for team, league, season_row in query.limit(limit).all():
            gc = team.game_class
            category = _GAME_CLASS_LABEL.get(gc, "Mixed" if gc else None)
            results.append(
                {
                    "id": team.id,
                    "text": team.text or team.name or "",
                    "category": category,
                    "league_name": (league.name or league.text) if league else None,
                    "season_name": (season_row.text or str(season_row.id)) if season_row else None,
                }
            )
        return results


def get_league_by_id(db_league_id: int) -> Optional[dict]:
    """Return a single league dict by its DB pk (leagues.id)."""
    db = get_database_service()
    with db.session_scope() as session:
        lg = session.query(League).filter(League.id == db_league_id).first()
        if lg is None:
            return None
        groups = [
            {"id": g.id, "group_id": g.group_id, "name": g.name or g.text}
            for g in lg.groups
        ]
        return {
            "id": lg.id,
            "league_id": lg.league_id,
            "season_id": lg.season_id,
            "game_class": lg.game_class,
            "name": lg.name or lg.text or f"League {lg.league_id}",
            "text": lg.text or lg.name or f"League {lg.league_id}",
            "mode": lg.mode,
            "groups": groups,
        }


# ---------------------------------------------------------------------------
# 2. League standings  (computed from games table)
# ---------------------------------------------------------------------------

def get_league_standings(db_league_id: int) -> list[dict]:
    """
    Compute standings from finished games in a league (all its groups).

    Points system: Win=3, OT/SO Win=2, OT/SO Loss=1, Regular Loss=0.
    We detect OT/SO by presence of "overtime" / "penalty" in home_score comment
    – since we do not have that info, we simply use W=3, L=0 (two-point system
    is fine as a first pass; refine later if OT flag is available).

    Returns list of dicts sorted by pts DESC, gd DESC, gf DESC.
    """
    db = get_database_service()
    with db.session_scope() as session:
        # Gather all group_ids for this league
        league = session.query(League).filter(League.id == db_league_id).first()
        if league is None:
            return []

        group_ids = [g.id for g in league.groups]
        if not group_ids:
            return []

        # All games that have a score
        games = (
            session.query(Game)
            .filter(
                Game.group_id.in_(group_ids),
                Game.home_score.isnot(None),
                Game.away_score.isnot(None),
            )
            .all()
        )

        if not games:
            return []

        # team_id → {name, gp, w, l, gf, ga, pts}
        table: dict[int, dict] = {}

        def _entry(team_id: int, team_name: str) -> dict:
            if team_id not in table:
                table[team_id] = {
                    "team_id": team_id,
                    "team_name": team_name,
                    "gp": 0,
                    "w": 0,
                    "l": 0,
                    "gf": 0,
                    "ga": 0,
                    "pts": 0,
                }
            return table[team_id]

        # Preload team names: first try same season, then any season, then API rankings
        team_ids = set()
        for g in games:
            team_ids.add(g.home_team_id)
            team_ids.add(g.away_team_id)

        team_names: dict[int, str] = {}
        # 1) same-season rows
        for t in session.query(Team).filter(
            Team.id.in_(team_ids),
            Team.season_id == league.season_id,
        ).all():
            if t.name or t.text:
                team_names[t.id] = t.name or t.text

        # 2) any season (for stubs that were created without a name)
        missing = team_ids - set(team_names)
        if missing:
            for t in session.query(Team).filter(
                Team.id.in_(missing),
                Team.name.isnot(None),
            ).all():
                team_names[t.id] = t.name

        # 3) live rankings API for anything still unresolved
        still_missing = team_ids - set(team_names)
        if still_missing:
            try:
                from app.services.swissunihockey import get_swissunihockey_client
                client = get_swissunihockey_client()
                data = client.get_rankings(
                    league=league.league_id,
                    game_class=league.game_class,
                    season=league.season_id,
                )
                for region in data.get("data", {}).get("regions", []):
                    for row in region.get("rows", []):
                        rd = row.get("data", {})
                        ti = rd.get("team", {})
                        tid, tname = ti.get("id"), ti.get("name")
                        if tid and tname and tid in still_missing:
                            team_names[tid] = tname
                            # Persist so we don't hit the API again
                            stub = session.get(Team, (tid, league.season_id))
                            if stub and not stub.name:
                                stub.name = tname
                                stub.text = tname
                session.commit()
            except Exception:
                pass

        for g in games:
            hs = g.home_score
            as_ = g.away_score
            h = _entry(g.home_team_id, team_names.get(g.home_team_id, f"Team {g.home_team_id}"))
            a = _entry(g.away_team_id, team_names.get(g.away_team_id, f"Team {g.away_team_id}"))

            h["gp"] += 1
            a["gp"] += 1
            h["gf"] += hs
            h["ga"] += as_
            a["gf"] += as_
            a["ga"] += hs

            if hs > as_:
                h["w"] += 1
                h["pts"] += 3
                a["l"] += 1
            elif as_ > hs:
                a["w"] += 1
                a["pts"] += 3
                h["l"] += 1
            else:
                # Tie – shouldn't happen in unihockey but handle it
                h["pts"] += 1
                a["pts"] += 1

        standings = sorted(
            table.values(),
            key=lambda x: (-x["pts"], -(x["gf"] - x["ga"]), -x["gf"]),
        )

        # Add rank and GD
        for i, row in enumerate(standings, 1):
            row["rank"] = i
            row["gd"] = row["gf"] - row["ga"]

        return standings


# ---------------------------------------------------------------------------
# 3. Top scorers per league
# ---------------------------------------------------------------------------

def get_league_top_scorers(db_league_id: int, limit: int = 20) -> list[dict]:
    """
    Top scorers for a league.

    Strategy: collect player IDs from TeamPlayer rows for teams that played in
    this league, then join PlayerStatistics + Player by player_id — avoids any
    fragile team-name string matching.
    """
    db = get_database_service()
    with db.session_scope() as session:
        league = session.query(League).filter(League.id == db_league_id).first()
        if league is None:
            return []

        # Teams that participate in any group of this league
        group_ids = [g.id for g in league.groups]
        if not group_ids:
            return []

        # Get team IDs that played in this league (from games)
        home_ids = {r[0] for r in session.query(Game.home_team_id).filter(Game.group_id.in_(group_ids)).all()}
        away_ids = {r[0] for r in session.query(Game.away_team_id).filter(Game.group_id.in_(group_ids)).all()}
        all_team_ids = list((home_ids | away_ids) - {None})

        if not all_team_ids:
            return []

        # Collect player IDs for those teams (from TeamPlayer roster entries)
        player_ids = [
            r[0] for r in
            session.query(TeamPlayer.player_id)
            .filter(TeamPlayer.team_id.in_(all_team_ids))
            .distinct()
            .all()
        ]

        if not player_ids:
            return []

        # Query PlayerStatistics + Player — restrict to team_id in this league so
        # players who also played in other leagues only show their stats for
        # the teams that actually participated here (one stat row per team).
        stats = (
            session.query(PlayerStatistics, Player)
            .join(Player, PlayerStatistics.player_id == Player.person_id)
            .filter(
                PlayerStatistics.player_id.in_(player_ids),
                PlayerStatistics.season_id == league.season_id,
                PlayerStatistics.team_id.in_(all_team_ids),
            )
            .order_by(
                PlayerStatistics.points.desc(),
                PlayerStatistics.goals.desc(),
            )
            .limit(limit)
            .all()
        )

        result = []
        for i, (ps, pl) in enumerate(stats, 1):
            result.append(
                {
                    "rank": i,
                    "player_id": pl.person_id,
                    "player_name": pl.full_name or f"Player {pl.person_id}",
                    "team_name": ps.team_name or "Unknown",
                    "team_id": ps.team_id,
                    "gp": ps.games_played,
                    "g": ps.goals,
                    "a": ps.assists,
                    "pts": ps.points,
                    "pim": ps.penalty_minutes,
                }
            )
        return result


def get_overall_top_scorers(season_id: Optional[int] = None, limit: int = 20) -> list[dict]:
    """
    Overall top scorers across all leagues in a season.
    
    Returns players with the highest points from PlayerStatistics,
    aggregating across all teams they played for in the season.
    Includes the league where they played most games.
    """
    from app.services.database import get_database_service
    from app.models.db_models import PlayerStatistics, Player
    from sqlalchemy import func
    
    if season_id is None:
        from app.main import get_current_season
        season_id = get_current_season()
    
    db = get_database_service()
    with db.session_scope() as session:
        # Aggregate stats per player across all teams
        stats = (
            session.query(
                PlayerStatistics.player_id,
                Player.full_name,
                func.sum(PlayerStatistics.games_played).label('gp'),
                func.sum(PlayerStatistics.goals).label('g'),
                func.sum(PlayerStatistics.assists).label('a'),
                func.sum(PlayerStatistics.points).label('pts'),
                func.sum(PlayerStatistics.penalty_minutes).label('pim')
            )
            .join(Player, PlayerStatistics.player_id == Player.person_id)
            .filter(PlayerStatistics.season_id == season_id)
            .group_by(PlayerStatistics.player_id, Player.full_name)
            .order_by(func.sum(PlayerStatistics.points).desc(), func.sum(PlayerStatistics.goals).desc())
            .limit(limit)
            .all()
        )
        
        result = []
        for i, (player_id, full_name, gp, g, a, pts, pim) in enumerate(stats, 1):
            # For each player, find the team/league where they played most games
            primary_stats = (
                session.query(
                    PlayerStatistics.team_name,
                    PlayerStatistics.team_id,
                    PlayerStatistics.league_abbrev,
                    PlayerStatistics.games_played
                )
                .filter(
                    PlayerStatistics.player_id == player_id,
                    PlayerStatistics.season_id == season_id
                )
                .order_by(PlayerStatistics.games_played.desc())
                .first()
            )
            
            if primary_stats:
                team_name, team_id, league_abbrev, _ = primary_stats
            else:
                team_name, team_id, league_abbrev = "Unknown", None, None
            
            result.append({
                "rank": i,
                "player_id": player_id,
                "player_name": full_name or f"Player {player_id}",
                "team_name": team_name or "Unknown",
                "team_id": team_id,
                "league": league_abbrev or "",
                "gp": gp or 0,
                "g": g or 0,
                "a": a or 0,
                "pts": pts or 0,
                "pim": pim or 0,
            })
        
        return result


# ---------------------------------------------------------------------------
# 4. Player stats leaderboard (all teams / season)
# ---------------------------------------------------------------------------

def get_player_leaderboard(
    season_id: Optional[int] = None,
    team_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    order_by: str = "points",
) -> dict:
    """
    Global player stats leaderboard for a season, optionally filtered by team.
    order_by: 'points' | 'goals' | 'assists' | 'pim'
    """
    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        q = (
            session.query(PlayerStatistics, Player, Team)
            .join(Player, PlayerStatistics.player_id == Player.person_id)
            .join(
                Team,
                (Team.id == PlayerStatistics.team_id)
                & (Team.season_id == PlayerStatistics.season_id),
                isouter=True,
            )
            .filter(PlayerStatistics.season_id == season_id)
        )

        if team_id is not None:
            q = q.filter(PlayerStatistics.team_id == team_id)

        order_col = {
            "goals": PlayerStatistics.goals,
            "assists": PlayerStatistics.assists,
            "pim": PlayerStatistics.penalty_minutes,
        }.get(order_by, PlayerStatistics.points)

        total = q.count()
        q = q.order_by(order_col.desc(), PlayerStatistics.goals.desc()).offset(offset).limit(limit)

        result = []
        for i, (ps, pl, tm) in enumerate(q.all(), offset + 1):
            result.append(
                {
                    "rank": i,
                    "player_id": pl.person_id,
                    "player_name": pl.full_name or f"Player {pl.person_id}",
                    "team_name": (tm.name if tm else None) or f"Team {ps.team_id}",
                    "team_id": ps.team_id,
                    "gp": ps.games_played,
                    "g": ps.goals,
                    "a": ps.assists,
                    "pts": ps.points,
                    "pim": ps.penalty_minutes,
                }
            )
        return {"players": result, "total": total, "offset": offset, "limit": limit}


# ---------------------------------------------------------------------------
# 5. Team page data
# ---------------------------------------------------------------------------

def get_team_detail(team_id: int, season_id: Optional[int] = None) -> dict:
    """
    Return dict with: team info, roster (with per-player stats), and recent games.
    Roster is built from official TeamPlayer index, enriched with game lineup data
    to fill missing jersey numbers / positions and add unlisted players.
    """
    _UNKNOWN_POS = {"nicht bekannt", ""}

    db = get_database_service()
    with db.session_scope() as session:
        # All seasons this team_id exists in (for the season selector)
        all_season_rows = (
            session.query(Team.season_id, Season.text, Season.highlighted)
            .join(Season, Team.season_id == Season.id)
            .filter(Team.id == team_id)
            .order_by(Team.season_id.desc())
            .all()
        )
        available_seasons = [
            {
                "season_id": r[0],
                "season_name": r[1] or str(r[0]),
                "is_current": bool(r[2]),
            }
            for r in all_season_rows
        ]
        valid_season_ids = {r[0] for r in all_season_rows}

        if season_id is None:
            # Prefer the highlighted (current) season; fall back to most recent
            highlighted = next((r[0] for r in all_season_rows if r[2]), None)
            season_id = highlighted or (all_season_rows[0][0] if all_season_rows else _get_current_season_id(session))
        elif season_id not in valid_season_ids and all_season_rows:
            season_id = all_season_rows[0][0]

        team = session.query(Team).filter(
            Team.id == team_id,
            Team.season_id == season_id,
        ).first()

        if team is None:
            return {}

        # Season and league display labels
        season_row = session.get(Season, season_id)
        season_name = season_row.text if season_row else str(season_id)
        league_row = (
            session.query(League).filter(League.id == team.league_id).first()
            if team.league_id else None
        )
        league_name = (
            (league_row.name or league_row.text if league_row else None)
            or team.game_class
            or ""
        )

        # ── Step 1: game_players lookup ──────────────────────────────────────
        # Aggregate all lineup appearances for this team/season so we can:
        #  a) fill missing jersey/position in the official roster
        #  b) add players seen in games who are absent from the official roster
        gp_agg: dict[int, dict] = {}
        for gp, pl in (
            session.query(GamePlayer, Player)
            .join(Player, GamePlayer.player_id == Player.person_id)
            .filter(
                GamePlayer.team_id == team_id,
                GamePlayer.season_id == season_id,
            )
            .all()
        ):
            pid = pl.person_id
            if pid not in gp_agg:
                gp_agg[pid] = {
                    "player_id": pid,
                    "name": pl.full_name or f"Player {pid}",
                    "number": None, "position": None,
                    "gp": 0, "g": 0, "a": 0, "pts": 0, "pim": 0,
                }
            entry = gp_agg[pid]
            if gp.jersey_number and not entry["number"]:
                entry["number"] = gp.jersey_number
            if gp.position and gp.position.lower() not in _UNKNOWN_POS and not entry["position"]:
                entry["position"] = gp.position
            entry["gp"]  += 1
            entry["g"]   += gp.goals or 0
            entry["a"]   += gp.assists or 0
            entry["pts"] += (gp.goals or 0) + (gp.assists or 0)
            entry["pim"] += gp.penalty_minutes or 0

        # Players in gp_agg who are officially on a different team this season
        # (guests / loan appearances) — must be excluded from any extras list.
        other_team_pids: set[int] = set()
        if gp_agg:
            other_team_pids = {
                pid
                for (pid,) in session.query(TeamPlayer.player_id)
                .filter(
                    TeamPlayer.season_id == season_id,
                    TeamPlayer.team_id != team_id,
                    TeamPlayer.player_id.in_(list(gp_agg.keys())),
                )
                .all()
            }

        # ── Step 2: official TeamPlayer roster ───────────────────────────────
        roster = []
        roster_source = "official"  # "official" | "games"
        tp_rows = (
            session.query(TeamPlayer, Player)
            .join(Player, TeamPlayer.player_id == Player.person_id)
            .filter(
                TeamPlayer.team_id == team_id,
                TeamPlayer.season_id == season_id,
            )
            .order_by(TeamPlayer.jersey_number.nulls_last())
            .all()
        )

        if tp_rows:
            pids = [pl.person_id for _, pl in tp_rows]

            # Determine which league_abbrev in PlayerStatistics corresponds to
            # this team's league. A player who also plays at U21, 2nd-team etc.
            # will have multiple rows with the same team_name; we want only the
            # league the team itself plays in. We find it by majority vote across
            # all official roster players.
            from collections import Counter
            abbrev_votes: Counter = Counter()
            for ps in (
                session.query(
                    PlayerStatistics.league_abbrev,
                    PlayerStatistics.games_played,
                )
                .filter(
                    PlayerStatistics.player_id.in_(pids),
                    PlayerStatistics.season_id == season_id,
                    PlayerStatistics.team_name == team.name,
                )
                .all()
            ):
                abbrev_votes[ps.league_abbrev] += ps.games_played or 1
            team_league_abbrev: str | None = (
                abbrev_votes.most_common(1)[0][0] if abbrev_votes else None
            )

            # Aggregate PlayerStatistics rows for this team/league only
            ps_filter = [
                PlayerStatistics.player_id.in_(pids),
                PlayerStatistics.season_id == season_id,
                PlayerStatistics.team_name == team.name,
            ]
            if team_league_abbrev:
                ps_filter.append(PlayerStatistics.league_abbrev == team_league_abbrev)

            player_stat_map: dict[int, dict] = {}
            for ps in session.query(PlayerStatistics).filter(*ps_filter).all():
                pid = ps.player_id
                if pid not in player_stat_map:
                    player_stat_map[pid] = {"gp": 0, "g": 0, "a": 0, "pts": 0, "pim": 0}
                player_stat_map[pid]["gp"]  += ps.games_played or 0
                player_stat_map[pid]["g"]   += ps.goals or 0
                player_stat_map[pid]["a"]   += ps.assists or 0
                player_stat_map[pid]["pts"] += ps.points or 0
                player_stat_map[pid]["pim"] += ps.penalty_minutes or 0

            for tp, pl in tp_rows:
                ps = player_stat_map.get(pl.person_id) or {}
                gp_info = gp_agg.get(pl.person_id, {})
                # Fill in number / position from game history if blank or unknown
                number = tp.jersey_number or gp_info.get("number")
                pos_raw = tp.position or ""
                position = (
                    pos_raw if pos_raw.lower() not in _UNKNOWN_POS
                    else (gp_info.get("position") or "")
                )
                roster.append(
                    {
                        "player_id": pl.person_id,
                        "name": pl.full_name or f"Player {pl.person_id}",
                        "number": number,
                        "position": position,
                        "gp": ps.get("gp", 0),
                        "g":  ps.get("g", 0),
                        "a":  ps.get("a", 0),
                        "pts": ps.get("pts", 0),
                        "pim": ps.get("pim", 0),
                    }
                )

            # Add players seen in game lineups but absent from the official roster.
            # Exclude players who are officially registered on a DIFFERENT team this
            # season — they are guests/loan players and don't belong here.
            official_pids = {pl.person_id for _, pl in tp_rows}
            extras_pids = [
                pid for pid in gp_agg
                if pid not in official_pids and pid not in other_team_pids
            ]
            # Look up PlayerStatistics for these extras (same as official path)
            extras_stat_map: dict[int, dict] = {}
            if extras_pids:
                ps_filter_extras = [
                    PlayerStatistics.player_id.in_(extras_pids),
                    PlayerStatistics.season_id == season_id,
                    PlayerStatistics.team_name == team.name,
                ]
                if team_league_abbrev:
                    ps_filter_extras.append(
                        PlayerStatistics.league_abbrev == team_league_abbrev
                    )
                for ps in session.query(PlayerStatistics).filter(*ps_filter_extras).all():
                    pid = ps.player_id
                    if pid not in extras_stat_map:
                        extras_stat_map[pid] = {"gp": 0, "g": 0, "a": 0, "pts": 0, "pim": 0}
                    extras_stat_map[pid]["gp"]  += ps.games_played or 0
                    extras_stat_map[pid]["g"]   += ps.goals or 0
                    extras_stat_map[pid]["a"]   += ps.assists or 0
                    extras_stat_map[pid]["pts"] += ps.points or 0
                    extras_stat_map[pid]["pim"] += ps.penalty_minutes or 0
            for pid in extras_pids:
                info = gp_agg[pid]
                ps = extras_stat_map.get(pid) or {}
                roster.append(
                    {
                        "player_id": pid,
                        "name": info["name"],
                        "number": info["number"],
                        "position": info["position"] or "",
                        "gp": ps.get("gp") or info["gp"],
                        "g":  ps.get("g", 0),
                        "a":  ps.get("a", 0),
                        "pts": ps.get("pts", 0),
                        "pim": ps.get("pim", 0),
                        "from_games": True,
                    }
                )
        else:
            # Roster not indexed — build entirely from game lineups,
            # but still skip players officially on other teams.
            roster_source = "games"
            for pid, info in gp_agg.items():
                if pid in other_team_pids:
                    continue
                roster.append(
                    {
                        "player_id": pid,
                        "name": info["name"],
                        "number": info["number"],
                        "position": info["position"] or "",
                        "gp": info["gp"],
                        "g":  info["g"],
                        "a":  info["a"],
                        "pts": info["pts"],
                        "pim": info["pim"],
                    }
                )
            roster.sort(key=lambda r: (r["number"] if r["number"] is not None else 99, r["name"]))

        # Recent games (last 10 with a score)
        recent_games_raw = (
            session.query(Game)
            .filter(
                or_(Game.home_team_id == team_id, Game.away_team_id == team_id),
                Game.season_id == season_id,
                Game.home_score.isnot(None),
            )
            .order_by(Game.game_date.desc())
            .limit(10)
            .all()
        )

        # Preload opponent names
        opp_ids = set()
        for g in recent_games_raw:
            opp_ids.add(g.home_team_id if g.away_team_id == team_id else g.away_team_id)

        opp_names: dict[int, str] = {}
        for t in session.query(Team).filter(
            Team.id.in_(opp_ids), Team.season_id == season_id
        ).all():
            if t.name or t.text:
                opp_names[t.id] = t.name or t.text
        # Cross-season fallback for nameless stubs
        missing_opp = {tid for tid in opp_ids if tid not in opp_names}
        if missing_opp:
            for t in session.query(Team).filter(
                Team.id.in_(missing_opp), Team.name.isnot(None)
            ).all():
                opp_names[t.id] = t.name

        recent_games = []
        for g in recent_games_raw:
            is_home = g.home_team_id == team_id
            opp_id = g.away_team_id if is_home else g.home_team_id
            my_score = g.home_score if is_home else g.away_score
            opp_score = g.away_score if is_home else g.home_score
            result_label = "W" if my_score > opp_score else ("L" if my_score < opp_score else "T")
            recent_games.append(
                {
                    "game_id": g.id,
                    "date": g.game_date.strftime("%Y-%m-%d") if g.game_date else "",
                    "opponent_id": opp_id,
                    "opponent_name": opp_names.get(opp_id, f"Team {opp_id}"),
                    "home_away": "H" if is_home else "A",
                    "score": f"{my_score}:{opp_score}",
                    "result": result_label,
                }
            )

        return {
            "id": team.id,
            "name": team.name or team.text or f"Team {team_id}",
            "season_id": season_id,
            "season_name": season_name,
            "league_id": team.league_id,
            "league_name": league_name,
            "game_class": team.game_class,
            "available_seasons": available_seasons,
            "roster": roster,
            "roster_source": roster_source,
            "recent_games": recent_games,
            "upcoming_games": _get_team_upcoming(session, team_id, season_id),
        }


def _get_team_upcoming(session, team_id: int, season_id: int) -> list[dict]:
    """Return upcoming (unscored) games for a team."""
    from datetime import date as _date
    uq = (
        session.query(Game)
        .filter(
            or_(Game.home_team_id == team_id, Game.away_team_id == team_id),
            Game.season_id == season_id,
            Game.home_score.is_(None),
            Game.game_date.isnot(None),
            Game.game_date >= _date.today(),
        )
        .order_by(Game.game_date.asc())
        .limit(10)
        .all()
    )
    opp_ids = {g.home_team_id if g.away_team_id == team_id else g.away_team_id for g in uq}
    opp_names: dict[int, str] = {}
    for t in session.query(Team).filter(Team.id.in_(opp_ids), Team.season_id == season_id).all():
        if t.name or t.text:
            opp_names[t.id] = t.name or t.text
    result = []
    for g in uq:
        is_home = g.home_team_id == team_id
        opp_id = g.away_team_id if is_home else g.home_team_id
        result.append({
            "game_id": g.id,
            "date": g.game_date.strftime("%d.%m.%Y") if g.game_date else "",
            "weekday": g.game_date.strftime("%a") if g.game_date else "",
            "time": g.game_time or "",
            "home_away": "H" if is_home else "A",
            "opponent_id": opp_id,
            "opponent_name": opp_names.get(opp_id, f"Team {opp_id}"),
        })
    return result


# ---------------------------------------------------------------------------
# 6. Player detail
# ---------------------------------------------------------------------------

def get_player_detail(person_id: int) -> dict:
    """
    Return player profile + per-season stats across all seasons.
    Uses team_name / league_abbrev text columns (populated since schema migration).
    """
    from app.services.data_indexer import LEAGUE_TIERS
    _DEFAULT_TIER = 99
    _STRIP_PREFIXES = ("herren ", "damen ", "junioren ", "juniorinnen ",
                       "junioren/-innen ", "senioren ")

    db = get_database_service()
    with db.session_scope() as session:
        player = session.query(Player).filter(Player.person_id == person_id).first()
        if player is None:
            return {}

        # Build a league-name-abbreviation → tier lookup so career rows can be
        # sorted by tier within each season (best league first).
        # PlayerStatistics stores a short name like "NLB" or "U21 B" derived from
        # the API stats page; League.name stores the full name like "Herren NLB".
        # We strip common gender/age prefixes to produce the short form.
        abbrev_tier: dict[str, int] = {}
        for (lname, lid) in (
            session.query(League.name, League.league_id).distinct().all()
        ):
            if not lname:
                continue
            t = LEAGUE_TIERS.get(lid, _DEFAULT_TIER)
            short = lname
            for pfx in _STRIP_PREFIXES:
                if short.lower().startswith(pfx):
                    short = short[len(pfx):]
                    break
            # Store both full name and short name; keep the best (lowest) tier
            for key in (lname, short):
                if key not in abbrev_tier or abbrev_tier[key] > t:
                    abbrev_tier[key] = t

        stats_rows = (
            session.query(PlayerStatistics, Season)
            .join(Season, PlayerStatistics.season_id == Season.id)
            .filter(PlayerStatistics.player_id == person_id)
            .all()
        )

        career: list[dict] = []
        for ps, season in stats_rows:
            career.append(
                {
                    "season_text": season.text or str(season.id),
                    "season_id": season.id,
                    "team_name": ps.team_name or "—",
                    "league": ps.league_abbrev or "",
                    "team_id": ps.team_id,
                    "gp": ps.games_played,
                    "g": ps.goals,
                    "a": ps.assists,
                    "pts": ps.points,
                    "pim": ps.penalty_minutes,
                    "_tier": abbrev_tier.get(ps.league_abbrev or "", _DEFAULT_TIER),
                }
            )

        # Sort: most recent season first, then by tier (best league first) within season
        career.sort(key=lambda r: (-r["season_id"], r["_tier"]))
        for r in career:
            r.pop("_tier", None)

        # Career totals
        totals = {
            "gp": sum(r["gp"] for r in career),
            "g": sum(r["g"] for r in career),
            "a": sum(r["a"] for r in career),
            "pts": sum(r["pts"] for r in career),
            "pim": sum(r["pim"] for r in career),
        }

        # Recent game appearances (last 10 across all seasons, most recent first)
        from app.models.db_models import Game as _Game, Team as _Team
        recent_game_rows = (
            session.query(GamePlayer, _Game)
            .join(_Game, GamePlayer.game_id == _Game.id)
            .filter(GamePlayer.player_id == person_id)
            .order_by(_Game.game_date.desc())
            .limit(10)
            .all()
        )
        # Preload team names needed
        team_ids_needed = set()
        for _, g in recent_game_rows:
            team_ids_needed.add(g.home_team_id)
            team_ids_needed.add(g.away_team_id)
        team_names = {
            t.id: t.name
            for t in session.query(_Team).filter(_Team.id.in_(team_ids_needed)).all()
        }

        recent_games: list[dict] = []
        for gp, g in recent_game_rows:
            is_home = (gp.team_id == g.home_team_id)
            opp_id = g.away_team_id if is_home else g.home_team_id
            opp_name = team_names.get(opp_id, f"Team {opp_id}")
            if g.home_score is not None and g.away_score is not None:
                my_score = g.home_score if is_home else g.away_score
                opp_score = g.away_score if is_home else g.home_score
                if my_score > opp_score:
                    result_label = "W"
                elif my_score < opp_score:
                    result_label = "L"
                else:
                    result_label = "D"
                score_str = f"{my_score}–{opp_score}"
            else:
                result_label = ""
                score_str = ""
            recent_games.append({
                "game_id": g.id,
                "date": g.game_date.strftime("%Y-%m-%d") if g.game_date else "",
                "home_away": "H" if is_home else "A",
                "opponent": opp_name,
                "opponent_id": opp_id,
                "score": score_str,
                "result": result_label,
                "season_id": g.season_id,
            })

        result = {
            "person_id": player.person_id,
            "name": player.full_name or f"Player {player.person_id}",
            "first_name": player.first_name or "",
            "last_name": player.last_name or "",
            "year_of_birth": player.year_of_birth,
            "career": career,
            "totals": totals,
            "recent_games": recent_games,
            "photo_url": None,
        }

    # Fetch photo URL from API outside the DB session (HTTP call)
    try:
        from app.services.swissunihockey import get_swissunihockey_client
        client = get_swissunihockey_client()
        api_data = client.get_player_details(person_id)
        regions = api_data.get("data", {}).get("regions", [])
        if regions:
            cells = regions[0].get("rows", [{}])[0].get("cells", [])
            if cells:
                img = cells[0].get("image", {})
                result["photo_url"] = img.get("url") or None
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# 7. Upcoming games
# ---------------------------------------------------------------------------

def get_upcoming_games(
    limit: int = 10,
    league_ids: Optional[list] = None,
    league_category: Optional[str] = None,
    season_id: Optional[int] = None,
) -> list[dict]:
    """
    Return next scheduled games (no score yet), ordered soonest first.
    
    Args:
        limit: Maximum number of games to return
        league_ids: Filter by league IDs (legacy parameter)
        league_category: Filter by league category (e.g., "2_11" for NLB Men)
        season_id: Season ID to filter by
    """
    from datetime import date as _date
    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        today = _date.today()
        q = (
            session.query(Game)
            .filter(
                Game.season_id == season_id,
                Game.home_score.is_(None),
                Game.game_date.isnot(None),
                Game.game_date >= today,
            )
        )
        
        # Filter by league category (e.g., "2_11" = NLB Men)
        if league_category and league_category != 'all':
            parts = league_category.split('_')
            if len(parts) == 2:
                try:
                    league_id = int(parts[0])
                    game_class = int(parts[1])
                    # Join through LeagueGroup to League
                    q = (q.join(LeagueGroup, Game.group_id == LeagueGroup.id)
                          .join(League, LeagueGroup.league_id == League.id)
                          .filter(League.league_id == league_id, League.game_class == game_class))
                except ValueError:
                    pass  # Invalid format, ignore filter
        elif league_ids:
            # Legacy filtering by league IDs
            q = q.join(LeagueGroup, Game.group_id == LeagueGroup.id).filter(
                LeagueGroup.league_id.in_(league_ids)
            )
            
        games_raw = q.order_by(Game.game_date.asc()).limit(limit).all()

        if not games_raw:
            return []

        team_ids = {g.home_team_id for g in games_raw} | {g.away_team_id for g in games_raw}
        t_names: dict = {}
        for t in session.query(Team).filter(
            Team.id.in_(team_ids), Team.season_id == season_id
        ).all():
            t_names[t.id] = t.name or t.text or f"Team {t.id}"
        missing = team_ids - t_names.keys()
        if missing:
            for t in session.query(Team).filter(Team.id.in_(missing), Team.name.isnot(None)).all():
                t_names.setdefault(t.id, t.name)

        # league name per group
        group_ids = {g.group_id for g in games_raw}
        grp_league: dict = {}
        grp_league_category: dict = {}  # For filtering: league_id_game_class
        grp_name: dict = {}  # Group name/number
        for grp in session.query(LeagueGroup).filter(LeagueGroup.id.in_(group_ids)).all():
            lg = session.query(League).filter(League.id == grp.league_id).first()
            grp_league[grp.id] = lg.name if lg else ""
            grp_name[grp.id] = grp.name or grp.text or ""
            if lg:
                grp_league_category[grp.id] = f"{lg.league_id}_{lg.game_class}"

        return [
            {
                "game_id": g.id,
                "date": g.game_date.strftime("%d.%m") if g.game_date else "",
                "weekday": g.game_date.strftime("%a") if g.game_date else "",
                "time": g.game_time or "",
                "home_team": t_names.get(g.home_team_id, f"Team {g.home_team_id}"),
                "away_team": t_names.get(g.away_team_id, f"Team {g.away_team_id}"),
                "home_team_id": g.home_team_id,
                "away_team_id": g.away_team_id,
                "league": grp_league.get(g.group_id, ""),
                "group_name": grp_name.get(g.group_id, ""),
                "league_category": grp_league_category.get(g.group_id, ""),
            }
            for g in games_raw
        ]


def get_latest_results(
    limit: int = 10,
    league_ids: Optional[list] = None,
    league_category: Optional[str] = None,
    season_id: Optional[int] = None,
) -> list[dict]:
    """
    Return recently completed games (with scores), ordered most recent first.
    
    Args:
        limit: Maximum number of games to return
        league_ids: Filter by league IDs (legacy parameter)
        league_category: Filter by league category (e.g., "2_11" for NLB Men)
        season_id: Season ID to filter by
    """
    from datetime import date as _date
    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        today = _date.today()
        q = (
            session.query(Game)
            .filter(
                Game.season_id == season_id,
                Game.home_score.isnot(None),  # Has score = completed
                Game.game_date.isnot(None),
                Game.game_date <= today,
            )
        )
        
        # Filter by league category (e.g., "2_11" = NLB Men)
        if league_category and league_category != 'all':
            parts = league_category.split('_')
            if len(parts) == 2:
                try:
                    league_id = int(parts[0])
                    game_class = int(parts[1])
                    # Join through LeagueGroup to League
                    q = (q.join(LeagueGroup, Game.group_id == LeagueGroup.id)
                          .join(League, LeagueGroup.league_id == League.id)
                          .filter(League.league_id == league_id, League.game_class == game_class))
                except ValueError:
                    pass  # Invalid format, ignore filter
        elif league_ids:
            # Legacy filtering by league IDs
            q = q.join(LeagueGroup, Game.group_id == LeagueGroup.id).filter(
                LeagueGroup.league_id.in_(league_ids)
            )
            
        games_raw = q.order_by(Game.game_date.desc()).limit(limit).all()

        if not games_raw:
            return []

        team_ids = {g.home_team_id for g in games_raw} | {g.away_team_id for g in games_raw}
        t_names: dict = {}
        for t in session.query(Team).filter(
            Team.id.in_(team_ids), Team.season_id == season_id
        ).all():
            t_names[t.id] = t.name or t.text or f"Team {t.id}"
        missing = team_ids - t_names.keys()
        if missing:
            for t in session.query(Team).filter(Team.id.in_(missing), Team.name.isnot(None)).all():
                t_names.setdefault(t.id, t.name)

        # league name per group
        group_ids = {g.group_id for g in games_raw}
        grp_league: dict = {}
        grp_league_category: dict = {}  # For filtering: league_id_game_class
        grp_name: dict = {}  # Group name/number
        for grp in session.query(LeagueGroup).filter(LeagueGroup.id.in_(group_ids)).all():
            lg = session.query(League).filter(League.id == grp.league_id).first()
            grp_league[grp.id] = lg.name if lg else ""
            grp_name[grp.id] = grp.name or grp.text or ""
            if lg:
                grp_league_category[grp.id] = f"{lg.league_id}_{lg.game_class}"

        return [
            {
                "game_id": g.id,
                "date": g.game_date.strftime("%d.%m") if g.game_date else "",
                "weekday": g.game_date.strftime("%a") if g.game_date else "",
                "time": g.game_time or "",
                "home_team": t_names.get(g.home_team_id, f"Team {g.home_team_id}"),
                "away_team": t_names.get(g.away_team_id, f"Team {g.away_team_id}"),
                "home_score": g.home_score or 0,
                "away_score": g.away_score or 0,
                "home_team_id": g.home_team_id,
                "away_team_id": g.away_team_id,
                "league": grp_league.get(g.group_id, ""),
                "group_name": grp_name.get(g.group_id, ""),
                "league_category": grp_league_category.get(g.group_id, ""),
            }
            for g in games_raw
        ]


# ---------------------------------------------------------------------------
# 8. Game detail / box score
# ---------------------------------------------------------------------------

_GOAL_RE = re.compile(r"^(Torschütze|Eigentor)\s+(\d+):(\d+)", re.IGNORECASE)
_PENALTY_RE = re.compile(r"^(\d+)'-Strafe\s*\((.+?)\)", re.IGNORECASE)
_PERIOD_START_RE = re.compile(r"^(Beginn|Start)\s+(.+)", re.IGNORECASE)
_PERIOD_END_RE = re.compile(r"^Ende\s+(.+)", re.IGNORECASE)


def _classify_event(event_type: str) -> str:
    if _GOAL_RE.match(event_type):
        return "goal"
    if _PENALTY_RE.match(event_type):
        return "penalty"
    if event_type.lower().startswith("bester spieler"):
        return "best_player"
    if _PERIOD_END_RE.match(event_type) or _PERIOD_START_RE.match(event_type):
        return "period"
    return "other"


def _period_from_time(time_str: str) -> str | None:
    """Derive period label from a 'MM:SS' (or 'MM') clock string.

    0–19:59  → "1"
    20–39:59 → "2"
    40–59:59 → "3"
    60–69:59 → "OT"
    70+      → "PS"
    """
    if not time_str:
        return None
    try:
        parts = str(time_str).split(":")
        minutes = int(parts[0])
        if minutes < 20:
            return "1"
        if minutes < 40:
            return "2"
        if minutes < 60:
            return "3"
        if minutes < 70:
            return "OT"
        return "PS"
    except (ValueError, IndexError):
        return None


def get_game_box_score(game_id: int) -> dict:
    """
    Parse game_events for a game and return a structured box score dict.
    """
    db = get_database_service()
    with db.session_scope() as session:
        game = session.query(Game).filter(Game.id == game_id).first()
        if game is None:
            return {}

        # Load team names
        def _team_name(tid: int) -> str:
            if tid is None:
                return "?"
            t = session.query(Team).filter(
                Team.id == tid,
                Team.season_id == game.season_id,
            ).first()
            return (t.name if t else None) or f"Team {tid}"

        home_name = _team_name(game.home_team_id)
        away_name = _team_name(game.away_team_id)

        events_raw = (
            session.query(GameEvent)
            .filter(GameEvent.game_id == game_id)
            .order_by(GameEvent.period, GameEvent.time)
            .all()
        )

        goals = []
        penalties = []
        period_markers = []
        best_players = []

        for ev in events_raw:
            raw = ev.raw_data or {}
            ev_type = ev.event_type or ""
            kind = _classify_event(ev_type)
            time_str = raw.get("time") or ev.time or ""
            period = ev.period or _period_from_time(time_str)

            # Determine team label
            team_label = raw.get("team", "")
            if not team_label:
                if ev.team_id == game.home_team_id:
                    team_label = home_name
                elif ev.team_id == game.away_team_id:
                    team_label = away_name

            player_name = raw.get("player", "")
            if not player_name and ev.player_id:
                pl = session.query(Player).filter(Player.person_id == ev.player_id).first()
                if pl:
                    player_name = pl.full_name or ""

            if kind == "goal":
                m = _GOAL_RE.match(ev_type)
                score_str = f"{m.group(2)}:{m.group(3)}" if m else ""
                is_own_goal = ev_type.lower().startswith("eigentor")
                goals.append(
                    {
                        "period": period,
                        "time": time_str,
                        "score": score_str,
                        "team": team_label,
                        "player": player_name,
                        "own_goal": is_own_goal,
                        "_ev_type": ev_type,  # kept for OG direction detection
                    }
                )

            elif kind == "penalty":
                m = _PENALTY_RE.match(ev_type)
                minutes = int(m.group(1)) if m else 0
                infraction = m.group(2).strip() if m else ev_type
                penalties.append(
                    {
                        "period": period,
                        "time": time_str,
                        "team": team_label,
                        "player": player_name,
                        "minutes": minutes,
                        "infraction": infraction,
                    }
                )

            elif kind == "period":
                period_markers.append({"time": time_str, "label": ev_type, "period": period})

            elif kind == "best_player":
                best_players.append({"team": team_label, "player": player_name})

        # ── Deduplicate goals ────────────────────────────────────────────────
        # The API emits 2 rows per assisted goal: one scorer-only and one
        # scorer+assist. Merge by (time, team), keeping the richer player string,
        # then reconstruct the running H:A score from scratch.
        deduped_goals: list[dict] = []
        for g in goals:
            merged = False
            for dg in deduped_goals:
                if dg["time"] == g["time"] and dg["team"] == g["team"]:
                    if len(g["player"] or "") > len(dg["player"] or ""):
                        dg["player"] = g["player"]
                    merged = True
                    break
            if not merged:
                deduped_goals.append(g)

        h_score, a_score = 0, 0
        dc_h, dc_a = 0, 0  # running doubled-counter from API embedded scores
        for g in deduped_goals:
            is_home = (g["team"] == home_name)
            m_emb = _GOAL_RE.match(g.get("_ev_type", ""))
            emb_h = int(m_emb.group(2)) if m_emb else None
            emb_a = int(m_emb.group(3)) if m_emb else None

            if g.get("own_goal"):
                if g["team"]:
                    # Team known: OG scores for the opponent
                    if is_home:
                        a_score += 1
                    else:
                        h_score += 1
                elif emb_h is not None:
                    # Team unknown: detect direction from which doubled-counter incremented
                    delta_a = emb_a - dc_a
                    delta_h = emb_h - dc_h
                    if delta_a > delta_h:
                        a_score += 1  # A counter went up → A benefited → home scored OG
                    else:
                        h_score += 1  # H counter went up → H benefited → away scored OG
                # fallthrough: if no embedded score, score stays unchanged
            elif is_home:
                h_score += 1
            else:
                a_score += 1

            if emb_h is not None:
                dc_h, dc_a = emb_h, emb_a
            g["score"] = f"{h_score}:{a_score}"
        for g in deduped_goals:
            g.pop("_ev_type", None)
        goals = deduped_goals

        # ── Deduplicate penalties ────────────────────────────────────────────
        # The API also emits 2 identical rows per penalty.
        seen_penalties: set[tuple] = set()
        deduped_penalties: list[dict] = []
        for p in penalties:
            key = (p["time"], p["team"], p["player"], p["minutes"])
            if key not in seen_penalties:
                seen_penalties.add(key)
                deduped_penalties.append(p)
        penalties = deduped_penalties

        # ── Roster ──────────────────────────────────────────────────────────
        roster_home: list[dict] = []
        roster_away: list[dict] = []
        gp_rows = (
            session.query(GamePlayer)
            .filter(GamePlayer.game_id == game_id)
            .order_by(GamePlayer.is_home_team.desc(), GamePlayer.jersey_number)
            .all()
        )
        for gp in gp_rows:
            pl = session.query(Player).filter(Player.person_id == gp.player_id).first()
            name = (pl.full_name if pl else None) or f"Player {gp.player_id}"
            entry = {
                "jersey": gp.jersey_number,
                "position": gp.position or "",
                "player": name,
                "player_id": gp.player_id,
            }
            if gp.is_home_team:
                roster_home.append(entry)
            else:
                roster_away.append(entry)

        return {
            "game_id": game_id,
            "season_id": game.season_id,
            "home_team_id": game.home_team_id,
            "away_team_id": game.away_team_id,
            "home_team": home_name,
            "away_team": away_name,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "date": game.game_date.strftime("%Y-%m-%d") if game.game_date else "",
            "time": game.game_time or "",
            "venue": game.venue or "",
            "status": game.status or "",
            "goals": goals,
            "penalties": penalties,
            "period_markers": period_markers,
            "best_players": best_players,
            "roster_home": roster_home,
            "roster_away": roster_away,
        }


# ---------------------------------------------------------------------------
# 8. Games list page
# ---------------------------------------------------------------------------

def get_recent_games(
    season_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    with_score_only: bool = False,
) -> dict:
    """Return recent/upcoming games for a season with pagination metadata."""
    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        q = session.query(Game).filter(Game.season_id == season_id)
        if with_score_only:
            q = q.filter(Game.home_score.isnot(None))

        total = q.count()
        games_raw = q.order_by(Game.game_date.desc()).offset(offset).limit(limit).all()

        # Preload team names in batch
        team_ids = set()
        for g in games_raw:
            team_ids.add(g.home_team_id)
            team_ids.add(g.away_team_id)

        t_names: dict[int, str] = {}
        for t in session.query(Team).filter(
            Team.id.in_(team_ids), Team.season_id == season_id
        ).all():
            if t.name or t.text:
                t_names[t.id] = t.name or t.text
        # Cross-season fallback for nameless stubs
        missing = {tid for tid in team_ids if tid not in t_names}
        if missing:
            for t in session.query(Team).filter(
                Team.id.in_(missing), Team.name.isnot(None)
            ).all():
                t_names[t.id] = t.name

        result = []
        for g in games_raw:
            result.append(
                {
                    "game_id": g.id,
                    "date": g.game_date.strftime("%Y-%m-%d") if g.game_date else "",
                    "time": g.game_time or "",
                    "home_team": t_names.get(g.home_team_id, f"Team {g.home_team_id}"),
                    "away_team": t_names.get(g.away_team_id, f"Team {g.away_team_id}"),
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "home_score": g.home_score,
                    "away_score": g.away_score,
                    "status": g.status or "",
                    "has_score": g.home_score is not None,
                }
            )
        return {"games": result, "total": total, "offset": offset, "limit": limit}
