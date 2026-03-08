import pytest
from app.services.stats_service import build_timeline_events


def test_empty_game():
    events, total = build_timeline_events([], [], "Home", "Away")
    assert events == []
    assert total == 3600


def test_goal_percentage_period1():
    goals = [{"period": 1, "time": "10:00", "team": "Home", "player": "Smith", "score": "1:0", "own_goal": False}]
    events, total = build_timeline_events(goals, [], "Home", "Away")
    assert total == 3600
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "goal"
    assert ev["team_side"] == "home"
    assert abs(ev["pct"] - (600 / 3600 * 100)) < 0.01
    assert ev["label"].startswith("GOAL - 10:00")
    assert "Home" in ev["label"]
    assert "Smith" in ev["label"]


def test_goal_percentage_period2():
    goals = [{"period": 2, "time": "05:00", "team": "Away", "player": "Jones", "score": "1:1", "own_goal": False}]
    events, total = build_timeline_events(goals, [], "Home", "Away")
    # period 2 starts at 1200s; 5 min = 300s → 1500s
    assert abs(events[0]["pct"] - (1500 / 3600 * 100)) < 0.01
    assert events[0]["team_side"] == "away"


def test_ot_extends_total():
    goals = [{"period": "OT", "time": "03:42", "team": "Home", "player": "Muller", "score": "4:3", "own_goal": False}]
    events, total = build_timeline_events(goals, [], "Home", "Away")
    assert total == 4200
    # OT starts at 3600s; 3:42 = 222s → 3822s
    assert abs(events[0]["pct"] - (3822 / 4200 * 100)) < 0.01


def test_penalty_label():
    pens = [{"period": 1, "time": "08:15", "team": "Away", "player": "Bauer", "minutes": 2, "infraction": "hooking"}]
    events, total = build_timeline_events([], pens, "Home", "Away")
    ev = events[0]
    assert ev["kind"] == "penalty"
    assert ev["label"].startswith("PEN - 08:15")
    assert "Away" in ev["label"]
    assert "Bauer" in ev["label"]
    assert "2 min" in ev["label"]
    assert "hooking" in ev["label"]


def test_unknown_team_side():
    goals = [{"period": 1, "time": "01:00", "team": "Other FC", "player": "X", "score": "1:0", "own_goal": False}]
    events, _ = build_timeline_events(goals, [], "Home", "Away")
    assert events[0]["team_side"] == "unknown"


def test_ids_are_unique():
    goals = [
        {"period": 1, "time": "10:00", "team": "Home", "player": "A", "score": "1:0", "own_goal": False},
        {"period": 2, "time": "05:00", "team": "Away", "player": "B", "score": "1:1", "own_goal": False},
    ]
    pens = [
        {"period": 1, "time": "07:00", "team": "Home", "player": "C", "minutes": 2, "infraction": "tripping"},
    ]
    events, _ = build_timeline_events(goals, pens, "Home", "Away")
    ids = [e["id"] for e in events]
    assert len(ids) == len(set(ids))


def test_events_sorted_by_pct():
    goals = [
        {"period": 3, "time": "01:00", "team": "Home", "player": "A", "score": "3:2", "own_goal": False},
        {"period": 1, "time": "05:00", "team": "Away", "player": "B", "score": "0:1", "own_goal": False},
    ]
    events, _ = build_timeline_events(goals, [], "Home", "Away")
    assert events[0]["pct"] < events[1]["pct"]
    # Period 1, 5:00 = 300s → 300/3600*100 ≈ 8.33%
    assert abs(events[0]["pct"] - (300 / 3600 * 100)) < 0.01
    # Period 3, 1:00 = 2460s → 2460/3600*100 ≈ 68.33%
    assert abs(events[1]["pct"] - (2460 / 3600 * 100)) < 0.01


def test_missing_time_handled():
    goals = [{"period": 1, "time": "", "team": "Home", "player": "X", "score": "1:0", "own_goal": False}]
    events, _ = build_timeline_events(goals, [], "Home", "Away")
    assert events[0]["pct"] == 0.0


def test_goal_with_assist_in_label():
    goals = [{"period": 1, "time": "12:00", "team": "Home", "player": "Smith (Assist: Jones)", "score": "1:0", "own_goal": False}]
    events, _ = build_timeline_events(goals, [], "Home", "Away")
    assert "Smith (Assist: Jones)" in events[0]["label"]


def test_goal_percentage_period3():
    goals = [{"period": 3, "time": "00:00", "team": "Home", "player": "X", "score": "1:0", "own_goal": False}]
    events, total = build_timeline_events(goals, [], "Home", "Away")
    assert total == 3600
    # Period 3 starts at 2400s → pct = 2400/3600*100 ≈ 66.67%
    assert abs(events[0]["pct"] - (2400 / 3600 * 100)) < 0.01


from app.services.database import DatabaseService
from sqlalchemy import text


def _make_db_with_finished_game():
    svc = DatabaseService("sqlite:///:memory:")
    svc.initialize()
    with svc.session_scope() as session:
        session.execute(text("INSERT INTO seasons (id) VALUES (2025)"))
        session.execute(text("INSERT INTO clubs (id, season_id) VALUES (1, 2025)"))
        session.execute(text("INSERT INTO teams (id, season_id, club_id, name) VALUES (1, 2025, 1, 'Home FC')"))
        session.execute(text("INSERT INTO teams (id, season_id, club_id, name) VALUES (2, 2025, 1, 'Away FC')"))
        session.execute(text("""
            INSERT INTO games (id, season_id, home_team_id, away_team_id, home_score, away_score, status)
            VALUES (999, 2025, 1, 2, 2, 1, 'finished')
        """))
        session.execute(text("""
            INSERT INTO game_events (game_id, event_type, period, time)
            VALUES (999, 'Torschütze 1:0 Meier', 1, '10:00')
        """))
    return svc


def test_box_score_includes_timeline_keys(monkeypatch):
    svc = _make_db_with_finished_game()
    import app.services.database as db_module
    monkeypatch.setattr(db_module, "_db_service", svc)
    from app.services.stats_service import get_game_box_score
    box = get_game_box_score(999)
    assert "timeline_events" in box
    assert "total_seconds" in box
    assert isinstance(box["timeline_events"], list)
    assert box["total_seconds"] in (3600, 4200)
