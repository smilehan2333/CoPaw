## Context

The market page already has a manager-only owner lookup for skills, but that lookup is a Console-side fan-out over source users and market skill APIs. The new requirement needs a stronger contract: the owner set shown to managers and the users checked by readiness runs must come from the same backend aggregation, and the checks must inspect SWE runtime state that the frontend cannot reliably evaluate.

The checks span multiple subsystems: market skill state, source-scoped user runtime directories, `PROFILE.md`, cron authentication, scheduled jobs, tenant model configuration, MCP clients, Monitor cron synchronization, and Console market/cron management UI. The feature therefore belongs in SWE as a backend readiness service with persisted run state and generic check results.

## Goals / Non-Goals

**Goals:**

- Let managers inspect the current user owner set for a market skill and run readiness checks across the full owner set.
- Use `skill_id` as the stable key, falling back to `skill_name` only while the market does not expose `skill_id`.
- Persist readiness configuration, run progress, per-user results, and per-check results in SWE backend storage.
- Support more than 200 owners without frontend polling or frontend fan-out.
- Keep readiness check types extensible without adding per-check database columns or per-check APIs.
- Add cron job skill bindings with CLI compatibility and Monitor sync storage.
- Upgrade the existing market owner lookup entry into one "用户可执行性" manager action.

**Non-Goals:**

- No frontend readiness configuration editor in the first version.
- No YAML readiness configuration.
- No historical run list UI or automatic run cleanup.
- No cross-instance cron aggregation in the first version.
- No new Monitor query page or readiness execution in Monitor.
- No automatic readiness run when the modal opens.

## Decisions

### Source and skill identity

SWE readiness APIs resolve `source_id` only from the request context/header, not from a query parameter. The path `skill_id` is validated with the same character set used by cron binding input: letters, digits, underscore, hyphen, dot, and colon. The Console computes the effective skill id as `skill.skill_id || skill.skill_name` and displays whether it came from the market id or the fallback name.

Alternative considered: accept `source_id` as a query override. This was rejected because existing market calls already use `X-Source-Id`, and allowing two source transports makes manager actions easier to call with inconsistent scope.

### Backend owner aggregation

The readiness service reuses market HTTP API semantics instead of reading market files or database tables directly. It resolves the current source's users, calls the market "mine" and "received" skill APIs per user, and matches by market `skill_id` when available, otherwise by `skill_name`. Users are de-duplicated by `user_id`; display fields such as `user_name` and `bbk_id` come from the user list when available.

Partial owner lookup failures do not block the whole run. Successfully resolved owners continue into readiness checks, and the run records lookup failure counts and summaries. If all owner lookup work fails and no user result can be produced, the run is `failed`.

### Configuration storage

Readiness configuration lives in a dedicated SWE table keyed globally by `skill_id`, not in source system configuration. The configuration shape is generic:

```json
{
  "checks": [
    { "name": "cron_auth_valid", "enabled": true, "params": {} }
  ]
}
```

The first version is read-only from product UI/API; operators can insert or update rows directly in the database. A run captures `config_snapshot` at start and uses that immutable snapshot even if the base config changes while the run is executing.

### Run and result persistence

SWE stores readiness data in three generic tables:

- `swe_skill_readiness_runs`: run state, `source_id`, `skill_id`, `config_snapshot`, owner lookup summary, progress counts, failure summary, and timestamps.
- `swe_skill_readiness_user_results`: one row per run/user with user identity, aggregate status, result summary, duration, and timestamps.
- `swe_skill_readiness_check_results`: one row per run/user/check with `check_name`, `status`, display/message/details, and duration.

The separate check result table keeps filtering by `check_name + status` index-backed without making each new check type a schema migration. The user results API filters the user set through the check result table but still returns the full check list for each returned user.

### Asynchronous run lifecycle

Starting a run for a `source_id + skill_id` with an existing `running` run returns the existing run instead of creating a duplicate. Runs process all current owners with no hard 200-user cap. User checks run with a default user-level concurrency of 10. Checks within one user run sequentially under a default 60-second user wall-time timeout.

The service persists results incrementally: each completed user updates the user result, check result rows, and run progress counts. `completed_users` counts users whose readiness evaluation finished, whether normal or abnormal. `failed_users` counts abnormal users, meaning users with at least one `fail` check. `total_users` is the resolved owner set size.

Run status remains separate from check status:

- `running`: work is in progress.
- `completed`: all resolved users were checked and no run-level partial failure remains.
- `partial`: some user results are available but non-fatal lookup or execution failures prevented a fully complete run.
- `failed`: no user results are available or startup/storage/config work fails before useful output.

### Check status and built-in strategies

Per-check status is normalized to `pass`, `fail`, or `skip`. There is no separate `error` status; technical failures are `fail` with diagnostic `message` and `details`. Users are normal when all checks are `pass` or `skip`, and abnormal when any check is `fail`.

Built-in checks:

- `profile_identity_block`: `PROFILE.md` contains `### 用户身份信息` and non-empty `分行号`, `网点机构编号`, `岗位编号`, and `客户经理ID`.
- `bound_cron_job`: at least one enabled, non-deleted cron job is bound to the skill id. Paused jobs count as bindings; disabled jobs do not count as executable.
- `cron_auth_valid`: `cron_auth.json` exists in the source-scoped tenant secret directory, is readable, has `user_info_expires_at`, and that value is in the future. Every other outcome is `fail`.
- `cron_model_connection`: checks the actual models used by enabled, non-deleted, model-running bound cron jobs, including paused jobs. Jobs without explicit `model_slot` check the tenant default model. Models are de-duplicated by `(provider_id, model_id)` and tested through the existing model-level connection check.
- `mcp_tools_available`: checks configured MCP server names and required tool names using runtime MCP configuration and `list_tools`. Empty `servers` params produce `skip`.

MCP server checks use a 10-second per-server timeout. Model connectivity reuses the current model-level test behavior and timeouts.

### Cron skill binding

Cron jobs gain a top-level optional `skill_ids` string. Console create/edit accepts comma, newline, or whitespace input, trims and de-duplicates values, validates characters, and stores a comma-separated string no longer than 200 characters. CLI `swe cron create` does not add a parameter in the first version and therefore creates unbound jobs by default.

Monitor `swe_cron_jobs` gains `skill_ids VARCHAR(200) DEFAULT ''`, and SWE monitor sync sends the field. Broadcast/copied cron jobs preserve `skill_ids` unless explicitly changed. The Console cron job list does not add a new column in the first version; the field is visible in create/edit.

Readiness checks use the SWE current instance cron manager/list_jobs as the scheduled-job data source in the first version. Monitor stores the binding for observability but does not execute readiness queries.

### API and UI

All readiness APIs require manager/admin authorization:

- `GET /api/skill-readiness/skills/{skill_id}/overview`
- `POST /api/skill-readiness/skills/{skill_id}/runs`
- `GET /api/skill-readiness/runs/{run_id}/results`

Overview returns the effective skill id, config availability/startability, config summary, owner summary/list, latest run summary, and per-check summaries. Starting a run is explicit; opening the modal never starts a run. Results are paginated, abnormal users sort first by default, and filters support user aggregate status plus `check_name` and `check_status=fail`. When filtering by a check, returned users still include all checks.

The market UI replaces the existing "查看拥有用户" manager action with "用户可执行性". The modal shows skill id/source, config status, owner list, latest run/progress, per-check summary cards, a manual start button, refresh action, and paginated results. Normal results are collapsed visually and abnormal results are emphasized.

## Risks / Trade-offs

- Owner fan-out over many users can be slow -> backend async runs persist progress incrementally and the UI reads snapshots on open/refresh instead of polling.
- JSON-only check storage would make filtered failure queries slow -> store generic indexed check result rows.
- Model/MCP checks can stress external dependencies -> default user concurrency is 10, checks are serial per user, and MCP has per-server timeout.
- Current-instance cron lookup can miss jobs on another SWE instance -> accepted first-version limitation; no UI warning per requirement.
- Manual database configuration can be error-prone -> validate config on read/start and make missing or empty enabled checks non-startable with clear UI messaging.
- `skill_name` fallback can collide if names are not stable -> display fallback source in the modal and keep API/DB field name `skill_id` so migration to market ids does not rename fields.

## Migration Plan

1. Add SWE readiness tables and Monitor `swe_cron_jobs.skill_ids` with idempotent schema initialization.
2. Add optional `CronJobSpec.skill_ids` with default empty behavior so old payloads and CLI-created jobs remain valid.
3. Add monitor sync read/write support for `skill_ids`.
4. Deploy backend readiness APIs and services before enabling the Console modal action.
5. Operators manually insert readiness configuration rows for target skills.
6. Rollback can leave the new tables/columns unused; old cron payloads remain compatible because `skill_ids` is optional.

## Open Questions

None. First-version scope and the deferred items were confirmed: no config UI, no history UI, no auto cleanup, no frontend polling, no cross-instance cron aggregation, no Monitor readiness queries, and no CLI skill binding parameter.
