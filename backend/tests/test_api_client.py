"""Tests for CacheManager in api_client.py."""

import time


def test_purge_expired_deletes_stale_files(tmp_path):
    from app.services.api_client import CacheManager

    cm = CacheManager(str(tmp_path))
    # Write a file with a TTL already expired
    cm.set("/api/test", {}, {"data": "x"}, ttl=1)
    time.sleep(2)
    # Write a fresh file
    cm.set("/api/fresh", {}, {"data": "y"}, ttl=3600)
    result = cm.purge_expired()
    assert result["expired_deleted"] == 1
    assert result["orphaned_deleted"] == 0
    assert result["bytes_freed_mb"] >= 0
    # Fresh file still exists
    stats = cm.get_stats()
    assert stats["total_entries"] == 1


def test_purge_orphaned_deletes_untracked_files(tmp_path):
    from app.services.api_client import CacheManager

    cm = CacheManager(str(tmp_path))
    # Drop a file directly with no metadata
    orphan = tmp_path / "general" / "deadbeef.json"
    orphan.parent.mkdir(exist_ok=True)
    orphan.write_text('{"x": 1}')
    result = cm.purge_expired()
    assert result["orphaned_deleted"] == 1


def test_purge_cache_policy_in_scheduler():
    from app.services.scheduler import POLICIES

    names = {p["name"] for p in POLICIES}
    assert "purge_cache" in names
    policy = next(p for p in POLICIES if p["name"] == "purge_cache")
    assert policy["scope"] == "global"
    assert policy["run_at_hour"] == 4
