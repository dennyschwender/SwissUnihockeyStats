"""Tests for cache functionality."""

import json
import pytest
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from api.cache import CacheManager


class TestCacheManager:
    """Test cases for CacheManager."""

    def setup_method(self):
        """Setup test cache directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheManager(cache_dir=self.temp_dir)

    def teardown_method(self):
        """Cleanup test cache directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_initialization(self):
        """Test cache manager initializes correctly."""
        assert self.cache.cache_dir.exists()
        assert self.cache.metadata == {}

    def test_cache_directory_creation(self):
        """Test cache directory is created automatically."""
        new_dir = tempfile.mktemp()
        cache = CacheManager(cache_dir=new_dir)
        assert Path(new_dir).exists()
        # Cleanup
        import shutil
        shutil.rmtree(new_dir, ignore_errors=True)

    def test_get_cache_key_consistent(self):
        """Test cache key generation is consistent."""
        key1 = self.cache._get_cache_key("/api/clubs", {"locale": "de"})
        key2 = self.cache._get_cache_key("/api/clubs", {"locale": "de"})
        assert key1 == key2

    def test_get_cache_key_params_order_independent(self):
        """Test cache key is same regardless of param order."""
        key1 = self.cache._get_cache_key("/api/test", {"a": 1, "b": 2})
        key2 = self.cache._get_cache_key("/api/test", {"b": 2, "a": 1})
        assert key1 == key2

    def test_get_cache_key_different_endpoints(self):
        """Test different endpoints produce different keys."""
        key1 = self.cache._get_cache_key("/api/clubs", {})
        key2 = self.cache._get_cache_key("/api/teams", {})
        assert key1 != key2

    def test_get_cache_key_different_params(self):
        """Test different params produce different keys."""
        key1 = self.cache._get_cache_key("/api/clubs", {"id": 1})
        key2 = self.cache._get_cache_key("/api/clubs", {"id": 2})
        assert key1 != key2

    def test_set_and_get_cache(self):
        """Test setting and getting cached data."""
        data = {"test": "data", "value": 123}
        self.cache.set("/api/test", {}, data)
        
        retrieved = self.cache.get("/api/test", {})
        assert retrieved == data

    def test_cache_miss_returns_none(self):
        """Test cache returns None for non-existent data."""
        result = self.cache.get("/api/nonexistent", {})
        assert result is None

    def test_cache_with_category(self):
        """Test caching with different categories."""
        data1 = {"type": "clubs"}
        data2 = {"type": "teams"}
        
        self.cache.set("/api/data", {}, data1, category="clubs")
        self.cache.set("/api/data", {}, data2, category="teams")
        
        # Same endpoint, different categories should return different data
        result1 = self.cache.get("/api/data", {}, category="clubs")
        result2 = self.cache.get("/api/data", {}, category="teams")
        
        assert result1 == data1
        assert result2 == data2

    def test_cache_expiration(self):
        """Test that expired cache returns None."""
        data = {"test": "data"}
        # Set cache with very short TTL (1 second)
        self.cache.set("/api/test", {}, data, ttl=1)
        
        # Should get data immediately
        assert self.cache.get("/api/test", {}) == data
        
        # Wait for expiration
        time.sleep(1.1)
        
        # Should return None after expiration
        assert self.cache.get("/api/test", {}) is None

    def test_determine_ttl_static_data(self):
        """Test TTL determination for static data."""
        ttl = self.cache._determine_ttl("/api/clubs")
        assert ttl == self.cache.TTL_CONFIG["static"]
        
        ttl = self.cache._determine_ttl("/api/seasons")
        assert ttl == self.cache.TTL_CONFIG["static"]

    def test_determine_ttl_semi_static_data(self):
        """Test TTL determination for semi-static data."""
        ttl = self.cache._determine_ttl("/api/teams")
        assert ttl == self.cache.TTL_CONFIG["semi_static"]
        
        ttl = self.cache._determine_ttl("/api/players")
        assert ttl == self.cache.TTL_CONFIG["semi_static"]

    def test_determine_ttl_dynamic_data(self):
        """Test TTL determination for dynamic data."""
        ttl = self.cache._determine_ttl("/api/rankings")
        assert ttl == self.cache.TTL_CONFIG["dynamic"]

    def test_determine_ttl_realtime_data(self):
        """Test TTL determination for real-time data."""
        ttl = self.cache._determine_ttl("/api/game_events/123")
        assert ttl == self.cache.TTL_CONFIG["realtime"]
        
        ttl = self.cache._determine_ttl("/api/live/scores")
        assert ttl == self.cache.TTL_CONFIG["realtime"]

    def test_clear_all_cache(self):
        """Test clearing all cache."""
        self.cache.set("/api/test1", {}, {"data": 1})
        self.cache.set("/api/test2", {}, {"data": 2})
        
        self.cache.clear()
        
        assert self.cache.get("/api/test1", {}) is None
        assert self.cache.get("/api/test2", {}) is None
        assert len(self.cache.metadata) == 0

    def test_clear_category_cache(self):
        """Test clearing cache by category."""
        self.cache.set("/api/test1", {}, {"data": 1}, category="clubs")
        self.cache.set("/api/test2", {}, {"data": 2}, category="teams")
        
        self.cache.clear(category="clubs")
        
        assert self.cache.get("/api/test1", {}, category="clubs") is None
        assert self.cache.get("/api/test2", {}, category="teams") == {"data": 2}

    def test_get_stats(self):
        """Test getting cache statistics."""
        self.cache.set("/api/test1", {}, {"data": 1}, category="clubs")
        self.cache.set("/api/test2", {}, {"data": 2}, category="teams")
        
        stats = self.cache.get_stats()
        
        assert stats["total_entries"] == 2
        assert stats["total_files"] == 2
        assert "clubs" in stats["categories"]
        assert "teams" in stats["categories"]
        assert stats["categories"]["clubs"] == 1
        assert stats["categories"]["teams"] == 1

    def test_cache_with_params(self):
        """Test caching with query parameters."""
        data1 = {"result": "filtered"}
        data2 = {"result": "all"}
        
        self.cache.set("/api/items", {"filter": "active"}, data1)
        self.cache.set("/api/items", {}, data2)
        
        assert self.cache.get("/api/items", {"filter": "active"}) == data1
        assert self.cache.get("/api/items", {}) == data2

    def test_metadata_persistence(self):
        """Test metadata is saved and loaded correctly."""
        data = {"test": "data"}
        self.cache.set("/api/test", {}, data)
        
        # Create new cache instance with same directory
        new_cache = CacheManager(cache_dir=self.temp_dir)
        
        # Metadata should be loaded
        assert len(new_cache.metadata) > 0
        
        # Should be able to retrieve cached data
        assert new_cache.get("/api/test", {}) == data

    def test_cache_path_structure(self):
        """Test cache file path structure."""
        cache_key = self.cache._get_cache_key("/api/test", {})
        cache_path = self.cache._get_cache_path(cache_key, "clubs")
        
        assert "clubs" in str(cache_path)
        assert cache_key in str(cache_path)
        assert cache_path.suffix == ".json"

    def test_invalid_cache_file_handled(self):
        """Test that corrupted cache files are handled gracefully."""
        # Create a cache entry
        self.cache.set("/api/test", {}, {"data": "test"})
        
        # Corrupt the cache file
        cache_key = self.cache._get_cache_key("/api/test", {})
        cache_path = self.cache._get_cache_path(cache_key, "general")
        cache_path.write_text("invalid json{{{")
        
        # Should return None instead of crashing
        result = self.cache.get("/api/test", {})
        assert result is None

    def test_cache_size_calculation(self):
        """Test cache size calculation in stats."""
        # Create some cached data
        large_data = {"data": "x" * 1000}  # ~1KB of data
        self.cache.set("/api/test", {}, large_data)
        
        stats = self.cache.get_stats()
        assert stats["total_size_mb"] >= 0

    def test_custom_ttl(self):
        """Test setting custom TTL."""
        data = {"test": "data"}
        custom_ttl = 3600  # 1 hour
        
        self.cache.set("/api/test", {}, data, ttl=custom_ttl)
        
        cache_key = self.cache._get_cache_key("/api/test", {})
        metadata = self.cache.metadata[cache_key]
        assert metadata["ttl"] == custom_ttl

    def test_cache_metadata_structure(self):
        """Test cache metadata contains all required fields."""
        data = {"test": "data"}
        self.cache.set("/api/test", {"param": "value"}, data, category="test_cat")
        
        cache_key = self.cache._get_cache_key("/api/test", {"param": "value"})
        metadata = self.cache.metadata[cache_key]
        
        assert "endpoint" in metadata
        assert "params" in metadata
        assert "category" in metadata
        assert "cached_at" in metadata
        assert "ttl" in metadata
        
        assert metadata["endpoint"] == "/api/test"
        assert metadata["params"] == {"param": "value"}
        assert metadata["category"] == "test_cat"

    def test_metadata_file_corruption_handled(self):
        """Test that corrupted metadata file doesn't crash initialization."""
        # Create corrupted metadata file
        metadata_path = Path(self.temp_dir) / "metadata.json"
        metadata_path.write_text("invalid json{{{")
        
        # Should initialize with empty metadata instead of crashing
        cache = CacheManager(cache_dir=self.temp_dir)
        assert cache.metadata == {}

    def test_concurrent_category_access(self):
        """Test multiple categories can be accessed independently."""
        categories = ["clubs", "teams", "leagues", "rankings"]
        
        for i, category in enumerate(categories):
            self.cache.set(f"/api/{category}", {}, {"id": i}, category=category)
        
        # Verify each category has its data
        for i, category in enumerate(categories):
            data = self.cache.get(f"/api/{category}", {}, category=category)
            assert data == {"id": i}

    def test_cache_none_values(self):
        """Test caching None or empty values."""
        # Cache should store empty dicts
        self.cache.set("/api/empty", {}, {})
        result = self.cache.get("/api/empty", {})
        assert result == {}

    def test_cache_complex_data_structures(self):
        """Test caching complex nested data structures."""
        complex_data = {
            "entries": [
                {"id": 1, "name": "Test", "nested": {"value": [1, 2, 3]}},
                {"id": 2, "name": "Test2", "nested": {"value": [4, 5, 6]}}
            ],
            "metadata": {"count": 2, "page": 1}
        }
        
        self.cache.set("/api/complex", {}, complex_data)
        result = self.cache.get("/api/complex", {})
        
        assert result == complex_data
        assert result["entries"][0]["nested"]["value"] == [1, 2, 3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
