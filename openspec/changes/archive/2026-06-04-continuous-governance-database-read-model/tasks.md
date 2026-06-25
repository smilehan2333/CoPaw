## 1. Database Read Model

- [x] 1.1 Define database tables and migrations for governance records, execution impact, file-governance state, cleanup audit, and reconcile health rows.
- [x] 1.2 Add repository/service APIs keyed by source id, logical managed user id, and workspace or agent id.
- [x] 1.3 Add idempotent upsert semantics for governance records, file-state rows, cleanup audit rows, and historical imports.
- [x] 1.4 Add unit tests for repository identity keys, idempotency, outcome updates, and pending/reconcile status transitions.

## 2. Dual-Write Execution Boundaries

- [x] 2.1 Dual-write dream optimization completion to workspace files and database-backed Continuous Governance Record rows.
- [x] 2.2 Dual-write Optimization Rollback by updating the original database record to Rollback Outcome while preserving existing workspace rollback behavior.
- [x] 2.3 Dual-write archive, Archive Restore, protection changes, Archive Purge, and audited maintenance to File Governance State and Cleanup Audit rows.
- [x] 2.4 Implement pending, failed, or reconcile-needed handling when workspace mutation succeeds but database read-model writes fail.
- [x] 2.5 Add tests for successful dual-write, database-write failure, retry/reconcile resolution, and non-success reporting before database persistence.

## 3. Historical Backfill and Reconciliation

- [x] 3.1 Add an explicit administrator or deployment-triggered backfill task for dream logs, archive indexes, protected paths, and audit logs.
- [x] 3.2 Ensure repeated backfill runs do not duplicate records, file-state rows, or cleanup audit rows.
- [x] 3.3 Add a reconciliation path for pending or reconcile-needed rows without request-time workspace scanning from analysis APIs.
- [x] 3.4 Add migration/backfill tests covering repeated imports and partial existing database state.

## 4. Management Reporting APIs

- [x] 4.1 Refactor Continuous Governance Analysis report APIs to read governance metrics, trends, distributions, and user rows from the database read model.
- [x] 4.2 Refactor File Governance State Report APIs to read archive, protected-file, purge, and cleanup-audit data from the database read model.
- [x] 4.3 Apply user-dimension filters to both governance outcome reporting and File Governance State Report.
- [x] 4.4 Apply record-dimension filters only to Continuous Governance Record metrics, not to File Governance State Report.
- [x] 4.5 Expose pending, failed, or reconcile-needed health separately from core metrics.
- [x] 4.6 Add API tests proving analysis requests do not scan workspace files, repair records, or backfill missing state.

## 5. Console Integration

- [x] 5.1 Update Continuous Governance Analysis API calls and types for database-backed reporting responses.
- [x] 5.2 Display pending, failed, or reconcile-needed health state separately from core metrics.
- [x] 5.3 Ensure user filters narrow File Governance State Report while record filters do not.
- [x] 5.4 Add or update Console tests for metric rendering, file-state filtering, and health-state display.

## 6. Verification

- [x] 6.1 Run targeted backend unit and API tests for continuous governance reporting, dual-write, and migration/backfill.
- [x] 6.2 Run targeted Console tests for `console/src/pages/Analytics/ContinuousGovernance/`.
- [x] 6.3 Run `openspec.cmd validate continuous-governance-database-read-model --strict`.
- [x] 6.4 Review `CONTEXT.md`, `docs/adr/0003-continuous-governance-reporting-uses-database-read-model.md`, and OpenSpec artifacts for terminology alignment before implementation.
