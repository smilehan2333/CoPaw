## Why

Continuous Governance Analysis currently depends on workspace files and request-time aggregation, which is fragile for source-scope management reporting across users, workspaces, and multiple instances. The clarified domain model requires management-side statistics, file-governance state, cleanup audit, and reconciliation health to be read from an authoritative database read model.

## What Changes

- Add a database-backed reporting model for Continuous Governance records, execution impact, file-governance state, cleanup audit, and pending/reconcile health.
- Dual-write workspace files and the database read model during the compatibility period; workspace files remain for current workspace execution and immediate file operations.
- Move management-side Continuous Governance Analysis APIs to read only from the database model, with no request-time workspace scanning, repair, or backfill side effects.
- Add an explicit idempotent migration/backfill task for existing workspace files such as dream logs, archive indexes, protected paths, and audit logs.
- Scope reporting identities by source id, logical managed user id, and workspace or agent id, not runtime tenant directory names.
- Treat management-visible actions as successful only when the database read model reflects the action; expose pending, failed, and reconcile-needed rows separately from core metrics.

## Capabilities

### New Capabilities

- `continuous-governance-database-read-model`: Store and query Continuous Governance management reporting from a database-backed read model with dual-write, migration, and reconciliation health.

### Modified Capabilities

- None.

## Impact

- Affected backend: `src/swe/app/routers/dream_logs.py`, dream optimization completion paths, rollback paths, archive/protect/purge file-governance paths, database migration scripts, and any new reporting repositories/services.
- Affected Console: `console/src/pages/Analytics/ContinuousGovernance/` API usage and health-state display for pending or reconcile-needed rows.
- Affected operations: explicit historical backfill command or task, deployment ordering for database migrations, and reconciliation monitoring.
- Tests: repository/service unit tests, API tests for database-backed reporting and filters, migration/backfill tests, and dual-write failure/retry/reconcile tests.
