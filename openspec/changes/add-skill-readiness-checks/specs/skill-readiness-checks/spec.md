## ADDED Requirements

### Requirement: Skill readiness APIs SHALL be manager-only and source-scoped by header
The system SHALL expose skill readiness APIs only to manager or admin callers and SHALL resolve `source_id` from the request context/header rather than from query parameters.

#### Scenario: Manager requests readiness overview
- **WHEN** a request to a skill readiness API includes `X-User-Role: manager` or `X-User-Role: admin` and a valid source context
- **THEN** the system SHALL process the request using the header/context source identity
- **AND** it SHALL NOT require or accept a `source_id` query override

#### Scenario: Unauthorized caller requests readiness data
- **WHEN** a request to a skill readiness API omits manager/admin role authorization
- **THEN** the system SHALL reject the request with HTTP 403
- **AND** it SHALL NOT read owner, cron, auth, model, MCP, or readiness result data

#### Scenario: Source context is missing
- **WHEN** a request to a skill readiness API has no resolved source identity
- **THEN** the system SHALL reject the request with HTTP 400
- **AND** it SHALL NOT start or read a readiness run

### Requirement: Skill readiness SHALL use a validated skill id with skill-name fallback
The Console and backend SHALL use `skill_id` as the readiness key, while allowing the Console to fall back to `skill_name` when the market skill object does not yet provide `skill_id`.

#### Scenario: Market skill has a skill id
- **WHEN** a manager opens the skill readiness modal for a market skill that includes `skill_id`
- **THEN** the Console SHALL call readiness APIs with that `skill_id`
- **AND** the modal SHALL show that the current skill id came from the market skill id

#### Scenario: Market skill lacks a skill id
- **WHEN** a manager opens the skill readiness modal for a market skill that lacks `skill_id`
- **THEN** the Console SHALL call readiness APIs with the skill's `skill_name`
- **AND** the modal SHALL show that the current skill id came from skill-name fallback

#### Scenario: Invalid skill id is submitted
- **WHEN** a readiness API receives a skill id containing unsupported characters such as slash or whitespace
- **THEN** the system SHALL reject the request with HTTP 400
- **AND** it SHALL NOT access readiness configuration or run state

### Requirement: Backend SHALL aggregate the current market skill owner set
The SWE backend SHALL resolve the current owner set for a market skill within the active source by calling market HTTP APIs for source users and matching skills by id or fallback name.

#### Scenario: Owner lookup succeeds
- **WHEN** the readiness overview or run startup resolves owners for a skill id
- **THEN** the backend SHALL enumerate current source users
- **AND** it SHALL call market skill APIs for each user
- **AND** it SHALL include each user whose market skill entry matches by `skill_id` or, when absent, by `skill_name`

#### Scenario: User appears in multiple market skill lists
- **WHEN** one user is found through both "mine" and "received" market skill APIs
- **THEN** the owner set SHALL include that `user_id` only once
- **AND** user display fields SHALL prefer the source user list values when available

#### Scenario: Some owner lookups fail
- **WHEN** only some user or tenant market skill lookups fail
- **THEN** the backend SHALL continue with successfully resolved owners
- **AND** a started run SHALL record owner lookup failure counts and summaries
- **AND** the final run status SHALL be `partial` if user results are available

#### Scenario: All owner lookups fail
- **WHEN** owner lookup cannot produce any usable user result because all lookup work failed
- **THEN** a started run SHALL finish as `failed`
- **AND** it SHALL expose a run-level failure summary

### Requirement: Readiness configuration SHALL be keyed globally by skill id
The system SHALL store readiness configuration in SWE backend storage keyed by `skill_id`, independent of `source_id`, and SHALL require at least one enabled check before a run can start.

#### Scenario: Config exists with enabled checks
- **WHEN** overview is requested for a skill id that has readiness configuration with at least one enabled check
- **THEN** the response SHALL report that configuration was found
- **AND** it SHALL report the skill as startable
- **AND** it SHALL include a readable configuration summary with check display names

#### Scenario: Config is missing
- **WHEN** overview is requested for a skill id without readiness configuration
- **THEN** the response SHALL report that no self-check configuration was found
- **AND** starting a run for that skill id SHALL be rejected

#### Scenario: Config has no enabled checks
- **WHEN** overview is requested for a skill id whose configuration has no enabled checks
- **THEN** the response SHALL report that no checks are enabled
- **AND** starting a run for that skill id SHALL be rejected

#### Scenario: Config changes while a run is executing
- **WHEN** a readiness run has already started
- **THEN** the run SHALL continue using the `config_snapshot` captured at startup
- **AND** later edits to the base configuration SHALL NOT affect users remaining in that run

### Requirement: Readiness runs SHALL execute asynchronously with persisted progress
The system SHALL create asynchronous readiness runs for one `source_id + skill_id`, persist progress incrementally, and avoid duplicate running runs for the same pair.

#### Scenario: Manager starts a new run
- **WHEN** a manager starts a readiness run for a startable skill id with no existing running run for the same source and skill
- **THEN** the system SHALL create a run with status `running`
- **AND** it SHALL process the full resolved owner set without a hard 200-user cap
- **AND** it SHALL return the new run id and initial progress

#### Scenario: Manager starts while a run is active
- **WHEN** a manager starts a readiness run for a source and skill that already has a `running` run
- **THEN** the system SHALL return the existing run id and progress
- **AND** it SHALL NOT create a second concurrent run for the same source and skill

#### Scenario: User result completes
- **WHEN** the backend finishes checking one user in a run
- **THEN** it SHALL persist that user's aggregate result
- **AND** it SHALL persist every check result for that user
- **AND** it SHALL update `completed_users` and `failed_users` on the run

#### Scenario: Run completes normally
- **WHEN** all resolved users have completed readiness checks and no run-level partial failure remains
- **THEN** the run status SHALL become `completed`
- **AND** `completed_users` SHALL equal `total_users`

#### Scenario: Run has partial output
- **WHEN** a run produces some user results but non-fatal lookup or execution failures prevent a fully complete run
- **THEN** the run status SHALL become `partial`
- **AND** the run SHALL expose a failure summary

#### Scenario: Run startup fails
- **WHEN** configuration parsing, owner lookup, or storage work fails before any user result is available
- **THEN** the run status SHALL become `failed`
- **AND** the run SHALL expose a failure summary

### Requirement: Readiness execution SHALL bound concurrency and per-user runtime
The readiness worker SHALL process users concurrently with a bounded concurrency and SHALL enforce a user-level timeout.

#### Scenario: Large owner set is checked
- **WHEN** a skill has more than 200 current owners
- **THEN** the backend SHALL still schedule all owners for checking
- **AND** it SHALL run at most 10 user checks concurrently by default

#### Scenario: One user exceeds the user timeout
- **WHEN** one user's readiness checks exceed the default 60-second user timeout
- **THEN** unfinished checks for that user SHALL be recorded as `fail`
- **AND** completed checks for that user SHALL keep their recorded statuses
- **AND** the worker SHALL continue checking other users

### Requirement: Check results SHALL use generic pass fail skip statuses
Each readiness check result SHALL use `pass`, `fail`, or `skip`. Technical failures SHALL be represented as `fail` with explanatory message and details rather than a separate error status.

#### Scenario: A check passes
- **WHEN** a configured readiness condition is satisfied for a user
- **THEN** that check result SHALL have status `pass`
- **AND** it SHALL include a display name, message, and duration

#### Scenario: A check fails due to unmet condition or technical failure
- **WHEN** a configured readiness condition is unmet or its technical inspection fails
- **THEN** that check result SHALL have status `fail`
- **AND** it SHALL include a message and details explaining the failure

#### Scenario: A check is not applicable
- **WHEN** a configured readiness check has no applicable target for a user
- **THEN** that check result SHALL have status `skip`
- **AND** the user SHALL still be normal if all other checks are `pass` or `skip`

#### Scenario: User aggregate status is calculated
- **WHEN** any check result for a user has status `fail`
- **THEN** the user's readiness result SHALL be abnormal
- **WHEN** all check results for a user are `pass` or `skip`
- **THEN** the user's readiness result SHALL be normal

### Requirement: Built-in checks SHALL inspect profile, cron, auth, model, and MCP readiness
The system SHALL provide built-in checks named `profile_identity_block`, `bound_cron_job`, `cron_auth_valid`, `cron_model_connection`, and `mcp_tools_available`.

#### Scenario: Profile identity block is checked
- **WHEN** `profile_identity_block` runs for a user
- **THEN** it SHALL pass only when `PROFILE.md` contains `### 用户身份信息` and non-empty `分行号`, `网点机构编号`, `岗位编号`, and `客户经理ID`
- **AND** missing file, missing heading, or missing fields SHALL produce `fail`

#### Scenario: Bound cron job is checked
- **WHEN** `bound_cron_job` runs for a user
- **THEN** it SHALL pass when at least one enabled and non-deleted scheduled job is bound to the current skill id
- **AND** paused jobs SHALL count as bindings
- **AND** disabled jobs SHALL NOT count as executable bindings

#### Scenario: Cron auth is checked
- **WHEN** `cron_auth_valid` runs for a user
- **THEN** it SHALL pass only when source-scoped `cron_auth.json` exists, is readable, contains `user_info_expires_at`, and that time is later than now
- **AND** every other outcome SHALL produce `fail`

#### Scenario: Cron model connection is checked
- **WHEN** `cron_model_connection` runs for a user with enabled, non-deleted, model-running bound jobs
- **THEN** it SHALL check the actual models those jobs would use, including tenant default model when no explicit model slot is configured
- **AND** it SHALL de-duplicate model tests by provider and model
- **AND** any failed model connection SHALL produce `fail`

#### Scenario: Cron model check has no model-running bound job
- **WHEN** `cron_model_connection` runs for a user with no applicable model-running bound jobs
- **THEN** it SHALL produce `skip`

#### Scenario: MCP tools are checked
- **WHEN** `mcp_tools_available` runs with configured server and tool requirements
- **THEN** it SHALL pass only when every required MCP server exists, is enabled, can list tools, and includes every required tool
- **AND** missing server, disabled server, connection failure, list-tools failure, or missing tool SHALL produce `fail`

#### Scenario: MCP tools config is empty
- **WHEN** `mcp_tools_available` runs with no configured servers
- **THEN** it SHALL produce `skip`

### Requirement: Results API SHALL return paginated users with full check details and check filters
The system SHALL expose paginated readiness results with abnormal-first ordering by default, aggregate status filters, and check-name filters backed by generic check result rows.

#### Scenario: Results are requested without check filter
- **WHEN** a manager requests readiness results for a run
- **THEN** the response SHALL include a page of user results
- **AND** abnormal users SHALL sort before normal users by default
- **AND** each returned user SHALL include all check results for that user

#### Scenario: Results are filtered by user status
- **WHEN** a manager requests results with `status=abnormal`, `status=normal`, or `status=all`
- **THEN** the backend SHALL filter the user result set accordingly
- **AND** it SHALL return pagination metadata for the filtered set

#### Scenario: Results are filtered by check failure
- **WHEN** a manager requests results with `check_name=<name>` and `check_status=fail`
- **THEN** the backend SHALL return users whose named check failed
- **AND** each returned user SHALL still include all check results, not only the matching check

#### Scenario: Check summaries are returned
- **WHEN** overview returns the latest run summary
- **THEN** the response SHALL include one summary per check name with `total`, `pass`, `fail`, and `skip` counts
- **AND** each summary SHALL include a display name

### Requirement: Cron jobs SHALL support skill id bindings
Cron job definitions SHALL support an optional top-level `skill_ids` field containing a normalized comma-separated list of skill ids, and existing clients that omit the field SHALL remain compatible.

#### Scenario: Console saves skill bindings
- **WHEN** a manager creates or edits a cron job with manually entered skill ids separated by commas, whitespace, or newlines
- **THEN** the Console SHALL normalize the values into a trimmed, de-duplicated comma-separated string
- **AND** it SHALL reject invalid characters or total length greater than 200 characters
- **AND** the backend SHALL persist the normalized top-level `skill_ids`

#### Scenario: CLI creates a cron job
- **WHEN** `swe cron create` creates a cron job without a skill binding parameter
- **THEN** the backend SHALL accept the payload
- **AND** the saved job SHALL have no skill binding by default

#### Scenario: Cron binding is matched
- **WHEN** readiness checks query jobs bound to a skill id
- **THEN** a job SHALL match only when comma-boundary matching finds the exact skill id in `skill_ids`
- **AND** an empty `skill_ids` value SHALL mean unbound

#### Scenario: Broadcast copies cron skill bindings
- **WHEN** a cron job with `skill_ids` is broadcast or copied to child jobs
- **THEN** the copied job SHALL preserve `skill_ids` unless explicitly changed

### Requirement: Monitor SHALL store synchronized cron skill bindings
Monitor SHALL store the synchronized cron job `skill_ids` value for observability without adding readiness query behavior.

#### Scenario: Cron job is synchronized to Monitor
- **WHEN** SWE syncs a cron job to Monitor
- **THEN** the sync payload SHALL include the job's normalized `skill_ids`
- **AND** Monitor SHALL store it in `swe_cron_jobs.skill_ids`

#### Scenario: Monitor schema is initialized
- **WHEN** Monitor database schema initialization runs
- **THEN** it SHALL ensure `swe_cron_jobs.skill_ids VARCHAR(200) DEFAULT ''` exists
- **AND** repeated initialization SHALL be idempotent

### Requirement: Console SHALL expose a unified user readiness modal from market skill management
The Console SHALL replace the manager owner lookup action with a single "用户可执行性" action that shows owner lookup and readiness results without automatically starting checks.

#### Scenario: Manager opens user readiness modal
- **WHEN** a manager clicks "用户可执行性" for a market skill
- **THEN** the modal SHALL load the readiness overview
- **AND** it SHALL display the skill name, current skill id, skill id source, config status, owner summary/list, and latest run summary when present
- **AND** it SHALL NOT start a readiness run automatically

#### Scenario: No readiness config is available
- **WHEN** overview reports no usable readiness configuration
- **THEN** the modal SHALL show the owner list normally
- **AND** it SHALL show that self-check configuration was not found or has no enabled checks
- **AND** the start button SHALL be disabled

#### Scenario: Manager starts readiness check
- **WHEN** overview reports the skill is startable and the manager clicks the start button
- **THEN** the Console SHALL call the start run API
- **AND** it SHALL show the returned run id and progress snapshot

#### Scenario: Run is in progress
- **WHEN** the modal displays a `running` run
- **THEN** the Console SHALL show `total_users`, `completed_users`, and `failed_users`
- **AND** it SHALL provide a manual refresh action
- **AND** it SHALL NOT poll automatically

#### Scenario: Results are displayed
- **WHEN** latest run results are available
- **THEN** the Console SHALL show check summary controls and paginated user results
- **AND** normal users SHALL be visually collapsed or de-emphasized
- **AND** abnormal users SHALL be highlighted
- **AND** selecting a check failure summary SHALL filter the user set by that check while preserving each user's full check details

### Requirement: Cron management UI SHALL allow editing skill bindings without adding a list column
The Console cron create/edit drawer SHALL let managers edit `skill_ids`, but the cron job list SHALL not add a dedicated `skill_ids` column in the first version.

#### Scenario: Manager edits a cron job
- **WHEN** a manager opens the cron job create or edit drawer
- **THEN** the drawer SHALL include a manual "绑定技能 ID" input
- **AND** existing `skill_ids` SHALL be shown for editing

#### Scenario: Cron job list renders
- **WHEN** the cron job table renders
- **THEN** it SHALL NOT add a dedicated `skill_ids` column
- **AND** existing table layout SHALL remain otherwise unchanged
