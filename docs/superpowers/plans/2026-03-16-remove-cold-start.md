# Remove Scheduler Cold-Start Queue Flooding

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the `_cold_start` flag from the scheduler so that jobs with a fresh `SyncStatus` are not re-queued on server restart or scheduler re-enable.

**Architecture:** Single file change — delete `_cold_start` from `Scheduler.__init__`, `enable()`, and `_refresh_queue()`, then simplify the condition in `_maybe_schedule()` from `if last_sync is None or self._cold_start:` to `if last_sync is None:`. Fresh installs still bootstrap correctly because all policies have `last_sync is None`.

**Tech Stack:** Python, SQLAlchemy, pytest, asyncio

---

## File Map

| File | Change |
|---|---|
| `backend/app/services/scheduler.py` | Remove `_cold_start` from 3 locations; simplify condition in `_maybe_schedule()` |
| `backend/tests/test_scheduler.py` | Add test verifying fresh SyncStatus rows are not re-queued after restart |

---

## Chunk 1: Implementation

### Task 1: Remove `_cold_start` and write regression test

**Files:**
- Modify: `backend/app/services/scheduler.py` (lines 443, 615, 852, 922)
- Modify: `backend/tests/test_scheduler.py`

**Context:**

`_cold_start` appears in exactly 4 locations in `scheduler.py`:
- Line 443 (`__init__`): `self._cold_start = True  # run all jobs immediately on first enable`
- Line 615 (`enable()`): `self._cold_start = True`
- Line 852 (`_refresh_queue()`): `self._cold_start = False`
- Line 922 (`_maybe_schedule()`): `if last_sync is None or self._cold_start:`

The comment on line 923–924 reads:
```
# Never synced or cold-start (first run after enable) –
# run soon, staggered by priority to avoid thundering herd.
```
After the fix this becomes just "Never synced".

The test needs a `Scheduler` instance and a seeded in-memory DB with `SyncStatus` rows already fresh (last_sync = now) for every policy × season combination. After one tick, the queue must be empty.

Look at the existing test fixtures in `test_scheduler.py` to understand how `scheduler` fixture and DB are constructed — follow the same pattern.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_scheduler.py`, add a new test class or method. Find the existing `@pytest.fixture` for `scheduler` and `engine`/`db` in the file to understand how to wire up a session. Then add:

```python
@pytest.mark.asyncio
async def test_fresh_sync_status_not_requeued_on_restart(scheduler, db_engine):
    """Jobs with a fresh SyncStatus must not be queued after a restart."""
    from sqlalchemy.orm import Session
    from app.models.db_models import SyncStatus
    from app.services.scheduler import POLICIES, _utcnow

    # Seed a fresh SyncStatus (just completed) for every policy × season=1
    with Session(db_engine) as s:
        for policy in POLICIES:
            s.add(SyncStatus(
                entity_type=policy["entity_type"],
                entity_id=f"season:1" if policy.get("scope") == "season" else policy["entity_type"],
                sync_status="completed",
                last_sync=_utcnow(),
                records_synced=0,
            ))
        s.commit()

    # Run one full tick — simulates a restart with fresh data
    await scheduler._refresh_queue()

    # No jobs should be queued: all SyncStatus rows are within max_age
    assert len(scheduler._queue) == 0, (
        f"Expected empty queue after restart with fresh SyncStatus, "
        f"got {len(scheduler._queue)} jobs: {[j.policy_name for j in scheduler._queue]}"
    )
```

Note: `db_engine` fixture may need to be added if it doesn't already exist. Check the existing fixtures — the scheduler fixture may already inject a DB. If `_utcnow` is not exported from scheduler, use `datetime.now(timezone.utc).replace(tzinfo=None)` instead.

- [ ] **Step 2: Run to verify the test fails**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest tests/test_scheduler.py::test_fresh_sync_status_not_requeued_on_restart -v
```

Expected: **FAIL** — the queue will have jobs because `_cold_start=True` causes them to be enqueued.

- [ ] **Step 3: Make the four changes to `scheduler.py`**

**Change 1** — remove `_cold_start` from `__init__` (line 443):
```python
# DELETE this line:
self._cold_start = True  # run all jobs immediately on first enable
```

**Change 2** — remove from `enable()` (line 615):
```python
# DELETE this line:
self._cold_start = True
```

**Change 3** — remove from `_refresh_queue()` (line 852):
```python
# DELETE this line:
self._cold_start = False
```
Also delete the comment above it on line 851: `# Cold start complete – subsequent ticks use normal max_age scheduling`

**Change 4** — simplify condition in `_maybe_schedule()` (line 922):
```python
# BEFORE:
        if last_sync is None or self._cold_start:
            # Never synced or cold-start (first run after enable) –
            # run soon, staggered by priority to avoid thundering herd.
            run_at = now + timedelta(seconds=policy["priority"])

# AFTER:
        if last_sync is None:
            # Never synced – run soon, staggered by priority to avoid thundering herd.
            run_at = now + timedelta(seconds=policy["priority"])
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest tests/test_scheduler.py::test_fresh_sync_status_not_requeued_on_restart -v
```

Expected: **PASS**

- [ ] **Step 5: Run the full scheduler test suite**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest tests/test_scheduler.py -v
```

Expected: All tests pass. If any fail, read the error — most likely a test was asserting `_cold_start` exists; remove or update that assertion.

- [ ] **Step 6: Run the full test suite**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest --tb=short -q
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats && git add backend/app/services/scheduler.py backend/tests/test_scheduler.py && git commit -m "fix(scheduler): remove cold_start flag — only queue jobs with stale or missing SyncStatus"
```
