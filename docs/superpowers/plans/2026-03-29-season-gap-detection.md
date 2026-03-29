# Season Gap Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `min_season` is configured, automatically force `index_seasons` whenever seasons in the range `[min_season, current_season]` are missing from the DB.

**Architecture:** Add ~15 lines to `_refresh_queue` in `scheduler.py`. After computing `indexed_seasons`, check for year gaps against the configured `min_season`. If gaps exist and no seasons job is already running/queued, launch a forced `index_seasons` job immediately. Thread `force=True` through `_launch_and_return_id`.

**Tech Stack:** Python asyncio, SQLAlchemy, existing `Scheduler` / `ScheduledJob` / `JobRecord` dataclasses.

---

### Task 1: Thread `force` through `_launch_and_return_id`

**Files:**
- Modify: `backend/app/services/scheduler.py` (method `_launch_and_return_id` and its call in `trigger_now`)

Currently `_launch_and_return_id` always passes `force=False` to `self._submit`. We need it to accept a `force` argument so the gap-fill path can bypass the 30-day cache.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_scheduler.py` inside the existing test file (after the last test class):

```python
class TestLaunchAndReturnIdForce:
    """_launch_and_return_id passes force flag to _submit"""

    @pytest.mark.asyncio
    async def test_force_flag_forwarded(self, mock_admin_jobs):
        captured = {}

        async def submit(job_id, season, task, force=False, max_tier=7):
            captured["force"] = force

        sched = Scheduler(mock_admin_jobs, submit)
        from app.services.scheduler import ScheduledJob, _utcnow, POLICIES
        policy = next(p for p in POLICIES if p["name"] == "seasons")
        job = ScheduledJob(
            run_at=_utcnow(),
            priority=policy["priority"],
            policy_name=policy["name"],
            task=policy["task"],
            season=None,
            label="test",
            max_tier=policy.get("max_tier", 7),
        )
        await sched._launch_and_return_id(job, force=True)
        assert captured["force"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py::TestLaunchAndReturnIdForce -v
```

Expected: `FAILED` — `TypeError: _launch_and_return_id() got an unexpected keyword argument 'force'`

- [ ] **Step 3: Add `force` parameter to `_launch_and_return_id`**

In `backend/app/services/scheduler.py`, find:

```python
    async def _launch_and_return_id(self, job: ScheduledJob) -> str:
        """Like _launch() but returns the job_id."""
        job_id = str(uuid.uuid4())[:8]
```

Replace with:

```python
    async def _launch_and_return_id(self, job: ScheduledJob, force: bool = False) -> str:
        """Like _launch() but returns the job_id."""
        job_id = str(uuid.uuid4())[:8]
```

Then find (a few lines below):

```python
            await self._submit(job_id, job.season, job.task, False, job.max_tier)
```

Replace with:

```python
            await self._submit(job_id, job.season, job.task, force, job.max_tier)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py::TestLaunchAndReturnIdForce -v
```

Expected: `PASSED`

- [ ] **Step 5: Run full test suite**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/services/scheduler.py tests/test_scheduler.py
git commit -m "feat: thread force flag through _launch_and_return_id"
```

---

### Task 2: Add gap detection to `_refresh_queue`

**Files:**
- Modify: `backend/app/services/scheduler.py` (method `_refresh_queue`)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_scheduler.py`:

```python
class TestSeasonGapDetection:
    """_refresh_queue forces index_seasons when seasons are missing from DB"""

    @pytest.mark.asyncio
    async def test_gap_triggers_forced_seasons_job(self, mock_admin_jobs):
        launched = []

        async def submit(job_id, season, task, force=False, max_tier=7):
            launched.append({"task": task, "force": force})

        sched = Scheduler(mock_admin_jobs, submit)
        sched._min_season = 2020

        # Simulate DB returning only season 2025 (highlighted), missing 2020-2024
        from unittest.mock import patch, MagicMock
        mock_season_rows = [(2025, True)]  # (id, highlighted)

        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = mock_season_rows
        # Season.is_frozen query returns None (not frozen)
        mock_session.query.return_value.filter.return_value.scalar.return_value = None

        mock_db = MagicMock()
        mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.scheduler.get_database_service", return_value=mock_db):
            await sched._refresh_queue()

        seasons_jobs = [j for j in launched if j["task"] == "seasons"]
        assert len(seasons_jobs) == 1
        assert seasons_jobs[0]["force"] is True

    @pytest.mark.asyncio
    async def test_no_gap_no_forced_job(self, mock_admin_jobs):
        launched = []

        async def submit(job_id, season, task, force=False, max_tier=7):
            launched.append({"task": task, "force": force})

        sched = Scheduler(mock_admin_jobs, submit)
        sched._min_season = 2025

        from unittest.mock import patch, MagicMock
        mock_season_rows = [(2025, True)]
        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = mock_season_rows
        mock_session.query.return_value.filter.return_value.scalar.return_value = None

        mock_db = MagicMock()
        mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.scheduler.get_database_service", return_value=mock_db):
            await sched._refresh_queue()

        forced_seasons = [j for j in launched if j["task"] == "seasons" and j["force"]]
        assert len(forced_seasons) == 0

    @pytest.mark.asyncio
    async def test_gap_skipped_when_seasons_job_already_queued(self, mock_admin_jobs):
        launched = []

        async def submit(job_id, season, task, force=False, max_tier=7):
            launched.append({"task": task, "force": force})

        sched = Scheduler(mock_admin_jobs, submit)
        sched._min_season = 2020

        # Pre-queue a seasons job
        from app.services.scheduler import ScheduledJob, _utcnow
        sched._queue.append(ScheduledJob(
            run_at=_utcnow(),
            priority=10,
            policy_name="seasons",
            task="seasons",
            season=None,
            label="already queued",
        ))

        from unittest.mock import patch, MagicMock
        mock_season_rows = [(2025, True)]
        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = mock_season_rows
        mock_session.query.return_value.filter.return_value.scalar.return_value = None

        mock_db = MagicMock()
        mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.scheduler.get_database_service", return_value=mock_db):
            await sched._refresh_queue()

        forced_seasons = [j for j in launched if j["task"] == "seasons" and j["force"]]
        assert len(forced_seasons) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py::TestSeasonGapDetection -v
```

Expected: all 3 `FAILED` (gap detection logic doesn't exist yet).

- [ ] **Step 3: Add gap detection to `_refresh_queue`**

In `backend/app/services/scheduler.py`, find the end of the `with db_service.session_scope() as session:` block inside `_refresh_queue` — just before the closing `except Exception` line of the first try block. The block ends after the async yield loop:

```python
                            if _itr % _YIELD_EVERY == 0:
                                await asyncio.sleep(0)

        except Exception as exc:
            logger.error("[scheduler] refresh_queue error: %s", exc, exc_info=True)
```

Insert the gap detection block **inside** the `with session_scope()` block, immediately after the season-policy loop (after the `await asyncio.sleep(0)` line and before the `except`):

```python
                            if _itr % _YIELD_EVERY == 0:
                                await asyncio.sleep(0)

                # ── Gap detection: force index_seasons if expected seasons missing ──
                if self._min_season is not None and current_season_id is not None:
                    expected = set(range(self._min_season, current_season_id + 1))
                    missing = expected - set(indexed_seasons)
                    if missing:
                        already_queued = any(
                            j.policy_name == "seasons" for j in self._queue
                        ) or any(
                            r.policy_name == "seasons" and r.status in ("pending", "running")
                            for r in self._history
                        )
                        if not already_queued:
                            seasons_policy = next(
                                p for p in POLICIES if p["name"] == "seasons"
                            )
                            job = ScheduledJob(
                                run_at=_utcnow(),
                                priority=seasons_policy["priority"],
                                policy_name=seasons_policy["name"],
                                task=seasons_policy["task"],
                                season=None,
                                label=seasons_policy["label"] + " (gap fill)",
                                max_tier=seasons_policy.get("max_tier", 7),
                            )
                            logger.info(
                                "[scheduler] season gap detected (missing %s), forcing index_seasons",
                                sorted(missing),
                            )
                            await self._launch_and_return_id(job, force=True)

        except Exception as exc:
            logger.error("[scheduler] refresh_queue error: %s", exc, exc_info=True)
```

- [ ] **Step 4: Run gap detection tests**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py::TestSeasonGapDetection -v
```

Expected: all 3 `PASSED`.

- [ ] **Step 5: Run full test suite**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/services/scheduler.py tests/test_scheduler.py
git commit -m "feat: force index_seasons when configured seasons are missing from DB"
```

---

### Task 3: Verify on the running instance

- [ ] **Step 1: Deploy**

On `pi4desk`:

```bash
cd ~/dockerimages/SwissUnihockeyStats
docker compose build --no-cache && docker compose up -d --force-recreate
```

- [ ] **Step 2: Confirm gap detection fires**

```bash
docker compose logs -f | grep "season gap detected"
```

Expected within one scheduler tick (~60 s): a log line like:
```
[scheduler] season gap detected (missing {2019, 2020, ...}), forcing index_seasons
```

- [ ] **Step 3: Confirm seasons appear in DB**

Open the admin Seasons view at `https://swissunihockeystats.mennylenderr.ch/admin` and confirm the previously-missing seasons now appear after the `index_seasons (gap fill)` job completes.
