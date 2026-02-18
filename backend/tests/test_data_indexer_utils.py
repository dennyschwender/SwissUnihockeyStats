"""
Tests for the data_indexer helper functions (league tiers, current season logic).
No network calls — pure unit tests.
"""
import pytest


class TestLeagueTiers:
    def test_nla_ids_are_tier_1(self):
        from app.services.data_indexer import league_tier
        assert league_tier(1)  == 1   # oldest NLA name
        assert league_tier(10) == 1   # SML (intermediate)
        assert league_tier(24) == 1   # L-UPL (current)

    def test_nlb_is_tier_2(self):
        from app.services.data_indexer import league_tier
        assert league_tier(2) == 2

    def test_lower_leagues_have_higher_tiers(self):
        from app.services.data_indexer import league_tier
        assert league_tier(3) == 3   # 1. Liga
        assert league_tier(4) == 4   # 2. Liga
        assert league_tier(5) == 5   # 3. Liga
        assert league_tier(6) == 6   # 4. Liga

    def test_unknown_league_returns_default_7(self):
        from app.services.data_indexer import league_tier
        assert league_tier(99999) == 7

    def test_tier_labels_cover_all_tiers(self):
        from app.services.data_indexer import TIER_LABELS
        for tier in range(1, 8):
            assert tier in TIER_LABELS, f"Tier {tier} missing from TIER_LABELS"

    def test_league_tiers_dict_values_in_range(self):
        from app.services.data_indexer import LEAGUE_TIERS
        for league_id, tier in LEAGUE_TIERS.items():
            assert 1 <= tier <= 7, f"league_id={league_id} has out-of-range tier={tier}"


class TestGetCurrentSeason:
    def test_returns_integer(self):
        from app.main import get_current_season
        result = get_current_season()
        assert isinstance(result, int)

    def test_result_is_plausible_year(self):
        from app.main import get_current_season
        result = get_current_season()
        assert 2020 <= result <= 2030, f"Unexpected season year: {result}"

    def test_date_fallback(self):
        """Calling get_current_season() without crashing is sufficient
        (DB may or may not be available; date fallback takes over automatically)."""
        from app.main import get_current_season
        result = get_current_season()
        assert isinstance(result, int)
        assert 2020 <= result <= 2035
