#!/usr/bin/env python3
"""
Database Query Wrapper per SwissUnihockeyStats.
Da eseguire all'interno del container o via `docker exec`.
"""

import argparse
import sqlite3
import sys
from datetime import datetime

DB_PATH = "/app/data/swissunihockey.db"


def connect():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"DB connection error: {e}", file=sys.stderr)
        sys.exit(1)


def query_players(args):
    conn = connect()
    cur = conn.cursor()
    sql = "SELECT person_id, full_name, year_of_birth FROM players"
    params = []
    where = []

    if args.name:
        where.append("full_name LIKE ?")
        params.append(f"%{args.name}%")
    if args.min_birth:
        where.append("year_of_birth >= ?")
        params.append(args.min_birth)
    if args.max_birth:
        where.append("year_of_birth <= ?")
        params.append(args.max_birth)
    # args.country rimosso perché non disponibile nella tabella players

    if where:
        sql += " WHERE " + " AND ".join(where)
    if args.limit:
        sql += " LIMIT ?"
        params.append(args.limit)

    cur.execute(sql, params)
    rows = cur.fetchall()

    print(f"{'ID':<8} {'Nome':<30} {'Nascita':<6}")
    print("-" * 50)
    for r in rows:
        print(f"{r['person_id']:<8} {r['full_name']:<30} {r['year_of_birth'] or '?':<6}")
    print(f"\nTotale: {len(rows)} giocatori")


def query_player_stats(args):
    conn = connect()
    cur = conn.cursor()
    sql = """
        SELECT s.text as season, ps.team_name, ps.games_played, ps.goals, ps.assists,
               ps.points, ps.penalty_minutes, ps.plus_minus
        FROM player_statistics ps
        JOIN seasons s ON ps.season_id = s.id
        WHERE ps.player_id = ?
    """
    params = [args.player_id]
    if args.season:
        sql += " AND s.text = ?"
        params.append(args.season)
    sql += " ORDER BY s.id DESC"
    cur.execute(sql, params)
    rows = cur.fetchall()

    print(f"=== Statistiche giocatore ID {args.player_id} ===")
    print(f"{'Stagione':<10} {'Squadra':<25} {'GP':>4} {'G':>4} {'A':>4} {'Pt':>4} {'PIM':>4} {'+/-':>4}")
    print("-" * 80)
    total_gp = total_g = total_a = total_pts = total_pim = total_pm = 0
    for r in rows:
        season = r['season'] or '?'
        team = r['team_name'] or 'N/A'
        gp, g, a, pts, pim, pm = r['games_played'], r['goals'], r['assists'], r['points'], r['penalty_minutes'], r['plus_minus']
        gp = gp or 0; g = g or 0; a = a or 0; pts = pts or 0; pim = pim or 0; pm = pm or 0
        print(f"{season:<10} {team:<25} {gp:>4} {g:>4} {a:>4} {pts:>4} {pim:>4} {pm:>4}")
        total_gp += gp; total_g += g; total_a += a; total_pts += pts; total_pim += pim; total_pm += pm
    print("-" * 80)
    print(f"{'TOTALE':<10} {'':<25} {total_gp:>4} {total_g:>4} {total_a:>4} {total_pts:>4} {total_pim:>4} {total_pm:>4}")
    if total_gp > 0:
        print(f"Media: PPG {total_pts/total_gp:.2f} | GPG {total_g/total_gp:.2f} | APG {total_a/total_gp:.2f} | PIM/GP {total_pim/total_gp:.1f}")


def query_games(args):
    conn = connect()
    cur = conn.cursor()
    sql = """
        SELECT g.id, s.text as season, g.game_date,
               ht.name as home_team, at.name as away_team,
               g.home_score, g.away_score, g.status
        FROM games g
        JOIN seasons s ON g.season_id = s.id
        LEFT JOIN teams ht ON g.home_team_id = ht.id
        LEFT JOIN teams at ON g.away_team_id = at.id
    """
    params = []
    where = []

    if args.season:
        where.append("s.text = ?")
        params.append(args.season)
    if args.team:
        where.append("(ht.name LIKE ? OR at.name LIKE ?)")
        params.extend([f"%{args.team}%", f"%{args.team}%"])
    if args.status:
        where.append("g.status = ?")
        params.append(args.status)
    if args.date_from:
        where.append("g.game_date >= ?")
        params.append(args.date_from)
    if args.date_to:
        where.append("g.game_date <= ?")
        params.append(args.date_to)

    if where:
        sql += " WHERE " + " AND ".join(where)
    if args.limit:
        sql += " LIMIT ?"
        params.append(args.limit)
    sql += " ORDER BY g.game_date DESC"

    cur.execute(sql, params)
    rows = cur.fetchall()

    print(f"{'ID':<10} {'Stagione':<10} {'Data':<10} {'Home':<25} {'Away':<25} {'Ris':<6} {'Stato'}")
    print("-" * 110)
    for r in rows:
        home = r['home_team'] or "N/A"
        away = r['away_team'] or "N/A"
        ris = f"{r['home_score']}-{r['away_score']}" if r['home_score'] is not None else "N/A"
        print(f"{r['id']:<10} {r['season']:<10} {r['game_date'] or '?':<10} {home:<25} {away:<25} {ris:<6} {r['status']}")
    print(f"\nTotale: {len(rows)} partite")


def query_season_completeness(args):
    conn = connect()
    cur = conn.cursor()
    sql = """
        SELECT s.id, s.text, s.highlighted as is_current, s.is_frozen,
               COUNT(g.id) as total,
               SUM(CASE WHEN g.status IN ('finished','cancelled') THEN 1 ELSE 0 END) as finished
        FROM seasons s
        LEFT JOIN games g ON g.season_id = s.id
    """
    params = []
    where = []
    if args.season:
        where.append("s.text = ?")
        params.append(args.season)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY s.id ORDER BY s.id DESC"
    cur.execute(sql, params)
    rows = cur.fetchall()

    print(f"{'Stagione':<10} {'Corrente?':<8} {'Frozen?':<7} {'Tot':>6} {'Finite':>6} {'%':>5}")
    print("-" * 60)
    for r in rows:
        total = r['total'] or 0
        finished = r['finished'] or 0
        pct = (finished / total * 100) if total else 0
        curr = "✓" if r['is_current'] else ""
        frozen = "✓" if r['is_frozen'] else ""
        print(f"{r['text']:<10} {curr:<8} {frozen:<7} {total:>6} {finished:>6} {pct:>5.1f}%")


def query_top_scorers(args):
    conn = connect()
    cur = conn.cursor()
    sql = """
        SELECT p.full_name, ps.team_name, ps.goals, ps.assists, ps.points, ps.games_played
        FROM player_statistics ps
        JOIN players p ON ps.player_id = p.person_id
        JOIN seasons s ON ps.season_id = s.id
        WHERE s.text = ?
    """
    params = [args.season]
    order_col = {'goals':'ps.goals','assists':'ps.assists','points':'ps.points'}[args.order]
    sql += f" ORDER BY {order_col} DESC LIMIT ?"
    params.append(args.limit)

    cur.execute(sql, params)
    rows = cur.fetchall()

    print(f"TOP {args.limit} per {args.season} — ordinati per {args.order}")
    print(f"{'Giocatore':<30} {'Squadra':<25} {'GP':>4} {'G':>4} {'A':>4} {'Pt':>4}")
    print("-" * 85)
    for i, r in enumerate(rows, 1):
        print(f"{i:2}. {r['full_name']:<27} {r['team_name'] or 'N/A':<25} {r['games_played'] or 0:>4} {r['goals'] or 0:>4} {r['assists'] or 0:>4} {r['points'] or 0:>4}")


def query_team_players(args):
    conn = connect()
    cur = conn.cursor()
    sql = """
        SELECT p.full_name, ps.games_played, ps.goals, ps.assists, ps.points, ps.penalty_minutes
        FROM player_statistics ps
        JOIN players p ON ps.player_id = p.person_id
        JOIN seasons s ON ps.season_id = s.id
        WHERE s.text = ? AND ps.team_name = ?
        ORDER BY ps.points DESC
    """
    cur.execute(sql, [args.season, args.team])
    rows = cur.fetchall()

    print(f"Roster {args.team} — {args.season}")
    print(f"{'#':<2} {'Giocatore':<28} {'GP':>4} {'G':>4} {'A':>4} {'Pt':>4} {'PIM':>4}")
    print("-" * 80)
    for i, r in enumerate(rows, 1):
        print(f"{i:2}. {r['full_name']:<28} {r['games_played'] or 0:>4} {r['goals'] or 0:>4} {r['assists'] or 0:>4} {r['points'] or 0:>4} {r['penalty_minutes'] or 0:>4}")
    print(f"\nTotale: {len(rows)} giocatori")


def query_games_between(args):
    conn = connect()
    cur = conn.cursor()
    sql = """
        SELECT g.id, s.text as season, g.game_date,
               ht.name as home_team, at.name as away_team,
               g.home_score, g.away_score, g.status
        FROM games g
        JOIN seasons s ON g.season_id = s.id
        LEFT JOIN teams ht ON g.home_team_id = ht.id
        LEFT JOIN teams at ON g.away_team_id = at.id
        WHERE (ht.name = ? AND at.name = ?)
           OR (ht.name = ? AND at.name = ?)
    """
    params = [args.team1, args.team2, args.team2, args.team1]
    if args.season:
        sql += " AND s.text = ?"
        params.append(args.season)
    sql += " ORDER BY g.game_date DESC"
    if args.limit:
        sql += " LIMIT ?"
        params.append(args.limit)

    cur.execute(sql, params)
    rows = cur.fetchall()

    print(f"Confronti: {args.team1} vs {args.team2}" + (f" — {args.season}" if args.season else ""))
    print(f"{'#':<2} {'ID':<10} {'Stagione':<10} {'Data':<10} {'Home':<25} {'Away':<25} {'Ris':<6} {'Stato'}")
    print("-" * 115)
    for i, r in enumerate(rows, 1):
        home = r['home_team'] or "N/A"
        away = r['away_team'] or "N/A"
        ris = f"{r['home_score']}-{r['away_score']}" if r['home_score'] is not None else "N/A"
        print(f"{i:2}. {r['id']:<10} {r['season']:<10} {r['game_date'] or '?':<10} {home:<25} {away:<25} {ris:<6} {r['status']}")
    print(f"\nTotale: {len(rows)} partite")


def main():
    parser = argparse.ArgumentParser(description="Wrapper query DB SwissUnihockeyStats")
    sub = parser.add_subparsers(dest='entity', required=True)

    # players
    p_players = sub.add_parser('players', help='Ricerca giocatori')
    p_players.add_argument('--name', help='Nome parziale (LIKE)')
    p_players.add_argument('--min-birth', type=int, help='Anno di nascita minimo')
    p_players.add_argument('--max-birth', type=int, help='Anno di nascita massimo')
    p_players.add_argument('--limit', type=int, help='Limite risultati')
    p_players.set_defaults(func=query_players)

    # player-stats
    p_stats = sub.add_parser('player-stats', help='Statistiche di un giocatore')
    p_stats.add_argument('--player-id', required=True, type=int, help='ID giocatore')
    p_stats.add_argument('--season', help='Filtra per stagione (es. 2024/25)')
    p_stats.set_defaults(func=query_player_stats)

    # games
    p_games = sub.add_parser('games', help='Ricerca partite')
    p_games.add_argument('--season', help='Stagione (es. 2024/25)')
    p_games.add_argument('--team', help='Nome squadra (home o away)')
    p_games.add_argument('--status', choices=['scheduled','finished','cancelled'], help='Stato partita')
    p_games.add_argument('--date-from', help='Data inizio (YYYY-MM-DD)')
    p_games.add_argument('--date-to', help='Data fine (YYYY-MM-DD)')
    p_games.add_argument('--limit', type=int, help='Limite risultati')
    p_games.set_defaults(func=query_games)

    # completeness
    p_comp = sub.add_parser('completeness', help='Completezza stagioni')
    p_comp.add_argument('--season', help='Filtra per stagione')
    p_comp.set_defaults(func=query_season_completeness)

    # top-scorers
    p_top = sub.add_parser('top-scorers', help='Migliori marcatori per stagione')
    p_top.add_argument('--season', required=True, help='Stagione (es. 2024/25)')
    p_top.add_argument('--order', choices=['goals','assists','points'], default='points', help='Ordinamento (default: points)')
    p_top.add_argument('--limit', type=int, default=10, help='Limite risultati (default 10)')
    p_top.set_defaults(func=query_top_scorers)

    # team-players
    p_team = sub.add_parser('team-players', help='Roster di una squadra in una stagione')
    p_team.add_argument('--season', required=True, help='Stagione (es. 2024/25)')
    p_team.add_argument('--team', required=True, help='Nome squadra')
    p_team.set_defaults(func=query_team_players)

    # games-between
    p_head = sub.add_parser('games-between', help='Scontri diretti tra due squadre')
    p_head.add_argument('--team1', required=True, help='Squadra 1')
    p_head.add_argument('--team2', required=True, help='Squadra 2')
    p_head.add_argument('--season', help='Filtra per stagione')
    p_head.add_argument('--limit', type=int, default=20, help='Limite risultati')
    p_head.set_defaults(func=query_games_between)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()