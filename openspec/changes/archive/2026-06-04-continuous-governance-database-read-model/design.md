## Context

Continuous Governance currently has two management surfaces: a read-only source-scope analysis view and an operational workbench for file-governance actions. The clarified domain model separates Continuous Governance Records from File Governance State, distinguishes user-dimension filters from record-dimension filters, and requires management-side statistics to use source-scoped identities rather than runtime tenant directory names.

The current implementation reads dream logs, archive indexes, protected paths, and audit jsonl files from workspace storage. That works for current workspace actions, but it makes source-scope analytics dependent on request-time file scanning and on where the files are stored in a multi-instance deployment.

## Goals / Non-Goals

**Goals:**

- Make the database read model authoritative for management-side Continuous Governance Analysis.
- Preserve workspace files during the compatibility period for current workspace operations such as rollback, diff, backup preview, archive restore, and orphan-file handling.
- Write the database read model at governance execution and file-governance action boundaries.
- Provide explicit historical backfill from existing workspace files.
- Expose pending, failed, or reconcile-needed read-model rows separately from core analysis metrics.

**Non-Goals:**

- Remove workspace files from current workspace operational flows in this change.
- Define a current net governance benefit metric.
- Expand Continuous Governance Record sources beyond dream memory optimization and related file hygiene.
- Implement request-time repair, workspace scanning fallback, or implicit backfill from analysis queries.

## Decisions

### Database Read Model Is Authoritative for Management Reporting

Management-side APIs read Continuous Governance Records, execution impact, File Governance State, Cleanup Audit, and health rows from database tables. Request handlers for analysis do not scan workspace files, repair missing state, or trigger backfill.

Alternative considered: keep scanning workspace files at query time. This was rejected because source-scope reporting needs stable cross-user, cross-workspace, and cross-instance behavior.

### Execution Paths Dual-Write During Compatibility

Dream optimization, rollback, archive, restore, protection changes, purge, and audited administrator maintenance update both existing workspace files and the database read model. Workspace files continue to support immediate current workspace operations, while management-side statistics treat the database rows as authoritative.

Alternative considered: cut over to database-only writes immediately. This was rejected because existing rollback, diff, backup preview, and archive workflows still depend on workspace files.

### Database Write Defines Management-Side Success

A management-visible governance or file-governance action is successful only after the database read model reflects the action. If workspace file changes succeed but the database write fails, the action remains pending, failed, or reconcile-needed for management reporting until retry or reconciliation resolves it.

Alternative considered: report success after workspace file mutation and let analysis catch up later. This was rejected because it would create visible success with missing management statistics.

### Pending and Reconcile Health Stay Out of Core Metrics

Core analysis metrics aggregate only committed successful read-model rows. Pending, failed, and reconcile-needed rows are exposed as health state or exception lists for administrators.

Alternative considered: include pending rows in metrics with status labels. This was rejected because partially persisted actions would distort coverage, success rate, file-state counts, and purge totals.

### Reporting Identity Uses Source-Scoped Domain Keys

Read-model rows use source id, logical managed user id, and workspace or agent id. Runtime tenant directory names remain technical file-location mappings and are not reporting primary keys.

Alternative considered: use runtime tenant directories as keys because current file layout is directory-based. This was rejected because management semantics are defined by Managed Source User Set and Target Workspace, not by runtime storage paths.

### Historical Data Uses Explicit Idempotent Backfill

Existing dream logs, archive indexes, protected paths, and audit files are imported by an explicit idempotent task triggered by administrators or deployment. Analysis queries never perform implicit backfill.

Alternative considered: lazy backfill when analysis pages are requested. This was rejected because analytics requests should be side-effect free and predictable.

## Risks / Trade-offs

- Database read-model writes can fail after workspace file mutation -> represent the action as pending, failed, or reconcile-needed and provide retry/reconcile tooling.
- Dual-write can drift during the compatibility period -> add idempotent keys and reconciliation tests for all write boundaries.
- Backfill may import duplicate historical records -> use stable source/user/workspace/record/action keys and idempotent upserts.
- Management-side data may be incomplete before migration finishes -> expose migration/reconcile health and avoid falling back to request-time scans.
- Current workspace operations still depend on files -> keep file writes until a later database-first operational design removes those dependencies.

## Migration Plan

1. Add database schema and repository/service layer for governance records, file-governance state, cleanup audit, and health rows.
2. Add dual-write at governance execution and file-governance action boundaries.
3. Add idempotent historical backfill from workspace files.
4. Switch management-side analysis APIs to read the database model only.
5. Add health endpoints or fields for pending, failed, and reconcile-needed rows.
6. Keep workspace-file reads for current workspace operational actions until a later change replaces those flows.

## Open Questions

- Exact table names and indexes should be finalized during implementation after reviewing existing database migration conventions.
- The retry/reconcile scheduler shape should be chosen during implementation based on existing background worker patterns.
