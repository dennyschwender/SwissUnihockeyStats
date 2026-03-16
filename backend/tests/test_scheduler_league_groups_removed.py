"""Tests verifying that the redundant league_groups scheduled policy has been
removed while manual-trigger support (via _TASK_META and DataIndexer) remains."""

from app.services.scheduler import POLICIES


def test_league_groups_policy_not_in_policies():
    """league_groups entry must not appear in POLICIES — games job handles on-the-fly."""
    names = [p["name"] for p in POLICIES]
    assert "league_groups" not in names


def test_groups_task_meta_still_exists():
    """'groups' key must remain in _TASK_META so the manual trigger is preserved."""
    from app.main import _TASK_META

    assert "groups" in _TASK_META


def test_index_groups_function_still_exists():
    """DataIndexer.index_groups_for_league must still exist for manual / CLI use."""
    from app.services.data_indexer import DataIndexer

    assert hasattr(DataIndexer, "index_groups_for_league")
