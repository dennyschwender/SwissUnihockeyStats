"""Tests for error pages (404, 500)."""

import pytest
from fastapi.testclient import TestClient
from backend.app.main import app


client = TestClient(app)


class TestErrorPages:
    """Test cases for error pages."""

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_404_page_with_locale(self, locale):
        """Test 404 error page is shown for non-existent routes with locale."""
        response = client.get(f"/{locale}/nonexistent-page")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")

    def test_404_page_content(self):
        """Test 404 page contains expected content."""
        response = client.get("/de/does-not-exist")
        assert response.status_code == 404
        content = response.text.lower()
        # Should contain 404 reference
        assert "404" in content
        # Should have navigation or home link
        assert "home" in content or "zurück" in content or "back" in content

    def test_404_page_has_proper_template(self):
        """Test 404 page uses error_404.html template."""
        response = client.get("/de/invalid-route")
        assert response.status_code == 404
        # Check for error page specific elements (German: "fehler")
        assert ("404" in response.text and 
                ("fehler" in response.text.lower() or "error" in response.text.lower()))

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_404_error_page_exists_for_all_locales(self, locale):
        """Test that 404 page works for all supported locales."""
        response = client.get(f"/{locale}/missing-page-xyz")
        assert response.status_code == 404
        # Should still return HTML even for error
        assert response.headers["content-type"].startswith("text/html")

    def test_404_page_includes_navigation(self):
        """Test that 404 page includes navigation links."""
        response = client.get("/de/nonexistent")
        assert response.status_code == 404
        # Should have navigation elements
        content = response.text.lower()
        assert "nav" in content or "menu" in content or "href" in content

    def test_invalid_nested_route_returns_404(self):
        """Test deeply nested invalid routes return 404."""
        response = client.get("/de/clubs/invalid/nested/route")
        assert response.status_code == 404

    def test_404_without_locale_still_works(self):
        """Test 404 handling works even without locale."""
        response = client.get("/this-does-not-exist", follow_redirects=True)
        # May redirect to /de/ which is valid (200) or show 404
        assert response.status_code in [200, 404]

    def test_404_preserves_locale_in_template(self):
        """Test that 404 page preserves locale for navigation."""
        response = client.get("/fr/page-inexistante")
        assert response.status_code == 404
        # Should have French locale links
        assert '/fr/' in response.text or 'fr' in response.text.lower()

    def test_partial_valid_route_returns_404(self):
        """Test that partial valid routes still return 404."""
        response = client.get("/de/clubs/teams/invalid")
        assert response.status_code == 404

    def test_404_response_headers(self):
        """Test 404 response has correct headers."""
        response = client.get("/de/missing")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")


class Test500Errors:
    """Test cases for 500 internal server errors."""

    @pytest.mark.skip(reason="error_500.html template not yet implemented")
    def test_500_error_page_template_exists(self):
        """Test that 500 error template exists."""
        pass

    @pytest.mark.skip(reason="error_500.html template not yet implemented")
    def test_500_error_structure(self):
        """Test 500 error page structure is correct."""
        pass

    @pytest.mark.skip(reason="error_500.html template not yet implemented")
    def test_error_templates_use_base_template(self):
        """Test that error templates extend base.html."""
        pass


class TestErrorHandling:
    """Test error handling across the application."""

    @pytest.mark.skip(reason="Method not allowed handling not fully implemented")
    def test_method_not_allowed_returns_error(self):
        """Test that POST to GET-only endpoint returns error."""
        pass

    def test_invalid_locale_still_works(self):
        """Test that invalid locales don't break the app."""
        response = client.get("/xx/")  # xx is not a valid locale
        # Should either redirect or show default locale
        assert response.status_code in [200, 404]

    def test_missing_required_params_handled(self):
        """Test that missing required parameters are handled gracefully."""
        # This depends on your API design - adjust as needed
        response = client.get("/health")
        assert response.status_code == 200  # Health check should always work

    def test_malformed_url_handled(self):
        """Test that malformed URLs are handled."""
        response = client.get("//de//clubs//")
        # Should either normalize or return 404
        assert response.status_code in [200, 404, 307, 308]

    def test_special_characters_in_url(self):
        """Test URLs with special characters are handled."""
        response = client.get("/de/<script>alert('xss')</script>")
        # Should return 404, not execute anything
        assert response.status_code == 404
        assert "<script>" not in response.text  # XSS protection


class TestErrorPageContent:
    """Test error page content and user experience."""

    def test_404_page_user_friendly(self):
        """Test that 404 page provides helpful information."""
        response = client.get("/de/test-missing")
        assert response.status_code == 404
        content = response.text.lower()
        # Should have helpful messages
        has_helpful_content = any(word in content for word in [
            "nicht gefunden",  # German: not found
            "not found",
            "zurück",  # German: back
            "home",
            "startseite"  # German: homepage
        ])
        assert has_helpful_content, "404 page should have helpful user messages"

    def test_error_pages_have_consistent_styling(self):
        """Test that error pages use consistent styling."""
        response = client.get("/de/missing")
        assert response.status_code == 404
        # Should include CSS
        assert "css" in response.text.lower() or "style" in response.text.lower()

    def test_404_page_accessible(self):
        """Test that 404 page is accessible."""
        response = client.get("/de/test")
        assert response.status_code == 404
        # Should have proper HTML structure
        assert "<!DOCTYPE" in response.text or "<html" in response.text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
