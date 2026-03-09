"""
Tests for cooldown persistence helpers _load_cooldowns() / _persist_cooldowns()
in app.main.
"""
import json
import os
import pytest
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_persist_cooldowns_writes_to_file(tmp_path, monkeypatch):
    """_persist_cooldowns() writes _job_last_done entries to scheduler_config.json."""
    cfg_path = str(tmp_path / "scheduler_config.json")
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", cfg_path)

    import app.main as main_mod
    # Patch the module-level dict directly
    dt = datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(main_mod, "_job_last_done", {("full", 2025): dt})

    main_mod._persist_cooldowns()

    with open(cfg_path) as f:
        data = json.load(f)

    assert "cooldowns" in data
    assert "full:2025" in data["cooldowns"]
    assert data["cooldowns"]["full:2025"] == dt.isoformat()


def test_load_cooldowns_reads_from_file(tmp_path, monkeypatch):
    """_load_cooldowns() populates _job_last_done from scheduler_config.json."""
    cfg_path = str(tmp_path / "scheduler_config.json")
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", cfg_path)

    dt_str = "2026-03-09T12:00:00+00:00"
    _write_config(cfg_path, {"cooldowns": {"clubs:2024": dt_str}})

    import app.main as main_mod
    # Reset the dict so we can observe the load
    monkeypatch.setattr(main_mod, "_job_last_done", {})

    main_mod._load_cooldowns()

    expected_dt = datetime.fromisoformat(dt_str)
    assert ("clubs", 2024) in main_mod._job_last_done
    assert main_mod._job_last_done[("clubs", 2024)] == expected_dt


def test_load_cooldowns_missing_file_is_noop(tmp_path, monkeypatch):
    """_load_cooldowns() with no file present raises no exception and leaves dict unchanged."""
    cfg_path = str(tmp_path / "nonexistent_scheduler_config.json")
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", cfg_path)

    import app.main as main_mod
    sentinel = {("teams", 2025): datetime(2026, 1, 1, tzinfo=timezone.utc)}
    monkeypatch.setattr(main_mod, "_job_last_done", dict(sentinel))

    # Should not raise
    main_mod._load_cooldowns()

    # Dict is unchanged when file is missing
    assert main_mod._job_last_done == sentinel


def test_persist_load_roundtrip(tmp_path, monkeypatch):
    """Persisting cooldowns and loading them back yields identical values."""
    cfg_path = str(tmp_path / "scheduler_config.json")
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", cfg_path)

    import app.main as main_mod

    original = {
        ("full", 2025): datetime(2026, 3, 9, 8, 30, 0, tzinfo=timezone.utc),
        ("clubs", 2024): datetime(2025, 11, 1, 0, 0, 0, tzinfo=timezone.utc),
    }
    monkeypatch.setattr(main_mod, "_job_last_done", dict(original))

    main_mod._persist_cooldowns()

    # Clear and reload
    monkeypatch.setattr(main_mod, "_job_last_done", {})
    main_mod._load_cooldowns()

    assert main_mod._job_last_done == original


def test_persist_cooldowns_preserves_existing_scheduler_keys(tmp_path, monkeypatch):
    """_persist_cooldowns() does not clobber existing keys in scheduler_config.json."""
    cfg_path = str(tmp_path / "scheduler_config.json")
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", cfg_path)

    # Pre-populate file with a scheduler key
    _write_config(cfg_path, {"enabled": True, "interval_minutes": 60})

    import app.main as main_mod
    dt = datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(main_mod, "_job_last_done", {("games", 2025): dt})

    main_mod._persist_cooldowns()

    with open(cfg_path) as f:
        data = json.load(f)

    # Scheduler keys must still be present
    assert data.get("enabled") is True
    assert data.get("interval_minutes") == 60
    # And cooldowns should be written
    assert "cooldowns" in data
    assert "games:2025" in data["cooldowns"]


def test_load_cooldowns_skips_malformed_entries(tmp_path, monkeypatch):
    """_load_cooldowns() silently skips entries that cannot be parsed."""
    cfg_path = str(tmp_path / "scheduler_config.json")
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", cfg_path)

    _write_config(cfg_path, {
        "cooldowns": {
            "valid:2025": "2026-03-09T12:00:00+00:00",
            "no_colon_here": "2026-03-09T12:00:00+00:00",   # bad key
            "bad:season": "2026-03-09T12:00:00+00:00",       # season not int
            "good:2024": "not-a-datetime",                    # bad datetime
        }
    })

    import app.main as main_mod
    monkeypatch.setattr(main_mod, "_job_last_done", {})

    main_mod._load_cooldowns()

    # Only the valid entry should be loaded
    assert ("valid", 2025) in main_mod._job_last_done
    assert len(main_mod._job_last_done) == 1
