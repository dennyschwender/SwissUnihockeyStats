"""
Simplified tests for API endpoints (skeletons not yet implemented).
"""
import pytest
from fastapi.testclient import TestClient


class TestAPIEndpointsBasic:
    """Test that API endpoints are accessible and return JSON."""

    @pytest.mark.parametrize("endpoint", [
        "/api/v1/clubs/",
        "/api/v1/teams/",
        "/api/v1/leagues/",
        "/api/v1/games/",
    ])
    def test_api_endpoints_accessible(self, client, endpoint):
        """Test implemented API endpoints are accessible."""
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        
        # Should return valid JSON with total
        data = response.json()
        assert "total" in data
        assert isinstance(data["total"], int)

    def test_teams_api_with_filter(self, client):
        """Test teams API with filter parameter."""
        response = client.get("/api/v1/teams/?club=1")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data

    def test_api_limit_parameter(self, client):
        """Test API limit parameter works."""
        response = client.get("/api/v1/clubs/?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data

    def test_api_response_time(self, client):
        """Test API responds within reasonable time."""
        import time
        start = time.time()
        response = client.get("/api/v1/clubs/")
        elapsed = time.time() - start
        
        assert response.status_code == 200
        # Should respond within 5 seconds
        assert elapsed < 5.0


class TestLoadingSkeletons:
    """Tests for loading skeletons (to be implemented post-MVP)."""

    @pytest.mark.skip(reason="Loading skeletons not yet implemented")
    def test_skeleton_placeholder(self):
        """Placeholder for skeleton tests when feature is implemented."""
        pass
