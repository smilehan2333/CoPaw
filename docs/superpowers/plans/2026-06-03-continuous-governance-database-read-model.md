# Continuous Governance Database Read Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move management-side Continuous Governance Analysis and File Governance State reporting to a database-backed read model while keeping current workspace file operations compatible.

**Architecture:** Add a focused `src/swe/app/continuous_governance/` module with Pydantic/domain models, SQL store, and service methods. Keep `dream_logs.py` as the operational router, but route management report reads and dual-write hooks through the new service. Use explicit SQL DDL under `scripts/sql/` and an explicit backfill script for old workspace files.

**Tech Stack:** FastAPI router code, Pydantic models, existing async `DatabaseConnection`, MySQL `INSERT ... ON DUPLICATE KEY UPDATE`, pytest with `MagicMock`/`AsyncMock`.

---

## File Structure

- Create `src/swe/app/continuous_governance/__init__.py`: module exports and service singleton helpers.
- Create `src/swe/app/continuous_governance/models.py`: database read-model records, filters, report rows, and health states.
- Create `src/swe/app/continuous_governance/store.py`: strict DB availability checks, idempotent upserts, report queries, archive/protected/audit queries, and health writes.
- Create `src/swe/app/continuous_governance/service.py`: request-facing orchestration, tenant/user filtering, report aggregation, dual-write helper methods, and backfill helpers.
- Create `scripts/sql/continuous_governance_read_model.sql`: DDL for governance records, archive items, protected files, cleanup audits, and reconcile health.
- Create `scripts/backfill_continuous_governance_read_model.py`: explicit idempotent workspace-file backfill command.
- Modify `src/swe/app/_app.py`: initialize the continuous governance service when DB is connected.
- Modify `src/swe/app/routers/dream_logs.py`: use service for management read endpoints and call dual-write helpers after workspace mutations.
- Create `tests/unit/app/continuous_governance/test_store.py`: store SQL/idempotency/health tests.
- Create `tests/unit/app/continuous_governance/test_service.py`: aggregation/filter/backfill tests.
- Modify `tests/unit/routers/test_dream_logs_report.py`: API tests proving report endpoints read service data and do not scan workspace files.
- Add targeted archive report/router tests if existing coverage does not exercise DB-backed file-state reporting.

## Task 1: Store, Models, And DDL

**Files:**
- Create: `src/swe/app/continuous_governance/__init__.py`
- Create: `src/swe/app/continuous_governance/models.py`
- Create: `src/swe/app/continuous_governance/store.py`
- Create: `scripts/sql/continuous_governance_read_model.sql`
- Test: `tests/unit/app/continuous_governance/test_store.py`

- [ ] **Step 1: Write store tests first**

Cover these behaviors:
- unavailable store raises a continuous-governance-specific unavailable error
- governance record upsert uses `source_id + target_user_id + target_agent_id + record_id`
- rollback updates the original governance record instead of inserting a new record
- archive item upsert is idempotent by source/user/agent/item id
- protected file upsert/delete uses source/user/agent/path
- cleanup audit upsert is idempotent by event id
- reconcile health can be inserted, listed by source, and resolved

Run: `venv\Scripts\python.exe -m pytest tests/unit/app/continuous_governance/test_store.py -v`
Expected: FAIL before implementation because the module does not exist.

- [ ] **Step 2: Implement models and store**

Use the existing `SourceSystemConfigStore` pattern:
- `is_available`
- `_require_db`
- `_call_db`
- strict exception wrapping
- JSON encode/decode for raw payloads and list fields
- parameterized SQL only
- `INSERT ... ON DUPLICATE KEY UPDATE` for idempotent writes

- [ ] **Step 3: Add DDL**

Define these tables with source-scoped unique keys:
- `swe_continuous_governance_records`
- `swe_file_governance_archive_items`
- `swe_file_governance_protected_files`
- `swe_file_governance_cleanup_audits`
- `swe_continuous_governance_reconcile_health`

Run: `venv\Scripts\python.exe -m pytest tests/unit/app/continuous_governance/test_store.py -v`
Expected: PASS.

## Task 2: Service And Report Aggregation

**Files:**
- Create: `src/swe/app/continuous_governance/service.py`
- Test: `tests/unit/app/continuous_governance/test_service.py`

- [ ] **Step 1: Write service tests first**

Cover these behaviors:
- source/user filters narrow covered users
- governed users include any matching governance record, including failed and rollback records
- success rate denominator includes rollback records, while only `success` counts as success
- record filters affect only record metrics
- file-governance report user filters narrow file-state rows
- record filters do not narrow file-state rows
- pending/failed/reconcile-needed health is returned separately from core committed metrics

Run: `venv\Scripts\python.exe -m pytest tests/unit/app/continuous_governance/test_service.py -v`
Expected: FAIL before implementation.

- [ ] **Step 2: Implement service aggregation**

Keep aggregation semantics aligned with `CONTEXT.md` and ADR 0003:
- database rows are authoritative for management reports
- runtime tenant directory names are not reporting primary keys
- report identity is `source_id + target_user_id + target_agent_id`
- file state rows are separate from governance records

Run: `venv\Scripts\python.exe -m pytest tests/unit/app/continuous_governance/test_service.py -v`
Expected: PASS.

## Task 3: Application Wiring And Router Read Switch

**Files:**
- Modify: `src/swe/app/_app.py`
- Modify: `src/swe/app/routers/dream_logs.py`
- Modify: `tests/unit/routers/test_dream_logs_report.py`

- [ ] **Step 1: Write router tests first**

Change report tests to attach a fake continuous governance service on `request.app.state`. Assert:
- `/dream-logs/report` returns DB-backed data
- `/dream-logs/report/users/{user_id}/records` returns DB-backed records
- damaged or present `dream_logs.json` files are not read by report endpoints
- DB unavailable returns a management-report error instead of silently scanning workspace files

Run: `venv\Scripts\python.exe -m pytest tests/unit/routers/test_dream_logs_report.py -v`
Expected: FAIL before router switch.

- [ ] **Step 2: Wire service initialization**

When `_app.py` creates a connected DB, initialize `ContinuousGovernanceService(ContinuousGovernanceStore(db_connection))` and store it on `app.state.continuous_governance_service`.

- [ ] **Step 3: Switch report endpoints**

In `dream_logs.py`, add small helpers to fetch the continuous governance service. Update management read endpoints to call the service rather than `_collect_tenant_report_records`, `_source_archive_workspaces`, `_collect_admin_audits`, or direct archive/protected file scanning.

Run: `venv\Scripts\python.exe -m pytest tests/unit/routers/test_dream_logs_report.py -v`
Expected: PASS.

## Task 4: Dual-Write Hooks And Backfill

**Files:**
- Modify: `src/swe/app/routers/dream_logs.py`
- Create: `scripts/backfill_continuous_governance_read_model.py`
- Test: `tests/unit/app/continuous_governance/test_service.py`
- Test: existing archive/router tests or new focused router tests

- [ ] **Step 1: Write dual-write tests**

Cover successful DB writes and DB-write failures after workspace mutation:
- dream optimization completion persists a governance record
- rollback updates the original record status to rollback
- archive/protect/restore/purge/admin audit operations update the file state read model
- workspace success plus DB failure writes pending/reconcile health and does not count as management success

- [ ] **Step 2: Add dual-write helpers**

Keep workspace-file mutation order unchanged for current operational behavior, then persist the DB read model through service helpers. On DB failure, record reconcile health with entity type/id and error context.

- [ ] **Step 3: Add explicit backfill script**

Backfill reads old `dream_logs.json`, archive indexes, protected paths, and admin audit files, then upserts rows through the store. Repeated backfill must not duplicate records.

Run:
- `venv\Scripts\python.exe -m pytest tests/unit/app/continuous_governance/test_service.py -v`
- `venv\Scripts\python.exe -m pytest tests/unit/routers/test_dream_logs_report.py -v`

Expected: PASS.

## Task 5: Review, Verification, And OpenSpec Closeout

**Files:**
- Modify: `openspec/changes/continuous-governance-database-read-model/tasks.md`
- Review: `docs/adr/0003-continuous-governance-reporting-uses-database-read-model.md`

- [ ] **Step 1: Run focused backend tests**

Run:
- `venv\Scripts\python.exe -m pytest tests/unit/app/continuous_governance tests/unit/routers/test_dream_logs_report.py -v`

- [ ] **Step 2: Run OpenSpec validation**

Run:
- `openspec.cmd validate continuous-governance-database-read-model --strict`

- [ ] **Step 3: Run code review**

Use at least one independent reviewer subagent or a separate review pass. Review for:
- spec compliance
- no accidental workspace scanning in management report reads
- DB identity key correctness
- missing health/pending paths
- test coverage gaps

- [ ] **Step 4: Update task status**

Only mark OpenSpec tasks complete for implemented and verified behavior.
