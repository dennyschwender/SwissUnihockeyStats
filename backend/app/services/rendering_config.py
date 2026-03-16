"""
Rendering exclusion configuration.

Stores which leagues / clubs / teams should be hidden from all public pages.
Config is persisted to ``data/rendering_config.json`` so it survives restarts.

Supported filters (all optional, default to empty lists = "hide nothing"):
  excluded_league_ids    – list of int  (API ``league_id``)
  excluded_league_names  – list of str  (exact name match)
  excluded_club_ids      – list of int  (API club id)
  excluded_club_names    – list of str  (exact ``text`` match)
  excluded_team_ids      – list of int  (DB team id)
  excluded_team_names    – list of str  (exact ``text``/``name`` match)
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.config import settings as _settings

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG: dict[str, list] = {
    "excluded_league_ids": [],
    "excluded_league_names": ["Herren Test"],  # pre-populate the existing hardcoded exclusion
    "excluded_club_ids": [],
    "excluded_club_names": [],
    "excluded_team_ids": [],
    "excluded_team_names": [],
}

# Data directory derived from settings.DATABASE_PATH so it works both locally
# and in Docker (where DATABASE_PATH is overridden via env to /app/data/...).
_DATA_DIR = Path(_settings.DATABASE_PATH).parent
_CONFIG_PATH = _DATA_DIR / "rendering_config.json"

_lock = threading.Lock()


def _load() -> dict[str, list]:
    """Load from disk on every call.

    No in-memory cache: with gunicorn multi-worker each process has its own
    address space.  Caching would cause workers that didn't handle the POST
    to keep serving stale values, making the admin UI oscillate between the
    old and new settings.  The config file is tiny (~200 B) so disk reads
    are negligible.
    """
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = json.load(f)
        cfg: dict[str, list] = {}
        for key, default_val in _DEFAULT_CONFIG.items():
            val = raw.get(key, default_val)
            if not isinstance(val, list):
                val = default_val
            cfg[key] = val
        return cfg
    except FileNotFoundError:
        _save_to_disk(_DEFAULT_CONFIG)
        return dict(_DEFAULT_CONFIG)
    except Exception as exc:
        logger.warning(
            "rendering_config: failed to load %s: %s — using defaults", _CONFIG_PATH, exc
        )
        return dict(_DEFAULT_CONFIG)


def _save_to_disk(cfg: dict[str, list]) -> None:
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        tmp.replace(_CONFIG_PATH)
    except Exception as exc:
        logger.error("rendering_config: failed to save: %s", exc)


def get_config() -> dict[str, list]:
    """Return a copy of the current rendering exclusion config."""
    with _lock:
        return dict(_load())


def set_config(new_cfg: dict[str, list]) -> dict[str, list]:
    """Validate, persist, and return the updated config."""
    validated: dict[str, list] = {}
    for key in _DEFAULT_CONFIG:
        val = new_cfg.get(key, [])
        if not isinstance(val, list):
            raise ValueError(f"'{key}' must be a list")
        validated[key] = val
    with _lock:
        _save_to_disk(validated)
    return dict(validated)


# ─── Convenience helpers used by route handlers ──────────────────────────────


def filter_leagues(leagues: list[dict]) -> list[dict]:
    """Remove excluded leagues from a list of league dicts.
    Each dict must have ``league_id`` (int) and ``name`` (str).
    """
    cfg = get_config()
    exc_ids = set(cfg.get("excluded_league_ids") or [])
    exc_names = set(cfg.get("excluded_league_names") or [])
    if not exc_ids and not exc_names:
        return leagues
    return [
        lg
        for lg in leagues
        if lg.get("league_id") not in exc_ids and lg.get("name") not in exc_names
    ]


def filter_teams(teams: list[dict]) -> list[dict]:
    """Remove excluded teams.
    Each dict must have ``id`` (int) and ``text``/``name`` (str).
    """
    cfg = get_config()
    exc_ids = set(cfg.get("excluded_team_ids") or [])
    exc_names = set(cfg.get("excluded_team_names") or [])
    if not exc_ids and not exc_names:
        return teams
    return [
        t
        for t in teams
        if t.get("id") not in exc_ids and (t.get("text") or t.get("name", "")) not in exc_names
    ]


def filter_clubs(clubs: list[dict]) -> list[dict]:
    """Remove excluded clubs.
    Accepts dicts that have ``id`` (int) and ``text`` (str) keys.
    """
    cfg = get_config()
    exc_ids = set(cfg.get("excluded_club_ids") or [])
    exc_names = set(cfg.get("excluded_club_names") or [])
    if not exc_ids and not exc_names:
        return clubs
    return [c for c in clubs if c.get("id") not in exc_ids and c.get("text", "") not in exc_names]
