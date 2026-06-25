## 1. Storage And Models

- [x] 1.1 Add SWE schema initialization for `swe_skill_readiness_configs`, `swe_skill_readiness_runs`, `swe_skill_readiness_user_results`, and `swe_skill_readiness_check_results`.
- [x] 1.2 Add Monitor schema migration for `swe_cron_jobs.skill_ids VARCHAR(200) DEFAULT ''`.
- [x] 1.3 Add Pydantic/data models for readiness config, run, user result, check result, overview, start-run response, and paginated results.
- [x] 1.4 Add store classes with tests for config lookup, run creation/deduplication, incremental progress updates, check summaries, and filtered result pagination.

## 2. Cron Skill Binding

- [x] 2.1 Add optional top-level `skill_ids` to `CronJobSpec` with normalization/validation helpers and backwards-compatible default behavior.
- [x] 2.2 Update cron create/replace, broadcast/copy helpers, and repository persistence to preserve `skill_ids`.
- [x] 2.3 Update `MonitorSyncClient` job payloads and Monitor sync request/service handling to store `skill_ids`.
- [x] 2.4 Add backend tests for absent `skill_ids`, invalid input rejection, comma-boundary matching, disabled-vs-paused binding semantics, and broadcast copy preservation.
- [x] 2.5 Update Console cron API types and create/edit drawer helpers to edit normalized `skill_ids` without adding a cron list column.
- [x] 2.6 Add focused Vitest coverage for cron skill binding form normalization and submit payload behavior.

## 3. Readiness Backend Service

- [x] 3.1 Create `skill_readiness` backend module structure for router, service, stores, owner resolver, strategy registry, and worker.
- [x] 3.2 Implement manager/admin authorization, header/context source resolution, and skill id validation.
- [x] 3.3 Implement backend owner aggregation through market HTTP APIs with `skill_id` matching and `skill_name` fallback.
- [x] 3.4 Implement overview response with skill id, config availability/startability, config summary, owner summary/list, latest run summary, and check summaries.
- [x] 3.5 Implement start-run behavior with config snapshot, existing-running-run reuse, full owner set scheduling, concurrency limit 10, and incremental persistence.
- [x] 3.6 Implement paginated results with aggregate status filters, `check_name/check_status=fail` filters, abnormal-first ordering, and full check details per returned user.
- [x] 3.7 Add unit tests for owner aggregation success, partial failures, all-failed lookup, running run deduplication, progress counting, and result filtering.

## 4. Readiness Strategies

- [x] 4.1 Implement shared strategy interface returning `name`, `display_name`, `status`, `message`, `details`, and `duration_ms`.
- [x] 4.2 Implement `profile_identity_block` against `PROFILE.md` fixed identity heading and four required non-empty fields.
- [x] 4.3 Implement `bound_cron_job` using current SWE cron manager/list_jobs, exact comma-boundary matching, enabled/non-deleted job requirement, and paused-job inclusion.
- [x] 4.4 Implement `cron_auth_valid` using source-scoped tenant secret path and `user_info_expires_at`, with every non-pass outcome recorded as `fail`.
- [x] 4.5 Implement `cron_model_connection` using bound model-running jobs, tenant default model fallback, provider/model de-duplication, and existing model-level connectivity checks.
- [x] 4.6 Implement `mcp_tools_available` with `servers: [{ name, tools }]`, enabled-server validation, `list_tools`, missing-tool reporting, empty-config `skip`, and 10-second per-server timeout.
- [x] 4.7 Add strategy tests for pass/fail/skip cases, timeout behavior, and technical-failure-as-fail messages.

## 5. Readiness APIs

- [x] 5.1 Add `GET /api/skill-readiness/skills/{skill_id}/overview`.
- [x] 5.2 Add `POST /api/skill-readiness/skills/{skill_id}/runs`.
- [x] 5.3 Add `GET /api/skill-readiness/runs/{run_id}/results`.
- [x] 5.4 Register the router in the SWE app lifecycle and initialize readiness services/stores from the database connection.
- [x] 5.5 Add API tests for authorization, missing source context, invalid skill id, missing config, no enabled checks, run start, latest overview, and filtered results.

## 6. Market Console UI

- [x] 6.1 Replace the existing market manager owner lookup action label with "用户可执行性" and preserve its placement in card/detail management actions.
- [x] 6.2 Add a skill readiness API client and TypeScript types for overview, run start, summaries, and paginated results.
- [x] 6.3 Implement the unified modal header showing skill name, current `skill_id`, id source, config status, and configuration summary.
- [x] 6.4 Implement owner summary/list display from backend overview instead of frontend owner fan-out.
- [x] 6.5 Implement latest run/progress display, explicit start button, disabled start states, and manual refresh without polling.
- [x] 6.6 Implement check summary controls, abnormal-first paginated user results, normal-result collapse/de-emphasis, abnormal highlighting, and check failure filtering while showing full checks.
- [x] 6.7 Add focused Vitest coverage for skill id fallback labeling, no-config start disabled state, start-run action, and check filter request parameters.

## 7. Documentation And Verification

- [x] 7.1 Update repository documentation/wiki references for the backend-owned skill readiness workflow and cron `skill_ids` binding.
- [x] 7.2 Run targeted backend tests for readiness stores/services/strategies/APIs and cron/monitor sync changes.
- [x] 7.3 Run targeted frontend tests for cron binding helpers and market readiness modal behavior.
- [x] 7.4 Run OpenSpec validation for `add-skill-readiness-checks`.
- [x] 7.5 Run GitNexus change detection before any commit or implementation handoff.
