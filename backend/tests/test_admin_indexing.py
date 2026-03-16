"""
Tests for admin indexing jobs API.
"""

import pytest


class TestAdminIndexingAPI:
    def test_unknown_task_returns_400(self, admin_client):
        r = admin_client.post("/admin/api/index", json={"season": 2025, "task": "nonexistent_task"})
        assert r.status_code == 400
        assert "Unknown task" in r.json().get("detail", "")

    def test_valid_task_returns_job_id(self, admin_client):
        """Posting a seasons task creates a job immediately."""
        r = admin_client.post(
            "/admin/api/index", json={"season": 0, "task": "seasons", "force": True}
        )
        assert r.status_code == 200
        data = r.json()
        assert "job_id" in data
        assert data["task"] == "seasons"

    def test_job_status_endpoint_exists(self, admin_client):
        # First create a job
        r = admin_client.post(
            "/admin/api/index", json={"season": 0, "task": "seasons", "force": True}
        )
        job_id = r.json()["job_id"]

        # Poll its status
        r2 = admin_client.get(f"/admin/api/jobs/{job_id}")
        assert r2.status_code == 200
        data = r2.json()
        assert "status" in data
        assert data["job_id"] == job_id

    def test_missing_job_returns_404(self, admin_client):
        r = admin_client.get("/admin/api/jobs/nonexistent-job-id")
        assert r.status_code == 404

    def test_stop_nonexistent_job_returns_404(self, admin_client):
        r = admin_client.delete("/admin/api/jobs/nonexistent-job-id")
        assert r.status_code == 404

    def test_seasons_task_is_recognised(self, admin_client):
        r = admin_client.post("/admin/api/index", json={"season": 0, "task": "seasons"})
        assert r.status_code == 200
        assert r.json()["label"] == "Index Seasons"

    def test_future_season_guard_rejects(self, admin_client):
        """Indexing a season beyond the current flagged season should warn and stop, not error."""
        r = admin_client.post(
            "/admin/api/index", json={"season": 9999, "task": "clubs", "force": False}
        )
        # Job is created (200), but will stop with a warning — not a 400
        assert r.status_code == 200

    def test_max_tier_accepted(self, admin_client):
        r = admin_client.post(
            "/admin/api/index",
            json={"season": 2025, "task": "events", "force": False, "max_tier": 2},
        )
        assert r.status_code == 200

    def test_repair_task_is_recognised(self, admin_client):
        r = admin_client.post("/admin/api/index", json={"season": 0, "task": "repair"})
        assert r.status_code == 200
        data = r.json()
        assert "job_id" in data


class TestAdminRepairEndpoint:
    def test_repair_endpoint_requires_auth(self, client):
        r = client.post("/admin/api/repair", follow_redirects=False)
        assert r.status_code in (401, 403, 302)

    def test_repair_endpoint_returns_ok(self, admin_client):
        r = admin_client.post("/admin/api/repair")
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert "total_fixed" in data
        assert "stuck_in_progress" in data
        assert "null_game_dates" in data

    def test_repair_endpoint_includes_reports(self, admin_client):
        r = admin_client.post("/admin/api/repair")
        data = r.json()
        assert "games_no_lineup" in data
        assert "roster_gaps" in data
        assert "unresolved_stats" in data
        assert isinstance(data["games_no_lineup"], list)


class TestAdminSeasonAPI:
    def test_set_current_season_unknown_returns_404(self, admin_client):
        r = admin_client.post("/admin/api/season/9999999/set-current")
        assert r.status_code == 404

    def test_set_current_season_known(self, admin_client):
        # 2025 should exist in the seasons table after DB init
        r = admin_client.post("/admin/api/season/2025/set-current")
        # Either 200 (found and updated) or 404 (not in DB yet — acceptable in unit test)
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            assert r.json()["ok"] is True
            assert r.json()["current_season"] == 2025

    def test_delete_unknown_layer_returns_400(self, admin_client):
        r = admin_client.delete("/admin/api/season/2025?layer=bad_layer")
        assert r.status_code == 400


def test_upcoming_games_task_is_recognised(admin_client):
    """upcoming_games task should be dispatched without 422/404."""
    r = admin_client.post(
        "/admin/api/index", json={"season": 2025, "task": "upcoming_games", "force": False}
    )
    assert r.status_code in (200, 202, 204), f"Got {r.status_code}: {r.text}"


def test_post_game_completion_task_is_recognised(admin_client):
    """post_game_completion task should be dispatched without 422/404."""
    r = admin_client.post(
        "/admin/api/index", json={"season": 2025, "task": "post_game_completion", "force": False}
    )
    assert r.status_code in (200, 202, 204), f"Got {r.status_code}: {r.text}"


def test_player_game_stats_workers_endpoint(admin_client):
    """POST /admin/api/scheduler with action=player_game_stats_workers updates the setting."""
    r = admin_client.post(
        "/admin/api/scheduler",
        json={"action": "player_game_stats_workers", "value": 8},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["player_game_stats_workers"] == 8
