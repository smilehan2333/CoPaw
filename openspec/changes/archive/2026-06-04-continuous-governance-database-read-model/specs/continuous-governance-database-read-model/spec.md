## ADDED Requirements

### Requirement: Database-backed management reporting
The system SHALL use a database-backed read model as the authoritative source for management-side Continuous Governance Analysis, including governance records, coverage metrics, governed-user counts, success and outcome metrics, trends, distributions, file-governance state reports, cleanup audits, archive state, protected files, purge metrics, and reconcile health.

#### Scenario: Analysis reads database model only
- **WHEN** a Continuous Governance Administrator opens the Continuous Governance Analysis page
- **THEN** the system reads management-side metrics and lists from the database read model
- **AND** the request does not scan workspace files, repair records, or backfill missing state as a side effect

#### Scenario: Workspace files are not reporting fallback
- **WHEN** a workspace file contains a governance record that has not been migrated into the database read model
- **THEN** management-side analysis does not include that record in core metrics
- **AND** the system exposes migration or reconcile health rather than silently reading the workspace file

### Requirement: Source-scoped reporting identity
The system SHALL identify database read-model rows by source id, logical managed user id, and workspace or agent id, rather than by runtime tenant directory name.

#### Scenario: Target workspace identity is domain-based
- **WHEN** the system stores a governance record or file-governance state row
- **THEN** the row includes source id, logical managed user id, and workspace or agent id
- **AND** runtime tenant directory names are not used as the reporting primary key

### Requirement: Dual-write compatibility
The system SHALL dual-write workspace files and the database read model during the compatibility period for governance execution and file-governance action boundaries.

#### Scenario: Dream optimization completion writes both stores
- **WHEN** dream optimization completes
- **THEN** the system writes the Continuous Governance Record and execution impact to the database read model
- **AND** the system preserves the existing workspace-file writes required by current workspace operations

#### Scenario: Rollback updates original record
- **WHEN** Optimization Rollback is performed
- **THEN** the system updates the original database-backed Continuous Governance Record to a Rollback Outcome
- **AND** the system does not create a separate Continuous Governance Record for the rollback

#### Scenario: File governance action updates file state
- **WHEN** archive, restore, protection change, purge, or audited administrator maintenance occurs
- **THEN** the system updates the corresponding database-backed File Governance State or Cleanup Audit rows
- **AND** the system preserves workspace-file state needed for immediate current workspace actions

### Requirement: Management-visible success requires database persistence
The system SHALL report a management-visible governance or file-governance action as successful only after the database read model reflects that action.

#### Scenario: Workspace write succeeds and database write fails
- **WHEN** a dual-write action changes workspace files but fails to update the database read model
- **THEN** the action is not reported as management-side success
- **AND** the system records or exposes the action as pending, failed, or reconcile-needed

#### Scenario: Retry resolves pending action
- **WHEN** retry or reconciliation successfully writes the missing database read-model state
- **THEN** the action becomes eligible for management-side success reporting and core metrics

### Requirement: Pending and reconcile health are separate from core metrics
The system SHALL exclude pending, failed, and reconcile-needed rows from core management-side analysis metrics and expose them separately as health state or exception lists.

#### Scenario: Pending row is excluded from core metrics
- **WHEN** a read-model row is pending or reconcile-needed
- **THEN** coverage, governed-user counts, success metrics, archive totals, protected-file counts, and purge totals do not aggregate that row
- **AND** the row is visible through administrator health or exception reporting

### Requirement: Historical workspace data backfill
The system SHALL provide an explicit idempotent migration or backfill task for existing workspace files, including dream logs, archive indexes, protected-path state, and audit logs.

#### Scenario: Administrator runs backfill
- **WHEN** an administrator or deployment process runs the historical backfill task
- **THEN** the system imports eligible workspace-file data into the database read model
- **AND** repeated runs do not create duplicate governance records, file-state rows, or cleanup audit rows

#### Scenario: Analysis request does not backfill
- **WHEN** a management-side analysis request encounters missing database rows
- **THEN** the system does not import workspace files during that request
- **AND** the system reports migration or reconcile health if applicable

### Requirement: Filter semantics for analysis and file-state reporting
The system SHALL apply user-dimension filters to the Managed Source User Set for both governance outcome reporting and File Governance State Report, while record-dimension filters apply only to Continuous Governance Record metrics.

#### Scenario: User filters narrow file-state report
- **WHEN** a Continuous Governance Administrator filters by a user dimension such as managed user, user keyword, or business grouping
- **THEN** the File Governance State Report includes only Target Workspaces for the narrowed Managed Source User Set

#### Scenario: Record filters do not narrow file-state report
- **WHEN** a Continuous Governance Administrator filters Continuous Governance Records by date, trigger, or outcome
- **THEN** coverage, governed-user counts, success metrics, trends, and distributions use those record filters
- **AND** the File Governance State Report is not narrowed by those record filters
