"""Convenience functions for common API operations."""

import configparser
import os
from typing import Any, Dict, Optional
from .client import SwissUnihockeyClient


def _get_client_from_config(config_path: str = "config.ini") -> SwissUnihockeyClient:
    """
    Create a client from config file.

    Args:
        config_path: Path to config.ini file

    Returns:
        Configured SwissUnihockeyClient
    """
    config = configparser.ConfigParser()
    
    # Look for config in parent directory if not found
    if not os.path.exists(config_path):
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(parent_dir, "config.ini")
    
    config.read(config_path)
    
    return SwissUnihockeyClient(
        base_url=config.get("API", "base_url", fallback="https://api-v2.swissunihockey.ch"),
        locale=config.get("API", "default_locale", fallback="de-CH"),
        timeout=config.getint("API", "timeout", fallback=30),
    )


# Convenience functions using default config
def get_clubs() -> Dict[str, Any]:
    """Fetch all clubs using default config."""
    with _get_client_from_config() as client:
        return client.get_clubs()


def get_leagues() -> Dict[str, Any]:
    """Fetch all leagues using default config."""
    with _get_client_from_config() as client:
        return client.get_leagues()


def get_seasons() -> Dict[str, Any]:
    """Fetch all seasons using default config."""
    with _get_client_from_config() as client:
        return client.get_seasons()


def get_teams(**params) -> Dict[str, Any]:
    """Fetch teams using default config."""
    with _get_client_from_config() as client:
        return client.get_teams(**params)


def get_games(**params) -> Dict[str, Any]:
    """Fetch games using default config."""
    with _get_client_from_config() as client:
        return client.get_games(**params)


def get_rankings(**params) -> Dict[str, Any]:
    """Fetch rankings using default config."""
    with _get_client_from_config() as client:
        return client.get_rankings(**params)


def get_topscorers(**params) -> Dict[str, Any]:
    """Fetch top scorers using default config."""
    with _get_client_from_config() as client:
        return client.get_topscorers(**params)


def get_players(**params) -> Dict[str, Any]:
    """Fetch players using default config."""
    with _get_client_from_config() as client:
        return client.get_players(**params)
