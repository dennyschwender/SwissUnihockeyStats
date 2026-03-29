"""
DB-backed stats service for Swiss Unihockey Stats frontend.

All functions query the local SQLite database (via SQLAlchemy) and return
plain Python dicts / lists ready to be passed to Jinja2 templates.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import joinedload

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
from app.services.cache import get_cached, set_cached

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Compact position abbreviations used in the game roster table.
_POS_ABBREV: dict[str, str] = {
    "goalie": "G",
    "torhüter": "G",
    "torhüterin": "G",
    "goalkeeper": "G",
    "verteidiger": "D",
    "verteidigerin": "D",
    "defender": "D",
    "stürmer": "A",
    "stürmerin": "A",
    "stürmer (mitte)": "C",
    "stürmerin (mitte)": "C",
    "stürmer (links)": "A",
    "stürmer (rechts)": "A",
    "stürmerin (links)": "A",
    "stürmerin (rechts)": "A",
    "forward": "A",
    "center": "C",
    "attaquant": "A",
    "défenseur": "D",
    "gardien": "G",
}

# Position values that are considered unknown / placeholder.
_UNKNOWN_POS: frozenset[str] = frozenset({"nicht bekannt", ""})


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
            {"id": s.id, "name": s.text or str(s.id), "current": s.id == current_id} for s in rows
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
            {"id": r.id, "name": r.text or str(r.id), "current": r.id == current_id} for r in rows
        ]


def get_seasons_with_player_stats() -> list[dict]:
    """Return only seasons that have at least one PlayerStatistics row, ordered descending."""
    db = get_database_service()
    with db.session_scope() as session:
        current_id = _get_current_season_id(session)
        rows = (
            session.query(Season.id, Season.text, func.count(PlayerStatistics.id).label("cnt"))
            .outerjoin(PlayerStatistics, PlayerStatistics.season_id == Season.id)
            .group_by(Season.id)
            .having(func.count(PlayerStatistics.id) > 0)
            .order_by(Season.id.desc())
            .all()
        )
        return [
            {"id": r.id, "name": r.text or str(r.id), "current": r.id == current_id} for r in rows
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
                    "group_count": len({g.name or g.text for g in lg.groups} - {None, ""}),
                }
            )
        return result


# Mapping from API game_class int to human-readable category label
_GAME_CLASS_LABEL = {11: "Men", 21: "Women"}


def _mw_from_league(game_class: int | None, league_name: str) -> str:
    """Return 'M' or 'W' for a league, falling back to name keywords when
    game_class is None or an unexpected value."""
    if game_class == 11:
        return "M"
    if game_class == 21:
        return "W"
    name_upper = (league_name or "").upper()
    if any(k in name_upper for k in ("HERREN", "JUNIOREN")):
        return "M"
    if any(k in name_upper for k in ("DAMEN", "JUNIORINNEN")):
        return "W"
    return ""


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
            query = query.filter(or_(*[League.name.ilike(f"{n}%") for n in league_names]))

        if q:
            query = query.filter(or_(Team.name.ilike(f"%{q}%"), League.name.ilike(f"%{q}%")))

        if sort == "league":
            # Sort by tier level first, then by league_id (proxy for A/B/C/D level),
            # then season desc, then team name
            order: list[Any] = [_tier_order_expr(), func.coalesce(League.league_id, 99), Team.name]
            if all_seasons:
                order.insert(1, Season.id.desc())
            query = query.order_by(*order)
        else:
            order: list[Any] = [Team.name]
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
                    "game_class": gc,
                    "league_id": team.league_id,
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
        # Deduplicate groups by display name so identically-named groups
        # (e.g. multiple "Gruppe 1" rows from re-indexing) merge into one.
        seen: dict[str, list[int]] = {}
        for g in lg.groups:
            name = g.name or g.text or f"Group {g.id}"
            seen.setdefault(name, []).append(g.id)
        groups = [{"name": name, "ids": ids} for name, ids in seen.items()]
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


def _get_standings_from_api(session, league, only_group_ids: list[int] | None) -> list[dict]:
    """Fallback: fetch official standings from the Swiss Unihockey rankings API.

    Used when no finished games exist in the DB (e.g. the league admin never
    submitted individual game scores into the system — common in lower leagues).
    Returns the same dict structure as the DB-computed path so callers are
    transparent to the source.
    """
    try:
        from app.services.swissunihockey import get_swissunihockey_client

        client = get_swissunihockey_client()

        # Resolve group name(s) so we can filter the API call correctly.
        # When only_group_ids is given, find the distinct group names for those ids.
        group_names: list[str | None] = [None]  # None = no group filter (all teams)
        if only_group_ids:
            grp_rows = session.query(LeagueGroup).filter(LeagueGroup.id.in_(only_group_ids)).all()
            names = list({(g.name or g.text or None) for g in grp_rows} - {None})
            if names:
                group_names = names  # typically a single name like "Gruppe 2"

        all_rows: list[dict] = []
        import re as _re

        for grp_name in group_names:
            kwargs = dict(
                season=league.season_id,
                league=league.league_id,
                game_class=league.game_class,
            )
            if grp_name:
                kwargs["group"] = grp_name

            data = client.get_rankings(**kwargs)
            regions = data.get("data", {}).get("regions", [])
            for region in regions:
                for row in region.get("rows", []):
                    cells = row.get("cells", [])
                    if len(cells) < 10:
                        continue
                    # [0] rank  [1] logo  [2] team  [3] GP  [4] forfeits?
                    # [5] W  [6] OT-W  [7] OT-L  [8] L  [9] GF:GA  [10] GD  [12] pts
                    rank_t = cells[0].get("text", [])
                    rank_val = int(rank_t[0]) if isinstance(rank_t, list) and rank_t else 0

                    team_link = cells[2].get("link", {})
                    team_id = (team_link.get("ids") or [None])[0]
                    tn = cells[2].get("text", [])
                    team_name = (tn[0] if isinstance(tn, list) else tn) or f"Team {team_id}"

                    def _int(cell_idx: int) -> int:
                        t = cells[cell_idx].get("text", [0])
                        v = t[0] if isinstance(t, list) else t
                        try:
                            return int(v)
                        except (ValueError, TypeError):
                            return 0

                    gp = _int(3)
                    w = _int(5)
                    otw = _int(6)
                    otl = _int(7)
                    l = _int(8)
                    pts = _int(12) if len(cells) > 12 else (_int(10))

                    gfga = cells[9].get("text", []) if len(cells) > 9 else []
                    gfga_str = (gfga[0] if isinstance(gfga, list) else gfga) or "0:0"
                    m = _re.match(r"(\d+):(\d+)", gfga_str)
                    gf = int(m.group(1)) if m else 0
                    ga = int(m.group(2)) if m else 0

                    all_rows.append(
                        {
                            "rank": rank_val,
                            "team_id": team_id,
                            "team_name": team_name,
                            "gp": gp,
                            "w": w,  # regulation wins
                            "otw": otw,  # OT/SO wins
                            "otl": otl,  # OT/SO losses
                            "l": l,  # regulation losses
                            "gf": gf,
                            "ga": ga,
                            "gd": gf - ga,
                            "pts": pts,
                        }
                    )

        # Sort by pts desc, then gd desc, then gf desc (same as DB path)
        all_rows.sort(key=lambda x: (-x["pts"], -x["gd"], -x["gf"]))
        for i, row in enumerate(all_rows, 1):
            row["rank"] = i
        return all_rows

    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(f"API standings fallback failed: {exc}")
        return []


def get_league_standings(db_league_id: int, only_group_ids: list[int] | None = None) -> list[dict]:
    """
    Compute standings from finished games in a league (all its groups).

    Points system: Win=3, OT/SO Win=2, OT/SO Loss=1, Regular Loss=0.
    We detect OT/SO by presence of "overtime" / "penalty" in home_score comment
    – since we do not have that info, we simply use W=3, L=0 (two-point system
    is fine as a first pass; refine later if OT flag is available).

    Args:
        only_group_ids: when given, restrict to these group DB-IDs (for per-group standings).

    Returns list of dicts sorted by pts DESC, gd DESC, gf DESC.
    """
    cache_key = ("standings", db_league_id, tuple(sorted(only_group_ids or [])))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    db = get_database_service()
    with db.session_scope() as session:
        # Gather all group_ids for this league
        league = (
            session.query(League)
            .options(joinedload(League.groups))
            .filter(League.id == db_league_id)
            .first()
        )
        if league is None:
            return []

        group_ids = [g.id for g in league.groups]
        if only_group_ids is not None:
            allowed = set(only_group_ids)
            group_ids = [gid for gid in group_ids if gid in allowed]
        if not group_ids:
            return []

        # All games that have a score
        total_games = session.query(Game).filter(Game.group_id.in_(group_ids)).count()
        games = (
            session.query(Game)
            .filter(
                Game.group_id.in_(group_ids),
                Game.home_score.isnot(None),
                Game.away_score.isnot(None),
            )
            .all()
        )

        # Fall back to the official API rankings when:
        # - no scored games at all, OR
        # - very sparse scores (<10% of total games) suggesting only partial
        #   re-indexing happened (e.g. a few playoff results but a full regular season)
        scored_count = len(games)
        use_api_fallback = scored_count == 0 or (
            total_games > 20 and scored_count / total_games < 0.10
        )
        if use_api_fallback:
            return _get_standings_from_api(session, league, only_group_ids)

        # team_id → {name, gp, w, l, gf, ga, pts}
        table: dict[int, dict] = {}

        def _entry(team_id: int, team_name: str) -> dict:
            if team_id not in table:
                table[team_id] = {
                    "team_id": team_id,
                    "team_name": team_name,
                    "gp": 0,
                    "w": 0,  # regulation wins
                    "otw": 0,  # OT/SO wins
                    "otl": 0,  # OT/SO losses
                    "l": 0,  # regulation losses
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
        for t in (
            session.query(Team)
            .filter(
                Team.id.in_(team_ids),
                Team.season_id == league.season_id,
            )
            .all()
        ):
            if t.name is not None or t.text is not None:
                team_names[int(t.id)] = str(t.name or t.text)

        # 2) any season (for stubs that were created without a name)
        missing = team_ids - set(team_names)
        if missing:
            for t in (
                session.query(Team)
                .filter(
                    Team.id.in_(missing),
                    Team.name.isnot(None),
                )
                .all()
            ):
                team_names[int(t.id)] = str(t.name)

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
                            if stub and stub.name is None:
                                stub.name = tname
                                stub.text = tname
                session.commit()
            except Exception:
                pass

        for g in games:
            hs = int(g.home_score or 0)
            as_ = int(g.away_score or 0)
            _hid = int(g.home_team_id)
            _aid = int(g.away_team_id)
            h = _entry(_hid, team_names.get(_hid, f"Team {_hid}"))
            a = _entry(_aid, team_names.get(_aid, f"Team {_aid}"))

            h["gp"] += 1
            a["gp"] += 1
            h["gf"] += hs
            h["ga"] += as_
            a["gf"] += as_
            a["ga"] += hs

            # OT/SO: winner gets 2 pts, loser gets 1 pt; regulation: winner 3, loser 0
            is_extra = g.period in ("OT", "SO")

            if hs > as_:
                if is_extra:
                    h["otw"] += 1
                    h["pts"] += 2
                    a["otl"] += 1
                    a["pts"] += 1
                else:
                    h["w"] += 1
                    h["pts"] += 3
                    a["l"] += 1
            elif as_ > hs:
                if is_extra:
                    a["otw"] += 1
                    a["pts"] += 2
                    h["otl"] += 1
                    h["pts"] += 1
                else:
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

        set_cached(cache_key, standings)
        return standings


# ---------------------------------------------------------------------------
# 3. Top scorers per league
# ---------------------------------------------------------------------------


def get_league_top_scorers(db_league_id: int, limit: int = 20) -> list[dict]:
    """
    Top scorers for a league.

    Strategy (in order of preference):
    1. Primary: collect player_ids from GamePlayer rows for games in this
       league's groups — this is gender-exact because it keys off actual game
       participation, not just team name.
    2. Fallback: if GamePlayer has no rows for these games (i.e. game events
       were never indexed), use team_name IN (names from Team table) to filter
       PlayerStatistics.  This can produce false positives when a club fields
       both a men's and women's team with the same name (e.g. "Zug United"),
       but is better than returning nothing.

    league_abbrev is derived by stripping the gender prefix ("Herren "/"Damen ")
    from the DB league name so it matches what the API returns (e.g. "L-UPL").
    """
    cache_key = ("league_scorers", db_league_id, limit)
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    import re as _re

    db = get_database_service()
    with db.session_scope() as session:
        league = (
            session.query(League)
            .options(joinedload(League.groups))
            .filter(League.id == db_league_id)
            .first()
        )
        if league is None:
            return []

        group_ids = [g.id for g in league.groups]
        if not group_ids:
            return []

        # All game IDs in this league
        game_ids = [r[0] for r in session.query(Game.id).filter(Game.group_id.in_(group_ids)).all()]

        # Derive league_abbrev from the DB name by stripping the gender/age prefix
        # so it matches what the API returns (e.g. "Junioren U21 B" → "U21 B").
        # Order matters: "Junioren/-innen" must be tried before "Junioren".
        league_abbrev = _re.sub(
            r"^(Junioren/-innen|Junioren|Juniorinnen|Herren|Damen|Senioren)\s+",
            "",
            str(league.name or ""),
        ).strip()

        # ── Primary path: GamePlayer ──────────────────────────────────────────
        player_ids = []
        if game_ids:
            player_ids = [
                r[0]
                for r in session.query(GamePlayer.player_id)
                .filter(GamePlayer.game_id.in_(game_ids))
                .distinct()
                .all()
            ]

        # game_class filter: added when available — eliminates same-abbrev rows
        # from the opposite-gender league (e.g. "U21 B" male vs female).
        gc_filters = [
            PlayerStatistics.season_id == league.season_id,
            PlayerStatistics.league_abbrev == league_abbrev,
        ]
        if league.game_class:
            gc_filters.append(
                (PlayerStatistics.game_class == league.game_class)
                | (PlayerStatistics.game_class == None)  # noqa: E711 – SQLAlchemy IS NULL
            )

        if player_ids:
            stats = (
                session.query(PlayerStatistics, Player)
                .join(Player, PlayerStatistics.player_id == Player.person_id)
                .filter(
                    PlayerStatistics.player_id.in_(player_ids),
                    *gc_filters,
                )
                .order_by(PlayerStatistics.points.desc(), PlayerStatistics.goals.desc())
                .limit(limit)
                .all()
            )
        else:
            # ── Fallback (no GamePlayer rows — season not yet underway) ──────────
            #
            # Tiered strategy, most-accurate first:
            #  1. team_id IN (league's team IDs) — exact, gender-safe once indexer
            #     runs (team_id is now stored on PlayerStatistics rows).
            #  2. player_id IN (TeamPlayer roster for league's teams) + gc OR-NULL
            #  3. team_name IN (names) + STRICT game_class (no NULL) — last resort;
            #     NULL game_class rows are excluded to prevent gender bleed from
            #     same-named clubs that field both a male and female team.

            home_ids = {
                r[0]
                for r in session.query(Game.home_team_id).filter(Game.group_id.in_(group_ids)).all()
            }
            away_ids = {
                r[0]
                for r in session.query(Game.away_team_id).filter(Game.group_id.in_(group_ids)).all()
            }
            all_team_ids = list((home_ids | away_ids) - {None})
            if not all_team_ids:
                return []

            base_q = (
                session.query(PlayerStatistics, Player)
                .join(Player, PlayerStatistics.player_id == Player.person_id)
                .filter(
                    PlayerStatistics.season_id == league.season_id,
                    PlayerStatistics.league_abbrev == league_abbrev,
                )
                .order_by(PlayerStatistics.points.desc(), PlayerStatistics.goals.desc())
            )

            def _run(extra_filter):
                return base_q.filter(extra_filter).limit(limit).all()

            # Tier 1: team_id on PlayerStatistics (populated by indexer)
            stats = _run(PlayerStatistics.team_id.in_(all_team_ids))

            if not stats:
                # Tier 2: TeamPlayer roster (gender-exact via team_id)
                roster_player_ids = [
                    r[0]
                    for r in session.query(TeamPlayer.player_id)
                    .filter(
                        TeamPlayer.team_id.in_(all_team_ids),
                        TeamPlayer.season_id == league.season_id,
                    )
                    .distinct()
                    .all()
                ]
                if roster_player_ids:
                    gc_clause = (
                        (
                            (PlayerStatistics.game_class == league.game_class)
                            | (PlayerStatistics.game_class == None)  # noqa: E711
                        )
                        if league.game_class
                        else True
                    )
                    stats = (
                        base_q.filter(
                            PlayerStatistics.player_id.in_(roster_player_ids),
                            gc_clause,
                        )
                        .limit(limit)
                        .all()
                    )

            if not stats:
                # Tier 3: team_name with OR-NULL game_class filter.
                # OR-NULL: rows not yet resolved by roster indexer (gc=None) are
                # included (minor bleed risk from same-named clubs), but confirmed-
                # wrong-gender rows (gc IS NOT NULL AND gc != league.game_class) are
                # excluded. Once the roster indexer runs, team_id will be set and
                # Tier 1 will handle all of this correctly without any bleed.
                team_names = [
                    r[0]
                    for r in session.query(Team.name)
                    .filter(Team.id.in_(all_team_ids), Team.name.isnot(None))
                    .distinct()
                    .all()
                ]
                if not team_names:
                    return []
                gc_clause = (
                    (
                        (PlayerStatistics.game_class == league.game_class)
                        | (PlayerStatistics.game_class == None)  # noqa: E711
                    )
                    if league.game_class
                    else True
                )
                stats = (
                    base_q.filter(
                        PlayerStatistics.team_name.in_(team_names),
                        gc_clause,
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
                    "pen_2": getattr(ps, "pen_2min", 0) or 0,
                    "pen_5": getattr(ps, "pen_5min", 0) or 0,
                    "pen_10": getattr(ps, "pen_10min", 0) or 0,
                    "pen_match": getattr(ps, "pen_match", 0) or 0,
                }
            )
        set_cached(cache_key, result)
        return result


# ---------------------------------------------------------------------------
# 4a. Per-phase top scorer aggregation from GamePlayer rows
# ---------------------------------------------------------------------------


def get_league_top_scorers_by_phase(
    db_league_id: int,
    phase_to_group_ids: dict[str, list[int]],
    limit: int = 100,
) -> dict[str, list[dict]]:
    """
    Build top-scorer lists per canonical phase using per-game GamePlayer rows.

    Returns a dict  { phase_key: [scorer_dict, ...] }  only for phases that
    have at least one GamePlayer row.  If no GamePlayer data exists at all for
    this league, returns {}.

    scorer_dict keys: player_id, player_name, team_name, team_id,
                      gp, g, a, pts, pim
    """
    from collections import defaultdict
    from sqlalchemy import func as _func

    db = get_database_service()
    with db.session_scope() as session:
        # Flat mapping: group_id → phase
        gid_to_phase: dict[int, str] = {}
        for ph, gids in phase_to_group_ids.items():
            for gid in gids:
                gid_to_phase[gid] = ph

        all_group_ids = list(gid_to_phase.keys())
        if not all_group_ids:
            return {}

        # Fetch all played games in this league grouped by group_id
        games_in_groups = (
            session.query(Game.id, Game.group_id)
            .filter(
                Game.group_id.in_(all_group_ids),
                Game.home_score.isnot(None),  # played only
            )
            .all()
        )
        if not games_in_groups:
            return {}

        game_id_to_phase: dict[int, str] = {
            g.id: gid_to_phase[g.group_id] for g in games_in_groups if g.group_id in gid_to_phase
        }
        all_game_ids = list(game_id_to_phase.keys())
        if not all_game_ids:
            return {}

        # Check whether any GamePlayer rows exist for these games
        gp_rows = (
            session.query(
                GamePlayer.game_id,
                GamePlayer.player_id,
                GamePlayer.team_id,
                GamePlayer.goals,
                GamePlayer.assists,
                GamePlayer.penalty_minutes,
            )
            .filter(GamePlayer.game_id.in_(all_game_ids))
            .all()
        )
        if not gp_rows:
            return {}  # no game-level detail → caller will suppress chips

        # Aggregate per (phase, player_id, team_id)
        # key: (phase, player_id, team_id)
        agg: dict[tuple, dict] = {}
        for row in gp_rows:
            ph = game_id_to_phase.get(row.game_id)
            if ph is None:
                continue
            key = (ph, row.player_id, row.team_id)
            if key not in agg:
                agg[key] = {"gp": 0, "g": 0, "a": 0, "pim": 0}
            agg[key]["gp"] += 1
            agg[key]["g"] += row.goals or 0
            agg[key]["a"] += row.assists or 0
            agg[key]["pim"] += row.penalty_minutes or 0

        # Resolve player names and team names
        player_ids = {k[1] for k in agg}
        team_ids = {k[2] for k in agg if k[2]}

        player_names: dict[int, str] = {}
        for pl in session.query(Player).filter(Player.person_id.in_(player_ids)).all():
            player_names[pl.person_id] = pl.full_name or f"Player {pl.person_id}"

        # Get the league's season_id for team name lookup
        league = session.query(League).filter(League.id == db_league_id).first()
        season_id = league.season_id if league else None

        team_names: dict[int, str] = {}
        if team_ids:
            q = session.query(Team).filter(Team.id.in_(team_ids))
            if season_id:
                q = q.filter(Team.season_id == season_id)
            for t in q.all():
                team_names[t.id] = t.name or t.text or f"Team {t.id}"
            # fallback: any season
            missing = team_ids - team_names.keys()
            if missing:
                for t in (
                    session.query(Team).filter(Team.id.in_(missing), Team.name.isnot(None)).all()
                ):
                    team_names.setdefault(t.id, t.name)

        # Build phase → sorted list
        phase_lists: dict[str, list[dict]] = {}
        for (ph, pid, tid), stats in agg.items():
            if ph not in phase_lists:
                phase_lists[ph] = []
            phase_lists[ph].append(
                {
                    "player_id": pid,
                    "player_name": player_names.get(pid, f"Player {pid}"),
                    "team_name": team_names.get(tid, "Unknown") if tid else "Unknown",
                    "team_id": tid,
                    "gp": stats["gp"],
                    "g": stats["g"],
                    "a": stats["a"],
                    "pts": stats["g"] + stats["a"],
                    "pim": stats["pim"],
                }
            )

        result: dict[str, list[dict]] = {}
        for ph, rows in phase_lists.items():
            rows.sort(key=lambda x: (-x["pts"], -x["g"]))
            # re-rank and trim
            for i, r in enumerate(rows[:limit], 1):
                r["rank"] = i
            result[ph] = rows[:limit]

        return result


# ---------------------------------------------------------------------------
# 4. Top penalties per league
# ---------------------------------------------------------------------------


def get_league_top_penalties(db_league_id: int, limit: int = 100) -> list[dict]:
    """
    Top penalty-minute leaders for a league, ordered by PIM descending.

    Uses the same filtering strategy as get_league_top_scorers (GamePlayer
    primary path, 3-tier fallback) but orders by penalty_minutes DESC and
    only returns rows where penalty_minutes > 0.
    """
    cache_key = ("league_penalties", db_league_id, limit)
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    import re as _re

    db = get_database_service()
    with db.session_scope() as session:
        league = (
            session.query(League)
            .options(joinedload(League.groups))
            .filter(League.id == db_league_id)
            .first()
        )
        if league is None:
            return []

        group_ids = [g.id for g in league.groups]
        if not group_ids:
            return []

        game_ids = [r[0] for r in session.query(Game.id).filter(Game.group_id.in_(group_ids)).all()]

        league_abbrev = _re.sub(
            r"^(Junioren/-innen|Junioren|Juniorinnen|Herren|Damen|Senioren)\s+",
            "",
            str(league.name or ""),
        ).strip()

        player_ids = []
        if game_ids:
            player_ids = [
                r[0]
                for r in session.query(GamePlayer.player_id)
                .filter(GamePlayer.game_id.in_(game_ids))
                .distinct()
                .all()
            ]

        gc_filters = [
            PlayerStatistics.season_id == league.season_id,
            PlayerStatistics.league_abbrev == league_abbrev,
            PlayerStatistics.penalty_minutes > 0,
        ]
        if league.game_class:
            gc_filters.append(
                (PlayerStatistics.game_class == league.game_class)
                | (PlayerStatistics.game_class == None)  # noqa: E711
            )

        order_col = PlayerStatistics.penalty_minutes.desc()

        if player_ids:
            stats = (
                session.query(PlayerStatistics, Player)
                .join(Player, PlayerStatistics.player_id == Player.person_id)
                .filter(
                    PlayerStatistics.player_id.in_(player_ids),
                    *gc_filters,
                )
                .order_by(order_col)
                .limit(limit)
                .all()
            )
        else:
            home_ids = {
                r[0]
                for r in session.query(Game.home_team_id).filter(Game.group_id.in_(group_ids)).all()
            }
            away_ids = {
                r[0]
                for r in session.query(Game.away_team_id).filter(Game.group_id.in_(group_ids)).all()
            }
            all_team_ids = list((home_ids | away_ids) - {None})
            if not all_team_ids:
                return []

            base_q = (
                session.query(PlayerStatistics, Player)
                .join(Player, PlayerStatistics.player_id == Player.person_id)
                .filter(
                    PlayerStatistics.season_id == league.season_id,
                    PlayerStatistics.league_abbrev == league_abbrev,
                    PlayerStatistics.penalty_minutes > 0,
                )
                .order_by(order_col)
            )

            def _run(extra_filter):
                return base_q.filter(extra_filter).limit(limit).all()

            stats = _run(PlayerStatistics.team_id.in_(all_team_ids))

            if not stats:
                roster_player_ids = [
                    r[0]
                    for r in session.query(TeamPlayer.player_id)
                    .filter(
                        TeamPlayer.team_id.in_(all_team_ids),
                        TeamPlayer.season_id == league.season_id,
                    )
                    .distinct()
                    .all()
                ]
                if roster_player_ids:
                    gc_clause = (
                        (
                            (PlayerStatistics.game_class == league.game_class)
                            | (PlayerStatistics.game_class == None)  # noqa: E711
                        )
                        if league.game_class
                        else True
                    )
                    stats = (
                        base_q.filter(
                            PlayerStatistics.player_id.in_(roster_player_ids),
                            gc_clause,
                        )
                        .limit(limit)
                        .all()
                    )

            if not stats:
                team_names = [
                    r[0]
                    for r in session.query(Team.name)
                    .filter(Team.id.in_(all_team_ids), Team.name.isnot(None))
                    .distinct()
                    .all()
                ]
                if not team_names:
                    return []
                gc_clause = (
                    (
                        (PlayerStatistics.game_class == league.game_class)
                        | (PlayerStatistics.game_class == None)  # noqa: E711
                    )
                    if league.game_class
                    else True
                )
                stats = (
                    base_q.filter(
                        PlayerStatistics.team_name.in_(team_names),
                        gc_clause,
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
                    "pen_2": getattr(ps, "pen_2min", 0) or 0,
                    "pen_5": getattr(ps, "pen_5min", 0) or 0,
                    "pen_10": getattr(ps, "pen_10min", 0) or 0,
                    "pen_match": getattr(ps, "pen_match", 0) or 0,
                }
            )
        set_cached(cache_key, result)
        return result


def get_overall_top_scorers(season_id: Optional[int] = None, limit: int = 20) -> list[dict]:
    """
    Overall top scorers across all leagues in a season.

    Returns players with the highest points from PlayerStatistics,
    aggregating across all teams they played for in the season.
    Includes the league where they played most games.
    """
    from app.services.database import get_database_service
    from app.models.db_models import PlayerStatistics, Player, League
    from sqlalchemy import func

    cache_key = ("top_scorers", season_id, limit)
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    if season_id is None:
        from app.main import get_current_season

        season_id = get_current_season()

    db = get_database_service()
    with db.session_scope() as session:
        # Build team_name → gender via Game→LeagueGroup→League (avoids ambiguous abbrev)
        _GC_GENDER = {11: "M", 21: "W"}
        team_gender: dict[str, str] = {}
        for _tname, _gc in (
            session.query(Team.name, League.game_class)
            .join(
                Game,
                or_(
                    (Game.home_team_id == Team.id) & (Game.season_id == Team.season_id),
                    (Game.away_team_id == Team.id) & (Game.season_id == Team.season_id),
                ),
            )
            .join(LeagueGroup, LeagueGroup.id == Game.group_id)
            .join(League, League.id == LeagueGroup.league_id)
            .filter(League.season_id == season_id, League.game_class.in_([11, 21]))
            .distinct()
            .all()
        ):
            if _tname:
                team_gender[_tname] = _GC_GENDER[_gc]

        # Aggregate stats per player across all teams
        stats = (
            session.query(
                PlayerStatistics.player_id,
                Player.full_name,
                func.sum(PlayerStatistics.games_played).label("gp"),
                func.sum(PlayerStatistics.goals).label("g"),
                func.sum(PlayerStatistics.assists).label("a"),
                func.sum(PlayerStatistics.points).label("pts"),
                func.sum(PlayerStatistics.penalty_minutes).label("pim"),
            )
            .join(Player, PlayerStatistics.player_id == Player.person_id)
            .filter(PlayerStatistics.season_id == season_id)
            .group_by(PlayerStatistics.player_id, Player.full_name)
            .order_by(
                func.sum(PlayerStatistics.points).desc(), func.sum(PlayerStatistics.goals).desc()
            )
            .limit(limit)
            .all()
        )

        # Batch-fetch primary team for all players in one query (replaces N+1 loop)
        player_ids = [row[0] for row in stats]
        all_ps_rows = (
            session.query(
                PlayerStatistics.player_id,
                PlayerStatistics.team_name,
                PlayerStatistics.team_id,
                PlayerStatistics.league_abbrev,
                PlayerStatistics.games_played,
            )
            .filter(
                PlayerStatistics.player_id.in_(player_ids),
                PlayerStatistics.season_id == season_id,
            )
            .all()
        )
        # Build lookup: player_id → row with highest games_played
        ps_by_player: dict[int, Any] = {}
        for ps_row in all_ps_rows:
            pid = ps_row[0]
            if pid not in ps_by_player or ps_row[4] > ps_by_player[pid][4]:
                ps_by_player[pid] = ps_row

        result = []
        for i, (player_id, full_name, gp, g, a, pts, pim) in enumerate(stats, 1):
            primary = ps_by_player.get(player_id)
            team_name = primary[1] if primary else "Unknown"
            team_id = primary[2] if primary else None
            league_abbrev = primary[3] if primary else None
            result.append(
                {
                    "rank": i,
                    "player_id": player_id,
                    "player_name": full_name or f"Player {player_id}",
                    "team_name": team_name or "Unknown",
                    "team_id": team_id,
                    "league": league_abbrev or "",
                    "gender": team_gender.get(team_name or "", ""),
                    "gp": gp or 0,
                    "g": g or 0,
                    "a": a or 0,
                    "pts": pts or 0,
                    "pim": pim or 0,
                }
            )

        set_cached(cache_key, result)
        return result


# ---------------------------------------------------------------------------
# 4. Player stats leaderboard (all teams / season)
# ---------------------------------------------------------------------------


def get_player_leaderboard(
    season_id: Optional[int] = None,
    team_id: Optional[int] = None,
    game_class: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    order_by: str = "points",
) -> dict:
    """
    Global player stats leaderboard for a season, optionally filtered by team or game_class.
    game_class: 11 = men (Herren) only, 21 = women (Damen) only; None = all
    order_by: 'points' | 'goals' | 'assists' | 'pim'
    """
    from sqlalchemy import func as _func

    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        gp_sum = _func.sum(PlayerStatistics.games_played)
        g_sum = _func.sum(PlayerStatistics.goals)
        a_sum = _func.sum(PlayerStatistics.assists)
        pts_sum = _func.sum(PlayerStatistics.points)
        pim_sum = _func.sum(PlayerStatistics.penalty_minutes)

        order_expr = {
            "goals": g_sum.desc(),
            "assists": a_sum.desc(),
            "pim": pim_sum.desc(),
        }.get(order_by, pts_sum.desc())

        base_filter = [PlayerStatistics.season_id == season_id]
        if team_id is not None:
            base_filter.append(
                PlayerStatistics.team_name.in_(session.query(Team.name).filter(Team.id == team_id))
            )
        if game_class is not None:
            gc_team_names = (
                session.query(Team.name)
                .filter(
                    Team.season_id == season_id,
                    Team.game_class == game_class,
                    Team.name.isnot(None),
                )
                .distinct()
            )
            base_filter.append(PlayerStatistics.team_name.in_(gc_team_names))

        total = (
            session.query(_func.count(_func.distinct(PlayerStatistics.player_id)))
            .filter(*base_filter)
            .scalar()
        ) or 0

        rows = (
            session.query(
                PlayerStatistics.player_id,
                Player.full_name,
                gp_sum.label("gp"),
                g_sum.label("g"),
                a_sum.label("a"),
                pts_sum.label("pts"),
                pim_sum.label("pim"),
            )
            .join(Player, PlayerStatistics.player_id == Player.person_id)
            .filter(*base_filter)
            .group_by(PlayerStatistics.player_id, Player.full_name)
            .order_by(order_expr, g_sum.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        # Build team_name → gender via Game→LeagueGroup→League (avoids ambiguous abbrev)
        _GC_GENDER = {11: "M", 21: "W"}
        team_gender: dict[str, str] = {}
        for _tname, _gc in (
            session.query(Team.name, League.game_class)
            .join(
                Game,
                or_(
                    (Game.home_team_id == Team.id) & (Game.season_id == Team.season_id),
                    (Game.away_team_id == Team.id) & (Game.season_id == Team.season_id),
                ),
            )
            .join(LeagueGroup, LeagueGroup.id == Game.group_id)
            .join(League, League.id == LeagueGroup.league_id)
            .filter(League.season_id == season_id, League.game_class.in_([11, 21]))
            .distinct()
            .all()
        ):
            if _tname:
                team_gender[_tname] = _GC_GENDER[_gc]

        result = []
        for i, (player_id, full_name, gp, g, a, pts, pim) in enumerate(rows, offset + 1):
            primary = (
                session.query(PlayerStatistics.team_name, PlayerStatistics.league_abbrev)
                .filter(
                    PlayerStatistics.player_id == player_id, PlayerStatistics.season_id == season_id
                )
                .order_by(PlayerStatistics.games_played.desc())
                .first()
            )
            _abbrev = (primary[1] if primary else None) or ""
            result.append(
                {
                    "rank": i,
                    "player_id": player_id,
                    "player_name": full_name or f"Player {player_id}",
                    "team_name": (primary[0] if primary else None) or "—",
                    "league": _abbrev,
                    "gender": team_gender.get((primary[0] if primary else None) or "", ""),
                    "gp": gp or 0,
                    "g": g or 0,
                    "a": a or 0,
                    "pts": pts or 0,
                    "pim": pim or 0,
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
            season_id = highlighted or (
                all_season_rows[0][0] if all_season_rows else _get_current_season_id(session)
            )
        elif season_id not in valid_season_ids and all_season_rows:
            season_id = all_season_rows[0][0]

        team = (
            session.query(Team)
            .filter(
                Team.id == team_id,
                Team.season_id == season_id,
            )
            .first()
        )

        if team is None:
            return {}

        # Season and league display labels
        season_row = session.get(Season, season_id)
        season_name = season_row.text if season_row else str(season_id)
        league_row = (
            session.query(League)
            .filter(
                League.league_id == team.league_id,
                League.season_id == team.season_id,
                League.game_class == team.game_class,
            )
            .first()
            if team.league_id is not None
            else None
        )
        league_name = (league_row.name or league_row.text if league_row else None) or ""

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
                    "number": None,
                    "position": None,
                    "gp": 0,
                    "g": 0,
                    "a": 0,
                    "pts": 0,
                    "pim": 0,
                }
            entry = gp_agg[pid]
            if gp.jersey_number and not entry["number"]:
                entry["number"] = gp.jersey_number
            if gp.position and gp.position.lower() not in _UNKNOWN_POS and not entry["position"]:
                entry["position"] = gp.position
            entry["gp"] += 1
            entry["g"] += gp.goals or 0
            entry["a"] += gp.assists or 0
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

        # Use the official roster whenever it exists. Even when official-roster
        # player IDs have zero overlap with game_players (API mismatch — e.g. NLA
        # registration IDs vs cup/game-event IDs), the official roster + its
        # PlayerStatistics entries are always more reliable than showing unrelated
        # game-lineup participants.
        official_pids: set[int] = {pl.person_id for _, pl in tp_rows}
        use_official_roster = bool(tp_rows)

        if use_official_roster:
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
                    # Exclude rows that belong to a different team with the same name
                    # (e.g. women's NLB "Visper Lions" vs men's 3. Liga "Visper Lions").
                    # When team_id is NULL (per-player API path) we can't discriminate,
                    # so we allow those through.
                    or_(
                        PlayerStatistics.team_id == team_id,
                        PlayerStatistics.team_id.is_(None),
                    ),
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
                or_(
                    PlayerStatistics.team_id == team_id,
                    PlayerStatistics.team_id.is_(None),
                ),
            ]
            if team_league_abbrev:
                ps_filter.append(PlayerStatistics.league_abbrev == team_league_abbrev)

            player_stat_map: dict[int, dict] = {}
            for ps in session.query(PlayerStatistics).filter(*ps_filter).all():
                pid = int(ps.player_id)
                if pid not in player_stat_map:
                    player_stat_map[pid] = {"gp": 0, "g": 0, "a": 0, "pts": 0, "pim": 0}
                player_stat_map[pid]["gp"] += ps.games_played or 0
                player_stat_map[pid]["g"] += ps.goals or 0
                player_stat_map[pid]["a"] += ps.assists or 0
                player_stat_map[pid]["pts"] += ps.points or 0
                player_stat_map[pid]["pim"] += ps.penalty_minutes or 0

            for tp, pl in tp_rows:
                ps = player_stat_map.get(pl.person_id) or {}
                gp_info = gp_agg.get(pl.person_id, {})
                # Fill in number / position from game history if blank or unknown
                number = tp.jersey_number or gp_info.get("number")
                pos_raw = tp.position or ""
                position = (
                    pos_raw
                    if pos_raw.lower() not in _UNKNOWN_POS
                    else (gp_info.get("position") or "")
                )
                position = _POS_ABBREV.get(position.lower(), position)
                # Prefer PlayerStatistics for G/A/PTS/PIM; fall back to per-game
                # accumulation from GamePlayer (populated by player_game_stats task)
                # so that the roster shows real numbers even when PlayerStatistics
                # hasn't been indexed yet or has a team-name mismatch.
                gp_val = ps.get("gp") or gp_info.get("gp", 0)
                g_val = ps.get("g") if ps.get("g") else gp_info.get("g", 0)
                a_val = ps.get("a") if ps.get("a") else gp_info.get("a", 0)
                pts_val = ps.get("pts") if ps.get("pts") else (g_val + a_val)
                pim_val = ps.get("pim") if ps.get("pim") else gp_info.get("pim", 0)
                roster.append(
                    {
                        "player_id": pl.person_id,
                        "name": pl.full_name or f"Player {pl.person_id}",
                        "number": number,
                        "position": position,
                        "gp": gp_val,
                        "g": g_val,
                        "a": a_val,
                        "pts": pts_val,
                        "pim": pim_val,
                    }
                )

            # Add players seen in game lineups but absent from the official roster.
            # Exclude players who are officially registered on a DIFFERENT team this
            # season — they are guests/loan players and don't belong here.
            extras_pids = [
                pid for pid in gp_agg if pid not in official_pids and pid not in other_team_pids
            ]
            # Look up PlayerStatistics for these extras (same as official path)
            extras_stat_map: dict[int, dict] = {}
            if extras_pids:
                ps_filter_extras = [
                    PlayerStatistics.player_id.in_(extras_pids),
                    PlayerStatistics.season_id == season_id,
                    PlayerStatistics.team_name == team.name,
                    or_(
                        PlayerStatistics.team_id == team_id,
                        PlayerStatistics.team_id.is_(None),
                    ),
                ]
                if team_league_abbrev:
                    ps_filter_extras.append(PlayerStatistics.league_abbrev == team_league_abbrev)
                for ps in session.query(PlayerStatistics).filter(*ps_filter_extras).all():
                    pid = int(ps.player_id)
                    if pid not in extras_stat_map:
                        extras_stat_map[pid] = {"gp": 0, "g": 0, "a": 0, "pts": 0, "pim": 0}
                    extras_stat_map[pid]["gp"] += ps.games_played or 0
                    extras_stat_map[pid]["g"] += ps.goals or 0
                    extras_stat_map[pid]["a"] += ps.assists or 0
                    extras_stat_map[pid]["pts"] += ps.points or 0
                    extras_stat_map[pid]["pim"] += ps.penalty_minutes or 0
            for pid in extras_pids:
                info = gp_agg[pid]
                ps = extras_stat_map.get(pid) or {}
                g_val = ps.get("g") if ps.get("g") else info["g"]
                a_val = ps.get("a") if ps.get("a") else info["a"]
                pts_val = ps.get("pts") if ps.get("pts") else (g_val + a_val)
                pim_val = ps.get("pim") if ps.get("pim") else info["pim"]
                roster.append(
                    {
                        "player_id": pid,
                        "name": info["name"],
                        "number": info["number"],
                        "position": _POS_ABBREV.get(
                            (info["position"] or "").lower(), info["position"] or ""
                        ),
                        "gp": ps.get("gp") or info["gp"],
                        "g": g_val,
                        "a": a_val,
                        "pts": pts_val,
                        "pim": pim_val,
                        "from_games": True,
                    }
                )
        else:
            # No official roster indexed — build entirely from game lineups,
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
                        "position": _POS_ABBREV.get(
                            (info["position"] or "").lower(), info["position"] or ""
                        ),
                        "gp": info["gp"],
                        "g": info["g"],
                        "a": info["a"],
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
            opp_ids.add(
                int(g.home_team_id) if int(g.away_team_id) == team_id else int(g.away_team_id)
            )

        opp_names: dict[int, str] = {}
        opp_logos: dict[int, str] = {}
        for t in (
            session.query(Team).filter(Team.id.in_(opp_ids), Team.season_id == season_id).all()
        ):
            if t.name is not None or t.text is not None:
                opp_names[int(t.id)] = str(t.name or t.text)
            if t.logo_url:
                opp_logos[int(t.id)] = str(t.logo_url)
        # Cross-season fallback for nameless stubs
        missing_opp = {tid for tid in opp_ids if tid not in opp_names}
        if missing_opp:
            for t in (
                session.query(Team).filter(Team.id.in_(missing_opp), Team.name.isnot(None)).all()
            ):
                opp_names[int(t.id)] = str(t.name)
                if t.logo_url and int(t.id) not in opp_logos:
                    opp_logos[int(t.id)] = str(t.logo_url)

        recent_games = []
        for g in recent_games_raw:
            is_home = int(g.home_team_id) == team_id
            opp_id = int(g.away_team_id) if is_home else int(g.home_team_id)
            my_score = int(g.home_score or 0) if is_home else int(g.away_score or 0)
            opp_score = int(g.away_score or 0) if is_home else int(g.home_score or 0)
            _is_extra = g.period in ("OT", "SO")
            if my_score > opp_score:
                result_label = "OTW" if _is_extra else "W"
            elif my_score < opp_score:
                result_label = "OTL" if _is_extra else "L"
            else:
                result_label = "T"
            recent_games.append(
                {
                    "game_id": g.id,
                    "date": g.game_date.strftime("%Y-%m-%d") if g.game_date else "",
                    "opponent_id": opp_id,
                    "opponent_name": opp_names.get(opp_id, f"Team {opp_id}"),
                    "opponent_logo": opp_logos.get(opp_id, ""),
                    "home_away": "H" if is_home else "A",
                    "score": f"{my_score}:{opp_score}",
                    "result": result_label,
                }
            )

        # ── Group standings: find the DB league id and the group the team plays in
        _league_db_id: int | None = league_row.id if league_row else None
        _team_group_id: int | None = None
        _group_name: str = ""
        if _league_db_id:
            _group_row = (
                session.query(Game.group_id, LeagueGroup.name, LeagueGroup.text)
                .join(LeagueGroup, Game.group_id == LeagueGroup.id)
                .filter(
                    or_(Game.home_team_id == team_id, Game.away_team_id == team_id),
                    Game.season_id == season_id,
                    Game.group_id.isnot(None),
                )
                .first()
            )
            if _group_row:
                _team_group_id = _group_row[0]
                _group_name = _group_row[1] or _group_row[2] or ""

        _result_data = {
            "id": team.id,
            "name": team.name or team.text or f"Team {team_id}",
            "logo_url": team.logo_url or "",
            "season_id": season_id,
            "season_name": season_name,
            "league_id": team.league_id,
            "league_name": league_name,
            "game_class": team.game_class,
            "available_seasons": available_seasons,
            "roster": roster,
            "roster_source": roster_source,
            "recent_games": recent_games,
            "upcoming_games": _get_team_upcoming(session, team_id, season_id or 0),
            "standings": [],
            "group_name": _group_name,
        }

    # Fetch standings outside the session scope (get_league_standings opens its own session)
    if _league_db_id:
        try:
            _result_data["standings"] = get_league_standings(
                _league_db_id,
                only_group_ids=[_team_group_id] if _team_group_id else None,
            )
        except Exception:
            pass

    return _result_data


def _get_team_upcoming(session, team_id: int, season_id: int) -> list[dict]:
    """Return upcoming (unscored) games for a team."""
    from datetime import date as _date

    uq = (
        session.query(Game)
        .filter(
            or_(Game.home_team_id == team_id, Game.away_team_id == team_id),
            Game.season_id == season_id,
            Game.home_score.is_(None),
            Game.status != "cancelled",
            Game.game_date.isnot(None),
            Game.game_date >= _date.today(),
        )
        .order_by(Game.game_date.asc())
        .limit(10)
        .all()
    )
    opp_ids = {g.home_team_id if g.away_team_id == team_id else g.away_team_id for g in uq}
    opp_names: dict[int, str] = {}
    opp_logos: dict[int, str] = {}
    for t in session.query(Team).filter(Team.id.in_(opp_ids), Team.season_id == season_id).all():
        if t.name or t.text:
            opp_names[t.id] = t.name or t.text
        if t.logo_url:
            opp_logos[t.id] = t.logo_url
    result = []
    for g in uq:
        is_home = g.home_team_id == team_id
        opp_id = g.away_team_id if is_home else g.home_team_id
        result.append(
            {
                "game_id": g.id,
                "date": g.game_date.strftime("%d.%m.%Y") if g.game_date else "",
                "weekday": g.game_date.strftime("%a") if g.game_date else "",
                "time": g.game_time or "",
                "home_away": "H" if is_home else "A",
                "opponent_id": opp_id,
                "opponent_name": opp_names.get(opp_id, f"Team {opp_id}"),
                "opponent_logo": opp_logos.get(opp_id, ""),
            }
        )
    return result


# ---------------------------------------------------------------------------
# 6. Player detail
# ---------------------------------------------------------------------------


def _player_details_stale(
    fetched_at: Optional[datetime],
    _today: Optional[datetime] = None,
) -> bool:
    """Return True if player biographical details need refreshing.

    Data is considered fresh if it was fetched after the most recent August 31st.
    This aligns with the new season registration cycle (September).

    Args:
        fetched_at: The datetime when details were last fetched. None → always stale.
        _today: Override today's date (for testing). Defaults to UTC now.
    """
    if fetched_at is None:
        return True
    today = _today or datetime.now(timezone.utc)
    # Find the most recent Aug 31 (this year if we're past it, else last year)
    aug31_this_year = today.replace(month=8, day=31, hour=0, minute=0, second=0, microsecond=0)
    cutoff = aug31_this_year if today >= aug31_this_year else aug31_this_year.replace(year=today.year - 1)
    # Normalise fetched_at to UTC-aware for comparison
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return fetched_at < cutoff


def _compute_ppg(points: Optional[int], games_played: Optional[int]) -> Optional[float]:
    """Compute points-per-game rounded to 2 decimal places. Returns None if no games."""
    if not games_played:
        return None
    return round((points or 0) / games_played, 2)


_STRIP_PREFIXES = (
    "herren ",
    "damen ",
    "junioren ",
    "juniorinnen ",
    "junioren/-innen ",
    "senioren ",
)


def _fetch_recent_game_rows(session, person_id: int, offset: int = 0, limit: int = 11) -> list[dict]:
    """Fetch recent game appearance rows for a player. Returns list of game dicts."""
    from app.models.db_models import Game as _Game, Team as _Team

    recent_game_rows = (
        session.query(GamePlayer, _Game)
        .join(_Game, GamePlayer.game_id == _Game.id)
        .filter(GamePlayer.player_id == person_id)
        .order_by(_Game.game_date.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    # Preload team names needed
    team_ids_needed = set()
    for _, g in recent_game_rows:
        team_ids_needed.add(g.home_team_id)
        team_ids_needed.add(g.away_team_id)
    team_names = {
        t.id: t.name for t in session.query(_Team).filter(_Team.id.in_(team_ids_needed)).all()
    }

    # Preload group_id → league short name
    group_ids_needed = {g.group_id for _, g in recent_game_rows if g.group_id}
    group_league_abbrev: dict[int, str] = {}
    if group_ids_needed:
        from app.models.db_models import LeagueGroup as _LG, League as _League2

        for grp, lg in (
            session.query(_LG, _League2)
            .join(_League2, _LG.league_id == _League2.id)
            .filter(_LG.id.in_(group_ids_needed))
            .all()
        ):
            lname = lg.name or lg.text or ""
            for pfx in _STRIP_PREFIXES:
                if lname.lower().startswith(pfx):
                    lname = lname[len(pfx):]
                    break
            group_league_abbrev[grp.id] = lname

    rows: list[dict] = []
    for gp, g in recent_game_rows:
        is_home = gp.team_id == g.home_team_id
        opp_id = g.away_team_id if is_home else g.home_team_id
        opp_name = team_names.get(opp_id, f"Team {opp_id}")
        if g.home_score is not None and g.away_score is not None:
            my_score = g.home_score if is_home else g.away_score
            opp_score = g.away_score if is_home else g.home_score
            _is_extra = g.period in ("OT", "SO")
            if my_score > opp_score:
                result_label = "OTW" if _is_extra else "W"
            elif my_score < opp_score:
                result_label = "OTL" if _is_extra else "L"
            else:
                result_label = "D"
            score_str = f"{my_score}–{opp_score}"
        else:
            result_label = ""
            score_str = ""
        rows.append(
            {
                "game_id": g.id,
                "date": g.game_date.strftime("%Y-%m-%d") if g.game_date else "",
                "home_away": "H" if is_home else "A",
                "opponent": opp_name,
                "opponent_id": opp_id,
                "score": score_str,
                "result": result_label,
                "season_id": g.season_id,
                "league": group_league_abbrev.get(g.group_id, "") if g.group_id else "",
                "g": gp.goals,
                "a": gp.assists,
                "pim": gp.penalty_minutes,
            }
        )
    return rows


def get_player_recent_games(person_id: int, offset: int = 0, limit: int = 10) -> dict:
    """Return a page of recent game appearances for a player.

    Returns:
        {"rows": [...], "has_more": bool}
    """
    db = get_database_service()
    with db.session_scope() as session:
        rows = _fetch_recent_game_rows(session, person_id, offset=offset, limit=limit + 1)
    has_more = len(rows) > limit
    return {"rows": rows[:limit], "has_more": has_more}


def get_player_detail(person_id: int, locale: str = "de") -> dict:
    """
    Return player profile + per-season stats across all seasons.
    Uses team_name / league_abbrev text columns (populated since schema migration).
    """
    from app.services.data_indexer import LEAGUE_TIERS

    _DEFAULT_TIER = 99

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
        for lname, lid in session.query(League.name, League.league_id).distinct().all():
            if not lname:
                continue
            t = LEAGUE_TIERS.get(lid, _DEFAULT_TIER)
            short = lname
            for pfx in _STRIP_PREFIXES:
                if short.lower().startswith(pfx):
                    short = short[len(pfx) :]
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

        # Build (season_id, league_abbrev) → league DB id lookup
        # Strip gender/age prefix from League.name to match ps.league_abbrev.
        # Where multiple leagues match (different game_class), keep the one
        # with the smallest game_class (highest tier).
        all_leagues = session.query(
            League.id, League.name, League.season_id, League.game_class, League.league_id
        ).all()
        _league_lookup: dict[tuple, tuple] = {}  # key → (db_id, game_class, api_league_id)
        for ldb_id, lname, lsid, lgc, lapi_id in all_leagues:
            if not lname:
                continue
            short = lname
            for pfx in _STRIP_PREFIXES:
                if short.lower().startswith(pfx):
                    short = short[len(pfx) :]
                    break
            key = (lsid, short)
            # keep lowest game_class (most senior/first match)
            if key not in _league_lookup:
                _league_lookup[key] = (ldb_id, lgc or 999, lapi_id)
            elif (lgc or 999) < _league_lookup[key][1]:
                _league_lookup[key] = (ldb_id, lgc or 999, lapi_id)
        league_id_lookup = {k: v[0] for k, v in _league_lookup.items()}
        # Also: db_league_id → game_class (for gender-exact team disambiguation)
        db_league_to_gc: dict[int, int] = {
            v[0]: v[1] for v in _league_lookup.values() if v[1] != 999
        }

        # Build (league_db_id, team_name) → team_db_id from actual game participation.
        # This is authoritative: a team named "Zug United" in Herren L-UPL games
        # is unambiguously the men's team, regardless of whether game_class is
        # stored on the team row.
        team_by_league_name: dict[tuple, int] = {}
        for _lg_dbid, _t_id, _t_name in (
            session.query(LeagueGroup.league_id, Team.id, Team.name)
            .join(Game, Game.group_id == LeagueGroup.id)
            .join(
                Team,
                or_(
                    (Team.id == Game.home_team_id) & (Team.season_id == Game.season_id),
                    (Team.id == Game.away_team_id) & (Team.season_id == Game.season_id),
                ),
            )
            .filter(Team.name.isnot(None))
            .distinct()
            .all()
        ):
            team_by_league_name[(_lg_dbid, _t_name)] = _t_id

        # Fallback: (season_id, team_name, game_class) and plain (season_id, team_name)
        _all_teams = (
            session.query(Team.id, Team.season_id, Team.name, Team.game_class)
            .filter(Team.name.isnot(None))
            .all()
        )
        team_id_by_gc: dict[tuple, int] = {}  # (season_id, team_name, game_class) → team_db_id
        team_id_fallback: dict[tuple, int] = {}  # (season_id, team_name) → team_db_id
        for t_id, t_sid, t_name, t_gc in _all_teams:
            if t_gc:
                team_id_by_gc[(t_sid, t_name, t_gc)] = t_id
            team_id_fallback[(t_sid, t_name)] = t_id

        career: list[dict] = []
        for ps, season in stats_rows:
            _abbrev = ps.league_abbrev or ""
            _team_name = ps.team_name or "—"
            _league_db_id = league_id_lookup.get((season.id, _abbrev))
            # Resolve team in priority order:
            # 1. game-participation lookup (league_db_id, team_name) — unambiguous by league
            # 2. (season, name, game_class) — gender-exact when game_class is indexed on Team
            # 3. (season, name) fallback
            _gc = db_league_to_gc.get(_league_db_id) if _league_db_id else None
            _team_db_id = (
                (_league_db_id and team_by_league_name.get((_league_db_id, _team_name)))
                or (_gc and team_id_by_gc.get((season.id, _team_name, _gc)))
                or team_id_fallback.get((season.id, _team_name))
            )
            career.append(
                {
                    "season_text": season.text or str(season.id),
                    "season_id": season.id,
                    "team_name": _team_name,
                    "league": _abbrev,
                    "team_id": ps.team_id,
                    "team_db_id": _team_db_id,
                    "league_db_id": _league_db_id,
                    "gp": ps.games_played,
                    "g": ps.goals,
                    "a": ps.assists,
                    "pts": ps.points,
                    "pim": ps.penalty_minutes,
                    "ppg": _compute_ppg(ps.points, ps.games_played),
                    "_tier": abbrev_tier.get(_abbrev, _DEFAULT_TIER),
                }
            )

        # Sort: most recent season first, then by tier (best league first) within season
        career.sort(key=lambda r: (-r["season_id"], r["_tier"]))
        for r in career:
            r.pop("_tier", None)

        # Career totals
        total_gp = sum(r["gp"] for r in career)
        total_pts = sum(r["pts"] for r in career)
        totals = {
            "gp": total_gp,
            "g": sum(r["g"] for r in career),
            "a": sum(r["a"] for r in career),
            "pts": total_pts,
            "pim": sum(r["pim"] for r in career),
            "ppg": _compute_ppg(total_pts, total_gp),
        }

        # Recent game appearances (last 10 across all seasons, most recent first)
        _recent_rows = _fetch_recent_game_rows(session, person_id, offset=0, limit=11)
        recent_games = _recent_rows[:10]
        recent_has_more = len(_recent_rows) > 10

        result = {
            "person_id": player.person_id,
            "name": player.full_name or f"Player {player.person_id}",
            "first_name": player.first_name or "",
            "last_name": player.last_name or "",
            "year_of_birth": player.year_of_birth,
            "career": career,
            "totals": totals,
            "recent_games": recent_games,
            "recent_has_more": recent_has_more,
            # Biographical cache fields (populated from DB if already fetched)
            "photo_url": player.photo_url,
            "height_cm": player.height_cm,
            "weight_kg": player.weight_kg,
            "position_raw": player.position_raw,
            "license_raw": player.license_raw,
            "player_details_fetched_at": player.player_details_fetched_at,
            # Translated fields — populated after API check below
            "position": None,
            "license": None,
        }

    # Fetch/refresh biographical data if stale (TTL: end of August each year).
    # First page load for a player will be slightly slower (one API call);
    # all subsequent loads are fast from DB until next end-of-August refresh.
    try:
        from app.services.swissunihockey import get_swissunihockey_client
        from app.lib.player_translations import translate_position, translate_license

        if _player_details_stale(result.get("player_details_fetched_at")):
            client = get_swissunihockey_client()
            api_data = client.get_player_details(person_id)
            regions = api_data.get("data", {}).get("regions", [])
            if regions:
                cells = regions[0].get("rows", [{}])[0].get("cells", [])
                if cells:
                    def _cell_text(idx):
                        if idx >= len(cells):
                            return None
                        cell = cells[idx]
                        texts = cell.get("text", []) if isinstance(cell, dict) else []
                        if isinstance(texts, list):
                            return str(texts[0]).strip() if texts else None
                        return str(texts).strip() or None

                    photo_url = None
                    img = cells[0].get("image", {}) if isinstance(cells[0], dict) else {}
                    photo_url = img.get("url") or None

                    position_raw = _cell_text(3)
                    year_of_birth_str = _cell_text(4)
                    height_str = _cell_text(5)   # e.g. "179 cm"
                    weight_str = _cell_text(6)   # e.g. "70 kg"
                    license_raw = _cell_text(7)

                    def _parse_int_prefix(s):
                        """Parse leading integer from strings like '179 cm' → 179."""
                        if not s:
                            return None
                        try:
                            return int(s.split()[0])
                        except (ValueError, IndexError):
                            return None

                    height_cm = _parse_int_prefix(height_str)
                    weight_kg = _parse_int_prefix(weight_str)

                    # Backfill year_of_birth if missing
                    if not result["year_of_birth"] and year_of_birth_str:
                        try:
                            yob = int(year_of_birth_str)
                            if 1950 <= yob <= 2025:
                                result["year_of_birth"] = yob
                        except (ValueError, TypeError):
                            pass

                    result["photo_url"] = photo_url
                    result["height_cm"] = height_cm
                    result["weight_kg"] = weight_kg
                    result["position_raw"] = position_raw
                    result["license_raw"] = license_raw

                    # Persist to DB
                    db = get_database_service()
                    with db.session_scope() as session:
                        player_row = session.query(Player).filter(
                            Player.person_id == person_id
                        ).first()
                        if player_row:
                            player_row.photo_url = photo_url
                            player_row.height_cm = height_cm
                            player_row.weight_kg = weight_kg
                            player_row.position_raw = position_raw
                            player_row.license_raw = license_raw
                            player_row.player_details_fetched_at = datetime.now(timezone.utc)
                            if not player_row.year_of_birth and result["year_of_birth"]:
                                player_row.year_of_birth = result["year_of_birth"]

        # Apply translations using the request locale
        result["position"] = translate_position(result.get("position_raw"), locale)
        result["license"] = translate_license(result.get("license_raw"), locale)

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
    if season_id is None:
        with db.session_scope() as session:
            season_id = _get_current_season_id(session)

    key = ("upcoming_games", season_id, league_category, limit)
    cached = get_cached(key)
    if cached is not None:
        return cached

    with db.session_scope() as session:
        today = _date.today()
        q = session.query(Game).filter(
            Game.season_id == season_id,
            Game.home_score.is_(None),
            Game.status != "cancelled",
            Game.game_date.isnot(None),
            Game.game_date >= today,
        )

        # Filter by league category (e.g., "2_11" = NLB Men)
        if league_category and league_category != "all":
            parts = league_category.split("_")
            if len(parts) == 2:
                try:
                    league_id = int(parts[0])
                    game_class = int(parts[1])
                    # Join through LeagueGroup to League
                    q = (
                        q.join(LeagueGroup, Game.group_id == LeagueGroup.id)
                        .join(League, LeagueGroup.league_id == League.id)
                        .filter(League.league_id == league_id, League.game_class == game_class)
                    )
                except ValueError:
                    pass  # Invalid format, ignore filter
        elif league_ids:
            # Legacy filtering by league IDs
            q = q.join(LeagueGroup, Game.group_id == LeagueGroup.id).filter(
                LeagueGroup.league_id.in_(league_ids)
            )

        games_raw = q.order_by(Game.game_date.asc()).limit(limit).all()

        if not games_raw:
            set_cached(key, [])
            return []

        team_ids = {g.home_team_id for g in games_raw} | {g.away_team_id for g in games_raw}
        t_names: dict = {}
        for t in (
            session.query(Team).filter(Team.id.in_(team_ids), Team.season_id == season_id).all()
        ):
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
        grp_label: dict = {}  # Combined "M NLB · Gruppe 1" label
        for grp in session.query(LeagueGroup).filter(LeagueGroup.id.in_(group_ids)).all():
            lg = session.query(League).filter(League.id == grp.league_id).first()
            grp_league[grp.id] = lg.name if lg else ""
            grp_name[grp.id] = grp.name or grp.text or ""
            if lg:
                grp_league_category[grp.id] = f"{lg.league_id}_{lg.game_class}"
            # Build short label line 1: "M - U16A" / "W - NLA" etc.
            # Strip common prefixes and collapse spaces ("U16 A" → "U16A")
            gc = int(lg.game_class) if lg and lg.game_class is not None else None
            lg_raw = str(lg.name or lg.text or "") if lg else ""
            mw = _mw_from_league(gc, lg_raw)
            for pfx in ("Herren ", "Damen ", "Junioren ", "Juniorinnen "):
                lg_raw = lg_raw.replace(pfx, "")
            lg_short = lg_raw.replace(" ", "").strip()  # "U16 A" → "U16A"
            grp_text = grp.name or grp.text or ""
            label_parts = [p for p in [mw, lg_short] if p]
            grp_label[grp.id] = " - ".join(label_parts)

        result = [
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
                "league_label": grp_label.get(g.group_id, ""),
                "league_category": grp_league_category.get(g.group_id, ""),
            }
            for g in games_raw
        ]
        set_cached(key, result)
        return result


def get_schedule(
    season_id: Optional[int] = None,
    sex: str = "all",
    age: str = "all",
    field: str = "all",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Paginated upcoming games (no score yet) ordered by date, for the schedule page."""
    from datetime import date as _date

    # Map filter dimensions → sets of valid game_class values
    _SEX_GC: dict[str, set[int]] = {
        "women": {21, 22, 26, 28, 41, 42, 43, 44},
        "mixed": {49},
        "men": {11, 12, 14, 16, 18, 19, 31, 32, 33, 34, 35, 51},
    }
    _AGE_GC: dict[str, set[int]] = {
        "senior": {11, 12, 21, 22},
        "U21": {19, 26},
        "U18": {18, 31, 41},
        "U16": {16, 28, 32, 42},
        "U14": {14, 33, 43, 49},
        "U12": {34, 36, 44},
        "U10": {35},
        "senioren": {51},
    }
    _FIELD_GC: dict[str, set[int]] = {
        "big": {11, 21, 14, 16, 18, 19, 26, 28, 49},
        "small": {12, 22, 31, 32, 33, 34, 35, 36, 41, 42, 43, 44, 51},
    }

    active_gc: Optional[set] = None
    for val, mapping in [(sex, _SEX_GC), (age, _AGE_GC), (field, _FIELD_GC)]:
        if val and val != "all" and val in mapping:
            s = mapping[val]
            active_gc = s if active_gc is None else active_gc & s

    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        today = _date.today()
        base_q = session.query(Game).filter(
            Game.season_id == season_id,
            Game.home_score.is_(None),
            Game.status != "cancelled",
            Game.game_date.isnot(None),
            Game.game_date >= today,
        )

        if active_gc is not None:
            base_q = (
                base_q.join(LeagueGroup, Game.group_id == LeagueGroup.id)
                .join(League, LeagueGroup.league_id == League.id)
                .filter(League.game_class.in_(list(active_gc)))
            )

        total = base_q.count()
        games_raw = (
            base_q.order_by(Game.game_date.asc(), Game.game_time.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        if not games_raw:
            return {"games": [], "total": total}

        team_ids = {g.home_team_id for g in games_raw} | {g.away_team_id for g in games_raw}
        t_names: dict = {}
        for t in (
            session.query(Team).filter(Team.id.in_(team_ids), Team.season_id == season_id).all()
        ):
            t_names[t.id] = t.name or t.text or f"Team {t.id}"
        missing = team_ids - t_names.keys()
        if missing:
            for t in session.query(Team).filter(Team.id.in_(missing), Team.name.isnot(None)).all():
                t_names.setdefault(t.id, t.name)

        group_ids = {g.group_id for g in games_raw}
        grp_league: dict = {}
        grp_label: dict = {}
        grp_league_category: dict = {}
        for grp, lg in (
            session.query(LeagueGroup, League)
            .outerjoin(League, League.id == LeagueGroup.league_id)
            .filter(LeagueGroup.id.in_(group_ids))
            .all()
        ):
            grp_league[grp.id] = lg.name if lg else ""
            if lg:
                grp_league_category[grp.id] = f"{lg.league_id}_{lg.game_class}"
            gc = int(lg.game_class) if lg and lg.game_class is not None else None
            lg_raw = str(lg.name or lg.text or "") if lg else ""
            mw = _mw_from_league(gc, lg_raw)
            for pfx in ("Herren ", "Damen ", "Junioren ", "Juniorinnen "):
                lg_raw = lg_raw.replace(pfx, "")
            lg_short = lg_raw.replace(" ", "").strip()
            label_parts = [p for p in [mw, lg_short] if p]
            grp_label[grp.id] = " - ".join(label_parts)

        return {
            "games": [
                {
                    "game_id": g.id,
                    "date": g.game_date.strftime("%d.%m.%Y") if g.game_date else "",
                    "weekday": g.game_date.strftime("%a") if g.game_date else "",
                    "time": g.game_time or "",
                    "home_team": t_names.get(g.home_team_id, f"Team {g.home_team_id}"),
                    "away_team": t_names.get(g.away_team_id, f"Team {g.away_team_id}"),
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "league": grp_league.get(g.group_id, ""),
                    "league_label": grp_label.get(g.group_id, ""),
                    "league_category": grp_league_category.get(g.group_id, ""),
                }
                for g in games_raw
            ],
            "total": total,
        }


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
    if season_id is None:
        with db.session_scope() as session:
            season_id = _get_current_season_id(session)

    key = ("latest_results", season_id, league_category, limit)
    cached = get_cached(key)
    if cached is not None:
        return cached

    with db.session_scope() as session:
        today = _date.today()
        q = session.query(Game).filter(
            Game.season_id == season_id,
            Game.home_score.isnot(None),  # Has score = completed
            Game.game_date.isnot(None),
            Game.game_date <= today,
        )

        # Filter by league category (e.g., "2_11" = NLB Men)
        if league_category and league_category != "all":
            parts = league_category.split("_")
            if len(parts) == 2:
                try:
                    league_id = int(parts[0])
                    game_class = int(parts[1])
                    # Join through LeagueGroup to League
                    q = (
                        q.join(LeagueGroup, Game.group_id == LeagueGroup.id)
                        .join(League, LeagueGroup.league_id == League.id)
                        .filter(League.league_id == league_id, League.game_class == game_class)
                    )
                except ValueError:
                    pass  # Invalid format, ignore filter
        elif league_ids:
            # Legacy filtering by league IDs
            q = q.join(LeagueGroup, Game.group_id == LeagueGroup.id).filter(
                LeagueGroup.league_id.in_(league_ids)
            )

        games_raw = q.order_by(Game.game_date.desc()).limit(limit).all()

        if not games_raw:
            set_cached(key, [])
            return []

        team_ids = {g.home_team_id for g in games_raw} | {g.away_team_id for g in games_raw}
        t_names: dict = {}
        for t in (
            session.query(Team).filter(Team.id.in_(team_ids), Team.season_id == season_id).all()
        ):
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
        grp_label: dict = {}  # Combined "M NLB · Gruppe 1" label
        for grp in session.query(LeagueGroup).filter(LeagueGroup.id.in_(group_ids)).all():
            lg = session.query(League).filter(League.id == grp.league_id).first()
            grp_league[grp.id] = lg.name if lg else ""
            grp_name[grp.id] = grp.name or grp.text or ""
            if lg:
                grp_league_category[grp.id] = f"{lg.league_id}_{lg.game_class}"
            # Build short label line 1: "M - U16A" / "W - NLA" etc.
            # Strip common prefixes and collapse spaces ("U16 A" → "U16A")
            gc = int(lg.game_class) if lg and lg.game_class is not None else None
            lg_raw = str(lg.name or lg.text or "") if lg else ""
            mw = _mw_from_league(gc, lg_raw)
            for pfx in ("Herren ", "Damen ", "Junioren ", "Juniorinnen "):
                lg_raw = lg_raw.replace(pfx, "")
            lg_short = lg_raw.replace(" ", "").strip()  # "U16 A" → "U16A"
            grp_text = grp.name or grp.text or ""
            label_parts = [p for p in [mw, lg_short] if p]
            grp_label[grp.id] = " - ".join(label_parts)

        result = [
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
                "league_label": grp_label.get(g.group_id, ""),
                "league_category": grp_league_category.get(g.group_id, ""),
            }
            for g in games_raw
        ]
        set_cached(key, result)
        return result


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


_PERIOD_OFFSETS: dict[int | str, int] = {1: 0, 2: 1200, 3: 2400, "OT": 3600}


def _period_offset(period) -> int:
    """Return the start offset in seconds for a period number or label."""
    if isinstance(period, str):
        key = period.upper()
        if key in ("OT", "SO"):
            return _PERIOD_OFFSETS["OT"]
    try:
        p = int(period)
        return _PERIOD_OFFSETS.get(p if p <= 3 else "OT", 0)
    except (TypeError, ValueError):
        return 0


_REGULAR_DURATION = 3600  # 60 minutes in seconds
_OT_DURATION = 4200  # 70 minutes in seconds (10-min OT)


def _parse_time_seconds(time_str: str) -> int:
    """Parse 'MM:SS' into total seconds. Returns 0 on bad input."""
    parts = (time_str or "").split(":")
    if len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
    return 0


def build_timeline_events(
    goals: list[dict],
    penalties: list[dict],
    home_name: str,
    away_name: str,
) -> tuple[list[dict], int]:
    """
    Convert goals/penalties into timeline event dicts with percentage positions.

    Returns (events, total_seconds) where:
      - events is sorted by pct ascending
      - total_seconds is 3600 (regular) or 4200 (OT present)
    """

    def _is_ot_period(period, time_str: str = "") -> bool:
        if isinstance(period, str) and period.upper() in ("OT", "SO"):
            return True
        try:
            return int(period) > 3
        except (TypeError, ValueError):
            pass
        # period=None means the time is an absolute game clock — derive from time
        if period is None and time_str:
            derived = _period_from_time(time_str)
            return derived is not None and derived.upper() in ("OT", "PS")
        return False

    has_ot = any(_is_ot_period(g.get("period"), g.get("time", "")) for g in goals) or any(
        _is_ot_period(p.get("period"), p.get("time", "")) for p in penalties
    )
    total_seconds = _OT_DURATION if has_ot else _REGULAR_DURATION

    def _team_side(team_label: str) -> str:
        if team_label == home_name:
            return "home"
        if team_label == away_name:
            return "away"
        return "unknown"

    events: list[dict] = []

    # own_goal is intentionally not used here: stats_service already assigned
    # the correct team label (the team that benefited from the own goal),
    # so team_side classification is correct without special-casing.
    for i, g in enumerate(goals):
        abs_s = _period_offset(g.get("period")) + _parse_time_seconds(g.get("time", ""))
        pct = min(100.0, max(0.0, abs_s / total_seconds * 100))
        # Shootout events are pinned at the right edge
        if isinstance(g.get("period"), str) and g["period"].upper() == "SO":
            pct = 100.0
        team = g.get("team", "")
        player = g.get("player", "") or ""
        label = f"GOAL - {g.get('time', '')} — {team}"
        if player:
            label += f" · {player}"
        events.append(
            {
                "id": f"goal-{i}",
                "kind": "goal",
                "team_side": _team_side(team),
                "pct": round(pct, 4),
                "label": label,
            }
        )

    for i, p in enumerate(penalties):
        abs_s = _period_offset(p.get("period")) + _parse_time_seconds(p.get("time", ""))
        pct = min(100.0, max(0.0, abs_s / total_seconds * 100))
        # Shootout events are pinned at the right edge
        if isinstance(p.get("period"), str) and p["period"].upper() == "SO":
            pct = 100.0
        team = p.get("team", "")
        player = p.get("player", "") or ""
        minutes = p.get("minutes", 0)
        infraction = p.get("infraction", "") or ""
        label = f"PEN - {p.get('time', '')} — {team}"
        if player:
            label += f" · {player}"
        label += f" ({minutes} min, {infraction})" if infraction else f" ({minutes} min)"
        events.append(
            {
                "id": f"pen-{i}",
                "kind": "penalty",
                "team_side": _team_side(team),
                "pct": round(pct, 4),
                "label": label,
            }
        )

    events.sort(key=lambda e: e["pct"])
    return events, total_seconds


def get_game_box_score(game_id: int) -> dict:
    """
    Parse game_events for a game and return a structured box score dict.
    """
    db = get_database_service()
    with db.session_scope() as session:
        game = session.query(Game).filter(Game.id == game_id).first()
        if game is None:
            return {}

        # Load team names + logos
        _team_cache: dict[int, Team] = {}

        def _get_team(tid: int):
            if tid not in _team_cache:
                _team_cache[tid] = (
                    session.query(Team)
                    .filter(
                        Team.id == tid,
                        Team.season_id == game.season_id,
                    )
                    .first()
                )
            return _team_cache.get(tid)

        def _team_name(tid: int) -> str:
            if tid is None:
                return "?"
            t = _get_team(tid)
            return (t.name if t else None) or f"Team {tid}"

        def _team_logo(tid: int) -> str:
            t = _get_team(tid)
            return (t.logo_url if t else None) or ""

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
            # Keep ev.period as-is for timeline events: None means the time is an
            # absolute game clock, so build_timeline_events must NOT add a period
            # offset.  Use the derived period only for period_markers (display only).
            period = ev.period
            derived_period = period or _period_from_time(time_str)

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
                period_markers.append(
                    {"time": time_str, "label": ev_type, "period": derived_period}
                )

            elif kind == "best_player":
                # Resolve which side by team_id first, then by substring match.
                # The API returns the club name (e.g. "Unihockey Langenthal Aarwangen")
                # while Team.name may be shorter ("Langenthal Aarwangen") or longer
                # ("Langenthal Aarwangen II").  Check both directions so either
                # form resolves correctly.
                import re as _re

                def _norm(s: str) -> str:
                    return _re.sub(r"\s+", " ", s).strip().lower()

                if ev.team_id:
                    _is_home = ev.team_id == game.home_team_id
                else:
                    _tl = _norm(team_label)
                    _hn = _norm(home_name)
                    _an = _norm(away_name)
                    if _tl and (_tl in _hn or _hn in _tl):
                        _is_home = True
                    elif _tl and (_tl in _an or _an in _tl):
                        _is_home = False
                    else:
                        _is_home = None  # unresolved; fixed up below
                best_players.append(
                    {"team": team_label, "player": player_name, "is_home": _is_home}
                )

        # ── Fix up unresolved best-player sides ──────────────────────────────
        # If name matching failed (is_home=None), or both players ended up on
        # the same side, reassign by position: the API consistently returns the
        # home best player first, away second.
        if best_players:
            unresolved = [bp for bp in best_players if bp["is_home"] is None]
            if unresolved:
                # Assign unresolved entries alternating from the side that has
                # fewer entries so far.
                resolved_home = sum(1 for bp in best_players if bp["is_home"] is True)
                resolved_away = sum(1 for bp in best_players if bp["is_home"] is False)
                for bp in unresolved:
                    if resolved_home <= resolved_away:
                        bp["is_home"] = True
                        resolved_home += 1
                    else:
                        bp["is_home"] = False
                        resolved_away += 1
            elif (
                len(best_players) == 2 and best_players[0]["is_home"] == best_players[1]["is_home"]
            ):
                # Both matched the same side — flip the second one.
                best_players[1]["is_home"] = not best_players[0]["is_home"]

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
            is_home = g["team"] == home_name
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
                elif emb_h is not None and emb_a is not None:
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

            if emb_h is not None and emb_a is not None:
                dc_h, dc_a = emb_h, emb_a
            g["score"] = f"{h_score}:{a_score}"
        for g in deduped_goals:
            g.pop("_ev_type", None)
        goals = deduped_goals

        # ── Period scores ────────────────────────────────────────────────────
        from collections import defaultdict as _defaultdict

        _ph: dict = _defaultdict(int)
        _pa: dict = _defaultdict(int)
        for g in goals:
            _p = g.get("period") or 0
            if not _p:
                continue
            _own = g.get("own_goal", False)
            _is_h = g["team"] == home_name
            if _own:
                if _is_h:
                    _pa[_p] += 1
                else:
                    _ph[_p] += 1
            else:
                if _is_h:
                    _ph[_p] += 1
                else:
                    _pa[_p] += 1
        _all_periods = sorted(set(list(_ph.keys()) + list(_pa.keys())))
        period_scores = [{"period": _p, "home": _ph[_p], "away": _pa[_p]} for _p in _all_periods]

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

        # ── Game summary stats ────────────────────────────────────────────────
        game_summary = (
            {
                "home_goals": game.home_score,
                "away_goals": game.away_score,
                "home_penalties": sum(1 for p in penalties if p["team"] == home_name),
                "away_penalties": sum(1 for p in penalties if p["team"] == away_name),
                "home_pim": sum(p["minutes"] for p in penalties if p["team"] == home_name),
                "away_pim": sum(p["minutes"] for p in penalties if p["team"] == away_name),
            }
            if game.home_score is not None
            else None
        )

        # ── Roster ──────────────────────────────────────────────────────────
        roster_home: list[dict] = []
        roster_away: list[dict] = []
        gp_rows = (
            session.query(GamePlayer)
            .filter(GamePlayer.game_id == game_id)
            .order_by(GamePlayer.is_home_team.desc(), GamePlayer.jersey_number)
            .all()
        )

        # Batch-load season stats for all roster players, split by team so that
        # players who changed clubs mid-season only show stats for this team.
        _home_pids = [gp.player_id for gp in gp_rows if gp.is_home_team]
        _away_pids = [gp.player_id for gp in gp_rows if not gp.is_home_team]

        def _build_stats_map(pids: list[int], team_name_filter: str) -> dict[int, dict]:
            smap: dict[int, dict] = {}
            if not pids:
                return smap
            all_rows = (
                session.query(PlayerStatistics)
                .filter(
                    PlayerStatistics.player_id.in_(pids),
                    PlayerStatistics.season_id == game.season_id,
                    PlayerStatistics.team_name == team_name_filter,
                )
                .all()
            )
            if not all_rows:
                return smap
            # Determine the dominant league_abbrev by majority vote (weighted by
            # games_played) so that cup / second-team rows are excluded and only
            # the league this game belongs to is counted.
            from collections import Counter as _Counter

            abbrev_votes: _Counter = _Counter()
            for _row in all_rows:
                abbrev_votes[_row.league_abbrev] += _row.games_played or 1
            _league_abbrev = abbrev_votes.most_common(1)[0][0] if abbrev_votes else None
            for _sr in all_rows:
                if _league_abbrev and _sr.league_abbrev != _league_abbrev:
                    continue
                _pid = _sr.player_id
                if _pid not in smap:
                    smap[_pid] = {"gp": 0, "g": 0, "a": 0, "pts": 0}
                smap[_pid]["gp"] += _sr.games_played or 0
                smap[_pid]["g"] += _sr.goals or 0
                smap[_pid]["a"] += _sr.assists or 0
                smap[_pid]["pts"] += _sr.points or 0
            return smap

        _home_stats_map = _build_stats_map(_home_pids, home_name)
        _away_stats_map = _build_stats_map(_away_pids, away_name)

        # Batch-load TeamPlayer positions as fallback for players whose game
        # lineup entry has no position (empty string / not set yet).
        _all_roster_pids = [gp.player_id for gp in gp_rows]
        _tp_pos_map: dict[int, str] = {}
        if _all_roster_pids:
            for _tp in (
                session.query(TeamPlayer)
                .filter(
                    TeamPlayer.player_id.in_(_all_roster_pids),
                    TeamPlayer.season_id == game.season_id,
                    TeamPlayer.team_id.in_([game.home_team_id, game.away_team_id]),
                )
                .all()
            ):
                if (
                    _tp.player_id not in _tp_pos_map
                    and _tp.position
                    and _tp.position.lower() not in _UNKNOWN_POS
                ):
                    _tp_pos_map[_tp.player_id] = _tp.position

        # Detect whether player_game_stats has been indexed for this game.
        # If the sum of goals across all game_players rows is 0 but the game
        # score is non-zero, the per-player stats are just the lineup-indexer
        # default (0) and haven't been populated yet → show None (→ "—").
        _gp_goal_sum = sum(gp.goals or 0 for gp in gp_rows)
        _actual_goals = (
            (game.home_score or 0) + (game.away_score or 0) if game.home_score is not None else None
        )
        _game_stats_indexed = (
            _actual_goals is None  # unscored game — don't know
            or _actual_goals == 0  # 0-0 game — all zeros are correct
            or _gp_goal_sum > 0  # at least one scorer found → indexed
        )

        # When game_players rows have all-zero goals despite a scored game,
        # derive G/A per player from the goals events (player field format:
        # "Ab. Lastname" or "Ab. Lastname (Cd. Assistname)").
        # The abbreviation may use 1 or more letters of the first name.
        _ev_goals: dict[str, int] = defaultdict(int)
        _ev_assists: dict[str, int] = defaultdict(int)
        if not _game_stats_indexed and goals:
            _SCORER_SPLIT = re.compile(r"^(.+?)(?:\s*\((.+?)\))?\s*$")
            for _g in goals:
                _ps = (_g.get("player") or "").strip()
                if not _ps:
                    continue
                _m = _SCORER_SPLIT.match(_ps)
                if _m:
                    _scorer = _m.group(1).strip()
                    _assists_raw = _m.group(2) or ""
                    if _scorer:
                        _ev_goals[_scorer] += 1
                    for _ast in [a.strip() for a in _assists_raw.split(",") if a.strip()]:
                        _ev_assists[_ast] += 1

        def _ev_name_matches(ev_abbrev: str, full_name: str) -> bool:
            """Match 'Ar. Gropengiesser' against 'Aris Gropengiesser'.
            The event prefix may use 1+ letters of the first name."""
            parts = ev_abbrev.split(". ", 1)
            if len(parts) != 2:
                return ev_abbrev.lower() == full_name.lower()
            ev_prefix, ev_last = parts[0].lower(), parts[1].strip().lower()
            fp = full_name.split()
            if len(fp) < 2:
                return False
            return fp[-1].lower() == ev_last and fp[0].lower().startswith(ev_prefix)

        for gp in gp_rows:
            pl = session.query(Player).filter(Player.person_id == gp.player_id).first()
            name = (pl.full_name if pl else None) or f"Player {gp.player_id}"
            _st = (_home_stats_map if gp.is_home_team else _away_stats_map).get(gp.player_id, {})

            # Try to fill game stats from events when GamePlayer data is empty
            if not _game_stats_indexed and _ev_goals:
                _gg = sum(g for k, g in _ev_goals.items() if _ev_name_matches(k, name))
                _ga = sum(a for k, a in _ev_assists.items() if _ev_name_matches(k, name))
            else:
                _gg = gp.goals if _game_stats_indexed else None
                _ga = gp.assists if _game_stats_indexed else None

            entry = {
                "jersey": gp.jersey_number,
                "position": _POS_ABBREV.get(
                    (gp.position or _tp_pos_map.get(gp.player_id) or "").lower(),
                    gp.position or _tp_pos_map.get(gp.player_id) or "",
                ),
                "player": name,
                "player_id": gp.player_id,
                "game_g": _gg,
                "game_a": _ga,
                "game_pts": (
                    ((_gg or 0) + (_ga or 0)) if (_gg is not None or _ga is not None) else None
                ),
                "season_gp": _st.get("gp"),
                "season_g": _st.get("g"),
                "season_a": _st.get("a"),
                "season_pts": _st.get("pts"),
            }
            if gp.is_home_team:
                roster_home.append(entry)
            else:
                roster_away.append(entry)

        # Mark as indexed if we derived at least one stat from events
        if not _game_stats_indexed and _ev_goals:
            _game_stats_indexed = any(
                (p.get("game_g") or 0) + (p.get("game_a") or 0) > 0
                for p in roster_home + roster_away
            )

        # ── Head-to-head ─────────────────────────────────────────────────────
        from sqlalchemy import or_ as _or2

        _h2h_raw = (
            session.query(Game)
            .filter(
                _or2(
                    (Game.home_team_id == game.home_team_id)
                    & (Game.away_team_id == game.away_team_id),
                    (Game.home_team_id == game.away_team_id)
                    & (Game.away_team_id == game.home_team_id),
                ),
                Game.id != game_id,
                Game.home_score.isnot(None),
                Game.season_id >= game.season_id - 2,
            )
            .order_by(Game.game_date.desc())
            .limit(6)
            .all()
        )
        h2h_games: list[dict] = []
        for _hg in _h2h_raw:
            h2h_games.append(
                {
                    "game_id": _hg.id,
                    "date": _hg.game_date.strftime("%Y-%m-%d") if _hg.game_date else "",
                    "home_team": _team_name(_hg.home_team_id),
                    "away_team": _team_name(_hg.away_team_id),
                    "home_team_id": _hg.home_team_id,
                    "away_team_id": _hg.away_team_id,
                    "home_score": _hg.home_score,
                    "away_score": _hg.away_score,
                }
            )

        # H2H record summary (from home team's perspective)
        _h2h_w = _h2h_d = _h2h_l = 0
        for _hg in h2h_games:
            _home_is_ours = _hg["home_team_id"] == game.home_team_id
            _my = _hg["home_score"] if _home_is_ours else _hg["away_score"]
            _opp = _hg["away_score"] if _home_is_ours else _hg["home_score"]
            if _my > _opp:
                _h2h_w += 1
            elif _my < _opp:
                _h2h_l += 1
            else:
                _h2h_d += 1
        h2h_record = {"w": _h2h_w, "d": _h2h_d, "l": _h2h_l, "total": len(h2h_games)}

        # ── Team form (last 5 scored games before this game) ─────────────────
        def _team_form(tid: int, home_only: "bool | None" = None, n: int = 5) -> list[dict]:
            if home_only is True:
                _loc_filter = (Game.home_team_id == tid,)
            elif home_only is False:
                _loc_filter = (Game.away_team_id == tid,)
            else:
                _loc_filter = (_or2(Game.home_team_id == tid, Game.away_team_id == tid),)
            _q = session.query(Game).filter(
                *_loc_filter,
                Game.id != game_id,
                Game.home_score.isnot(None),
            )
            if game.game_date:
                _q = _q.filter(Game.game_date <= game.game_date)
            _recent = _q.order_by(Game.game_date.desc()).limit(n).all()
            _form: list[dict] = []
            for _fg in reversed(_recent):
                _is_h = _fg.home_team_id == tid
                _my = (_fg.home_score if _is_h else _fg.away_score) or 0
                _op = (_fg.away_score if _is_h else _fg.home_score) or 0
                _opp_tid = _fg.away_team_id if _is_h else _fg.home_team_id
                _res = "W" if _my > _op else ("L" if _my < _op else "D")
                _form.append(
                    {
                        "game_id": _fg.id,
                        "date": _fg.game_date.strftime("%Y-%m-%d") if _fg.game_date else "",
                        "home_away": "H" if _is_h else "A",
                        "opponent": _team_name(_opp_tid),
                        "opponent_id": _opp_tid,
                        "score": f"{_my}–{_op}",
                        "result": _res,
                    }
                )
            return _form

        home_form = _team_form(game.home_team_id)
        away_form = _team_form(game.away_team_id)
        home_h_form = _team_form(game.home_team_id, home_only=True, n=8)
        home_a_form = _team_form(game.home_team_id, home_only=False, n=8)
        away_h_form = _team_form(game.away_team_id, home_only=True, n=8)
        away_a_form = _team_form(game.away_team_id, home_only=False, n=8)

        # ── Season record (W-D-L, GF, GA, PIM, averages) up to this game ─────
        from sqlalchemy import func as _sqlfunc

        def _season_record(tid: int) -> dict:
            _q = session.query(Game).filter(
                _or2(Game.home_team_id == tid, Game.away_team_id == tid),
                Game.season_id == game.season_id,
                Game.home_score.isnot(None),
                Game.id != game_id,
            )
            if game.game_date:
                _q = _q.filter(Game.game_date <= game.game_date)
            _w = _d = _l = _gf = _ga = 0
            _w_h = _d_h = _l_h = _gf_h = _ga_h = 0
            _w_a = _d_a = _l_a = _gf_a = _ga_a = 0
            for _rg in _q.all():
                _is_h = _rg.home_team_id == tid
                _my = (_rg.home_score if _is_h else _rg.away_score) or 0
                _op = (_rg.away_score if _is_h else _rg.home_score) or 0
                _gf += _my
                _ga += _op
                _res = "w" if _my > _op else ("l" if _my < _op else "d")
                if _is_h:
                    _gf_h += _my
                    _ga_h += _op
                    if _res == "w":
                        _w_h += 1
                    elif _res == "l":
                        _l_h += 1
                    else:
                        _d_h += 1
                else:
                    _gf_a += _my
                    _ga_a += _op
                    if _res == "w":
                        _w_a += 1
                    elif _res == "l":
                        _l_a += 1
                    else:
                        _d_a += 1
                if _res == "w":
                    _w += 1
                elif _res == "l":
                    _l += 1
                else:
                    _d += 1
            _gp = _w + _d + _l
            # total team PIM from game_players for this season
            _pim_q = (
                session.query(_sqlfunc.coalesce(_sqlfunc.sum(GamePlayer.penalty_minutes), 0))
                .join(Game, GamePlayer.game_id == Game.id)
                .filter(
                    GamePlayer.team_id == tid,
                    Game.season_id == game.season_id,
                    Game.home_score.isnot(None),
                    Game.id != game_id,
                )
            )
            if game.game_date:
                _pim_q = _pim_q.filter(Game.game_date <= game.game_date)
            _total_pim = _pim_q.scalar() or 0
            return {
                "w": _w,
                "d": _d,
                "l": _l,
                "gf": _gf,
                "ga": _ga,
                "gp": _gp,
                "avg_gf": round(_gf / _gp, 1) if _gp else "—",
                "avg_ga": round(_ga / _gp, 1) if _gp else "—",
                "avg_total": round((_gf + _ga) / _gp, 1) if _gp else "—",
                "total_pim": _total_pim,
                "avg_pim": round(_total_pim / _gp, 1) if _gp else "—",
                "home": {
                    "w": _w_h,
                    "d": _d_h,
                    "l": _l_h,
                    "gf": _gf_h,
                    "ga": _ga_h,
                    "gp": _w_h + _d_h + _l_h,
                },
                "away": {
                    "w": _w_a,
                    "d": _d_a,
                    "l": _l_a,
                    "gf": _gf_a,
                    "ga": _ga_a,
                    "gp": _w_a + _d_a + _l_a,
                },
            }

        home_record = _season_record(game.home_team_id)
        away_record = _season_record(game.away_team_id)

        # ── Group / league standings ──────────────────────────────────────────
        _db_league_id = game.group.league_id if game.group else None
        _db_group_id = game.group_id
        _group_name = (game.group.name or game.group.text or "") if game.group else ""
        _phase = (game.group.phase or "") if game.group else ""
        _league_name = (
            (game.group.league.name or game.group.league.text or "")
            if (game.group and game.group.league)
            else ""
        )

        _timeline_events, _total_seconds = build_timeline_events(
            goals, penalties, home_name, away_name
        )

        def _get_regular_season_standings(db_session, league_id, group_id, phase):
            """For playoff/playout games, show the regular-season standings instead."""
            if not league_id:
                return []
            canonical = _canonical_phase(phase)
            if canonical == "regular":
                # Already a regular-season game — use own group
                return get_league_standings(
                    league_id, only_group_ids=[group_id] if group_id else None
                )
            # Find the Regelsaison group for the same league
            reg_group = (
                db_session.query(LeagueGroup)
                .filter(LeagueGroup.league_id == league_id, LeagueGroup.phase == "Regelsaison")
                .first()
            )
            use_id = reg_group.id if reg_group else group_id
            return get_league_standings(league_id, only_group_ids=[use_id] if use_id else None)

        return {
            "game_id": game_id,
            "season_id": game.season_id,
            "league_db_id": _db_league_id,
            "home_team_id": game.home_team_id,
            "away_team_id": game.away_team_id,
            "home_team": home_name,
            "away_team": away_name,
            "home_team_logo": _team_logo(game.home_team_id),
            "away_team_logo": _team_logo(game.away_team_id),
            "home_score": game.home_score,
            "away_score": game.away_score,
            "date": game.game_date.strftime("%Y-%m-%d") if game.game_date else "",
            "time": game.game_time or "",
            "venue": game.venue or "",
            "status": game.status or "",
            "referee_1": game.referee_1 or "",
            "referee_2": game.referee_2 or "",
            "spectators": game.spectators,
            "goals": goals,
            "penalties": penalties,
            "period_markers": period_markers,
            "period_scores": period_scores,
            "best_players": best_players,
            "roster_home": roster_home,
            "roster_away": roster_away,
            "game_stats_indexed": _game_stats_indexed,
            "h2h_games": h2h_games,
            "h2h_record": h2h_record,
            "home_form": home_form,
            "away_form": away_form,
            "home_h_form": home_h_form,
            "home_a_form": home_a_form,
            "away_h_form": away_h_form,
            "away_a_form": away_a_form,
            "game_summary": game_summary,
            "home_record": home_record,
            "away_record": away_record,
            "group_standings": _get_regular_season_standings(
                session, _db_league_id, _db_group_id, _phase
            ),
            "group_name": _group_name,
            "phase": _phase,
            "league_name": _league_name,
            "timeline_events": _timeline_events,
            "total_seconds": _total_seconds,
        }


# ---------------------------------------------------------------------------
# 7b. Playoff series data for a single game
# ---------------------------------------------------------------------------


def _canonical_phase(phase_str: str | None) -> str:
    """Normalise a raw phase string to one of: regular / playoff / playout / promotion."""
    if not phase_str or phase_str == "Regelsaison":
        return "regular"
    p = phase_str.lower()
    if "playoff" in p or "superfinal" in p:
        return "playoff"
    if "playout" in p:
        return "playout"
    if "aufstieg" in p or "abstieg" in p or "qualifikation" in p:
        return "promotion"
    return "regular"


def get_playoff_series_for_game(game_id: int) -> dict | None:
    """Return all series in the same playoff/playout phase as *game_id*, grouped by round.

    Returns a dict with key:
      - ``phases``: list of phase dicts, each containing:
        - ``phase_name``: raw phase string (e.g. "Playoff Viertelfinals")
        - ``series_list``: list of series dicts for that round

    The current game's round is always first; remaining rounds are ordered
    by their earliest game date (ascending).

    Returns *None* if the game is not in a playoff/playout group or has no group.
    """
    db = get_database_service()
    with db.session_scope() as session:
        game = session.query(Game).filter(Game.id == game_id).first()
        if not game or not game.group_id:
            return None

        group = session.query(LeagueGroup).filter(LeagueGroup.id == game.group_id).first()
        if not group:
            return None

        canonical = _canonical_phase(group.phase)
        if canonical not in ("playoff", "playout"):
            return None

        league_fk_id: int = group.league_id  # FK to leagues.id row

        # All LeagueGroup rows in the same League with the same canonical phase
        sibling_groups = (
            session.query(LeagueGroup).filter(LeagueGroup.league_id == league_fk_id).all()
        )
        phase_groups = [g for g in sibling_groups if _canonical_phase(g.phase) == canonical]
        phase_group_ids = [g.id for g in phase_groups]
        group_by_id = {g.id: g for g in phase_groups}
        if not phase_group_ids:
            return None

        # All games in this phase, scoped to the same season as the current game
        phase_games = (
            session.query(Game)
            .filter(
                Game.group_id.in_(phase_group_ids),
                Game.season_id == game.season_id,
            )
            .order_by(Game.game_date.asc())
            .all()
        )
        if not phase_games:
            return None

        # Build team name/logo maps
        all_team_ids = {g.home_team_id for g in phase_games} | {g.away_team_id for g in phase_games}
        _snm: dict[int, str] = {}
        _slogo: dict[int, str | None] = {}
        for _t in (
            session.query(Team)
            .filter(Team.id.in_(all_team_ids), Team.season_id == game.season_id)
            .all()
        ):
            _snm[_t.id] = _t.name or _t.text or f"Team {_t.id}"
            if _t.logo_url:
                _slogo[_t.id] = _t.logo_url
        _missing = all_team_ids - _snm.keys()
        if _missing:
            for _t in (
                session.query(Team).filter(Team.id.in_(_missing), Team.name.isnot(None)).all()
            ):
                _snm.setdefault(_t.id, _t.name)
                if _t.logo_url:
                    _slogo.setdefault(_t.id, _t.logo_url)

        # Bucket games by group_id, then by sorted team-pair key
        _pairs_by_group: dict[int, dict[tuple, list]] = {g.id: {} for g in phase_groups}
        for _g in phase_games:
            _key = tuple(sorted([_g.home_team_id, _g.away_team_id]))
            _pairs_by_group[_g.group_id].setdefault(_key, []).append(_g)

        current_pair = tuple(sorted([game.home_team_id, game.away_team_id]))
        current_group_id: int = game.group_id

        def _earliest(gid: int) -> datetime:
            dates = [g.game_date for g in phase_games if g.group_id == gid and g.game_date]
            return min(dates) if dates else datetime.max

        other_groups = sorted(
            [g for g in phase_groups if g.id != current_group_id],
            key=lambda g: _earliest(g.id),
        )
        ordered_groups = [group_by_id[current_group_id]] + other_groups

        # Only include groups that actually have games in this season
        ordered_groups = [g for g in ordered_groups if _pairs_by_group.get(g.id)]

        phases: list[dict] = []
        for _grp in ordered_groups:
            group_series: list[dict] = []
            for _key, _pgames in sorted(
                _pairs_by_group[_grp.id].items(),
                key=lambda x: _snm.get(x[0][0] if isinstance(x[0], tuple) else x[0], ""),
            ):
                _sorted = sorted(_pgames, key=lambda x: x.game_date or datetime.min)
                _first_g = _sorted[0]
                _ta = _first_g.home_team_id
                _tb = _first_g.away_team_id
                _ta_wins = _tb_wins = 0
                _games_list: list[dict] = []
                for _g in _sorted:
                    _cancelled = _g.status == "cancelled"
                    _played = _g.home_score is not None
                    if _played:
                        _home_wins = _g.home_score > _g.away_score
                        if _g.home_team_id == _ta:
                            if _home_wins:
                                _ta_wins += 1
                            else:
                                _tb_wins += 1
                        else:
                            if _home_wins:
                                _tb_wins += 1
                            else:
                                _ta_wins += 1
                    _games_list.append(
                        {
                            "game_id": _g.id,
                            "date": _g.game_date.strftime("%d.%m.%Y") if _g.game_date else "",
                            "weekday": _g.game_date.strftime("%a") if _g.game_date else "",
                            "home_team": _snm.get(_g.home_team_id, f"Team {_g.home_team_id}"),
                            "away_team": _snm.get(_g.away_team_id, f"Team {_g.away_team_id}"),
                            "home_team_id": _g.home_team_id,
                            "away_team_id": _g.away_team_id,
                            "home_score": _g.home_score,
                            "away_score": _g.away_score,
                            "played": _played,
                            "cancelled": _cancelled,
                            "is_current": _g.id == game_id,
                        }
                    )
                group_series.append(
                    {
                        "team_a_id": _ta,
                        "team_b_id": _tb,
                        "team_a_name": _snm.get(_ta, f"Team {_ta}"),
                        "team_b_name": _snm.get(_tb, f"Team {_tb}"),
                        "team_a_logo": _slogo.get(_ta),
                        "team_b_logo": _slogo.get(_tb),
                        "team_a_rank": None,
                        "team_b_rank": None,
                        "team_a_wins": _ta_wins,
                        "team_b_wins": _tb_wins,
                        "games": _games_list,
                        "is_current_series": _key == current_pair,
                    }
                )
            phases.append(
                {
                    "phase_name": _grp.phase or canonical.capitalize(),
                    "series_list": group_series,
                }
            )

        return {"phases": phases}


# ---------------------------------------------------------------------------
# 8. Games list page
# ---------------------------------------------------------------------------


def get_recent_games(
    season_id: Optional[int] = None,
    mode: str = "results",  # "results" = scored, date DESC  |  "schedule" = upcoming, date ASC
    sex: str = "all",
    age: str = "all",
    field: str = "all",
    level: str = "all",
    limit: int = 50,
    offset: int = 0,
    with_score_only: bool = False,  # kept for backward compat; overridden when mode is explicit
) -> dict:
    """Return games for the combined Games/Schedule page with sex/age/field/level filters."""
    from datetime import date as _date

    # ---------- game_class filter sets (same as schedule/teams) ----------
    _SEX_GC: dict[str, set[int]] = {
        "women": {21, 22, 26, 28, 41, 42, 43, 44},
        "mixed": {49},
        "men": {11, 12, 14, 16, 18, 19, 31, 32, 33, 34, 35, 51},
    }
    _AGE_GC: dict[str, set[int]] = {
        "senior": {11, 12, 21, 22},
        "U21": {19, 26},
        "U18": {18, 31, 41},
        "U16": {16, 28, 32, 42},
        "U14": {14, 33, 43, 49},
        "U12": {34, 36, 44},
        "U10": {35},
        "senioren": {51},
    }
    _FIELD_GC: dict[str, set[int]] = {
        "big": {11, 21, 14, 16, 18, 19, 26, 28, 49},
        "small": {12, 22, 31, 32, 33, 34, 35, 36, 41, 42, 43, 44, 51},
    }
    # level → (national league_id, regional game_classes)
    _LEVEL_LID: dict[str, int] = {"A": 13, "B": 14, "C": 15, "D": 16}
    _LEVEL_REGIONAL_GCS: dict[str, list[int]] = {
        "A": [31, 41],
        "B": [32, 42],
        "C": [33, 43],
        "D": [34, 44],
        "E": [35],
    }

    active_gc: Optional[set] = None
    for val, mapping in [(sex, _SEX_GC), (age, _AGE_GC), (field, _FIELD_GC)]:
        if val and val != "all" and val in mapping:
            s = mapping[val]
            active_gc = s if active_gc is None else active_gc & s

    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        today = _date.today()
        base_q = session.query(Game).filter(Game.season_id == season_id)

        if mode == "schedule":
            base_q = base_q.filter(Game.home_score.is_(None), Game.status != "cancelled", Game.game_date >= today)
        else:
            # "results" mode (default)
            base_q = base_q.filter(Game.home_score.isnot(None))

        need_league_join = active_gc is not None or (level and level != "all")
        if need_league_join:
            base_q = base_q.join(LeagueGroup, Game.group_id == LeagueGroup.id).join(
                League, LeagueGroup.league_id == League.id
            )
            if active_gc is not None:
                base_q = base_q.filter(League.game_class.in_(list(active_gc)))
            if level and level != "all":
                lvl_conds = []
                if level in _LEVEL_LID:
                    lvl_conds.append(
                        and_(
                            League.league_id == _LEVEL_LID[level],
                            League.game_class.notin_([11, 12, 21, 22]),
                        )
                    )
                if level in _LEVEL_REGIONAL_GCS:
                    lvl_conds.append(League.game_class.in_(_LEVEL_REGIONAL_GCS[level]))
                if lvl_conds:
                    base_q = base_q.filter(or_(*lvl_conds))

        total = base_q.count()
        order = Game.game_date.asc() if mode == "schedule" else Game.game_date.desc()
        games_raw = base_q.order_by(order, Game.game_time.asc()).offset(offset).limit(limit).all()

        if not games_raw:
            return {"games": [], "total": total, "offset": offset, "limit": limit}

        # Preload team names and logos
        team_ids = {g.home_team_id for g in games_raw} | {g.away_team_id for g in games_raw}
        t_names: dict[int, str] = {}
        t_logos: dict[int, str] = {}
        for t in (
            session.query(Team).filter(Team.id.in_(team_ids), Team.season_id == season_id).all()
        ):
            if t.name or t.text:
                t_names[t.id] = str(t.name or t.text or "")
            if t.logo_url:
                t_logos[t.id] = t.logo_url
        missing = {tid for tid in team_ids if tid not in t_names}
        if missing:
            for t in session.query(Team).filter(Team.id.in_(missing), Team.name.isnot(None)).all():
                t_names.setdefault(t.id, str(t.name or ""))
                if t.logo_url:
                    t_logos.setdefault(t.id, t.logo_url)

        # Preload league labels per group
        group_ids = {g.group_id for g in games_raw if g.group_id}
        grp_label: dict[int, str] = {}
        if group_ids:
            for grp, lg in (
                session.query(LeagueGroup, League)
                .outerjoin(League, League.id == LeagueGroup.league_id)
                .filter(LeagueGroup.id.in_(group_ids))
                .all()
            ):
                if lg:
                    gc = int(lg.game_class) if lg.game_class is not None else None
                    lg_raw = str(lg.name or lg.text or "")
                    mw = _mw_from_league(gc, lg_raw)
                    for pfx in ("Herren ", "Damen ", "Junioren ", "Juniorinnen "):
                        lg_raw = lg_raw.replace(pfx, "")
                    label_parts = [p for p in [mw, lg_raw.replace(" ", "").strip()] if p]
                    grp_label[grp.id] = " - ".join(label_parts)

        result = []
        for g in games_raw:
            result.append(
                {
                    "game_id": g.id,
                    "date": g.game_date.strftime("%d.%m.%Y") if g.game_date else "",
                    "weekday": g.game_date.strftime("%a") if g.game_date else "",
                    "time": g.game_time or "",
                    "home_team": t_names.get(g.home_team_id, f"Team {g.home_team_id}"),
                    "away_team": t_names.get(g.away_team_id, f"Team {g.away_team_id}"),
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "home_team_logo": t_logos.get(g.home_team_id, ""),
                    "away_team_logo": t_logos.get(g.away_team_id, ""),
                    "home_score": g.home_score,
                    "away_score": g.away_score,
                    "has_score": g.home_score is not None,
                    "league_label": grp_label.get(g.group_id, "") if g.group_id else "",
                }
            )
        return {"games": result, "total": total, "offset": offset, "limit": limit}
