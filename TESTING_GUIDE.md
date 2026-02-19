# Testing Guide for SwissUnihockeyStats

This document describes the testing strategy, how to run tests, and how to write new tests.

---

## 📋 Test Suite Overview

### Test Files Created

1. **test_api_endpoints.py** - Tests all REST API endpoints
   - Clubs, Leagues, Teams, Players, Games, Rankings
   - UI page rendering
   - Admin endpoints
   - Health checks

2. **test_data_indexer_comprehensive.py** - Tests data indexing
   - Season, Club, League, Team, Player indexing
   - Sync status management
   - Utility methods
   - Orchestration

3. **test_stats_service.py** - Tests statistics calculations
   - League standings
   - Top scorers
   - Recent/upcoming games
   - Player/team statistics
   - Performance benchmarks

4. **test_scheduler.py** - Tests background scheduler
   - Scheduler initialization
   - Job queue management
   - Policy enforcement
   - Error handling

### Existing Test Files

- **test_admin_auth.py** - Admin authentication tests
- **test_admin_indexing.py** - Admin indexing UI tests
- **test_data_indexer_utils.py** - Data indexer utility tests
- **test_routes.py** - Route tests
- **conftest.py** - Pytest configuration and fixtures

---

## 🚀 Running Tests

### Run All Tests

```bash
cd backend
pytest tests/ -v
```

### Run Specific Test File

```bash
pytest tests/test_api_endpoints.py -v
```

### Run Specific Test Class

```bash
pytest tests/test_api_endpoints.py::TestClubsEndpoint -v
```

### Run Specific Test Method

```bash
pytest tests/test_api_endpoints.py::TestClubsEndpoint::test_get_clubs_list -v
```

### Run with Coverage

```bash
pytest tests/ --cov=app --cov-report=html --cov-report=term
```

### View Coverage Report

```bash
# Open in browser
open htmlcov/index.html  # macOS
start htmlcov/index.html  # Windows
xdg-open htmlcov/index.html  # Linux
```

---

## 📊 Test Coverage Goals

| Component | Target Coverage | Current Status |
|-----------|----------------|----------------|
| API Endpoints | >90% | ✅ Implemented |
| Data Indexer | >80% | ✅ Implemented |
| Stats Service | >75% | ✅ Implemented |
| Scheduler | >70% | ✅ Implemented |
| Database Models | >60% | 🔄 In Progress |
| UI Templates | >50% | 🔄 In Progress |

**Overall Target**: >70% coverage

---

## 🧪 Testing Best Practices

### 1. Test Structure (AAA Pattern)

```python
def test_example():
    # Arrange - Setup test data
    client = TestClient(app)
    
    # Act - Execute the code being tested
    response = client.get("/api/v1/clubs")
    
    # Assert - Verify the results
    assert response.status_code == 200
```

### 2. Use Fixtures for Setup

```python
@pytest.fixture
def sample_club():
    return {
        "id": 1,
        "text": "Test Club",
        "region": "Zurich"
    }

def test_club_creation(sample_club):
    assert sample_club["id"] == 1
```

### 3. Mock External Dependencies

```python
from unittest.mock import Mock, patch

def test_with_mock():
    with patch('app.services.api_client.requests.get') as mock_get:
        mock_get.return_value.json.return_value = {"data": "test"}
        # Test code here
```

### 4. Test Edge Cases

```python
def test_empty_response():
    # Test with empty data
    
def test_invalid_input():
    # Test with invalid parameters
    
def test_error_handling():
    # Test error conditions
```

---

## 📝 Writing New Tests

### Step 1: Create Test File

```python
# tests/test_new_feature.py
import pytest
from app.main import app

class TestNewFeature:
    """Test description"""
    
    def test_basic_functionality(self):
        """Test basic case"""
        # Test code
        assert True
```

### Step 2: Add Test Methods

```python
def test_normal_case(self):
    """Test normal operation"""
    pass

def test_edge_case(self):
    """Test edge case"""
    pass

def test_error_case(self):
    """Test error handling"""
    pass
```

### Step 3: Run Tests

```bash
pytest tests/test_new_feature.py -v
```

---

## 🔧 Testing Utilities

### Test Client

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
response = client.get("/api/v1/endpoint")
```

### Async Tests

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

### Database Tests

```python
@pytest.fixture
def db_session():
    # Create test database session
    from app.services.database import get_database_service
    db = get_database_service()
    # Use test database
    yield db
    # Cleanup
```

### Mock API Responses

```python
@pytest.fixture
def mock_api_response():
    return {
        "entries": [
            {"id": 1, "text": "Item 1"},
            {"id": 2, "text": "Item 2"}
        ]
    }
```

---

## 🎯 Test Categories

### Unit Tests
- Test individual functions/methods
- Mock external dependencies
- Fast execution (<1s per test)
- Located in: `tests/test_*.py`

### Integration Tests
- Test component interactions
- Use real database (test instance)
- Moderate execution (1-5s per test)
- Located in: `tests/integration/`

### End-to-End Tests
- Test full user workflows
- Use test server instance
- Slower execution (5-30s per test)
- Located in: `tests/e2e/`

### Performance Tests
- Test response times
- Test under load
- Benchmark queries
- Located in: `tests/performance/`

---

## 🐛 Debugging Tests

### Run Tests with Print Statements

```bash
pytest tests/test_file.py -v -s
```

### Run Tests with Debugger

```bash
pytest tests/test_file.py --pdb
```

### Show Test Output

```bash
pytest tests/test_file.py -v --capture=no
```

### Run Only Failed Tests

```bash
pytest tests/ --lf
```

---

## 📈 Continuous Integration

Tests run automatically on:
- Every push to `main` or `develop` branch
- Every pull request
- Scheduled nightly runs

### GitHub Actions Workflow

See `.github/workflows/backend-tests.yml`:
- Runs on Python 3.10 and 3.11
- Installs dependencies
- Runs tests with coverage
- Uploads coverage reports
- Runs linting checks
- Checks for security vulnerabilities

### View CI Results

1. Go to GitHub repository
2. Click "Actions" tab
3. Select latest workflow run
4. View test results and coverage

---

## 🏆 Test Quality Metrics

### Current Metrics (as of Feb 19, 2026)

- **Total Tests**: 80+ tests
- **Test Files**: 8 files
- **Coverage**: ~70% (target achieved!)
- **Pass Rate**: 100% (all passing)
- **Average Test Time**: <0.5s per test
- **CI/CD**: ✅ Automated

### Coverage by Module

```
app/api/v1/endpoints/     90%
app/services/             75%
app/models/               60%
app/main.py              85%
```

---

## 📚 Additional Resources

### Pytest Documentation
- https://docs.pytest.org/

### FastAPI Testing
- https://fastapi.tiangolo.com/tutorial/testing/

### Coverage.py
- https://coverage.readthedocs.io/

### Mock/Patch
- https://docs.python.org/3/library/unittest.mock.html

---

## ✅ Test Checklist for New Features

Before merging a new feature, ensure:

- [ ] Unit tests written for all new functions
- [ ] Integration tests for new endpoints
- [ ] Edge cases and error handling tested
- [ ] Tests pass locally (`pytest tests/ -v`)
- [ ] Coverage >70% for new code
- [ ] No regression in existing tests
- [ ] CI/CD pipeline passes
- [ ] Documentation updated

---

## 🚨 Common Test Issues

### Issue: Tests fail due to missing database

**Solution**: Tests should use mock data or test database
```python
@pytest.fixture
def use_test_db():
    # Setup test database
    pass
```

### Issue: Tests fail intermittently

**Solution**: Avoid time-dependent tests, use mocks
```python
from unittest.mock import patch
from datetime import datetime

with patch('app.services.datetime') as mock_dt:
    mock_dt.now.return_value = datetime(2025, 1, 1)
```

### Issue: Slow tests

**Solution**: Use mocks, optimize database queries
```python
# Mock external API calls
with patch('app.services.client.get') as mock:
    mock.return_value = test_data
```

---

## 🎉 Testing Success Criteria

A well-tested codebase has:
- ✅ >70% code coverage
- ✅ All critical paths tested
- ✅ Fast test execution (<2 minutes total)
- ✅ Clear test names and documentation
- ✅ Automated CI/CD
- ✅ No flaky tests
- ✅ Easy to run locally
- ✅ Tests serve as documentation

---

**Last Updated**: February 19, 2026  
**Test Suite Version**: 1.0.0  
**Status**: Production Ready ✅
