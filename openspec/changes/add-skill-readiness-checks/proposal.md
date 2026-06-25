## Why

Managers need to know whether a market skill can actually run for every current user who owns that skill. The current market owner lookup only answers who owns a skill; it does not verify user runtime prerequisites such as profile identity data, bound scheduled jobs, cron authentication, model connectivity, or required MCP tools.

## What Changes

- Add a SWE backend skill readiness capability keyed by `skill_id`, with fallback to `skill_name` while the market does not yet expose a dedicated skill id.
- Move market skill owner lookup for this workflow to SWE backend aggregation so the displayed owner set and checked user set share one source of truth.
- Add skill readiness configuration storage keyed globally by `skill_id`, with generic `checks: [{ name, enabled, params }]` strategy configuration.
- Add asynchronous readiness runs for one `source_id + skill_id`, including persisted run progress, per-user results, per-check results, and per-check summaries.
- Add built-in readiness checks for profile identity block, bound scheduled job, cron auth validity, cron model connectivity, and MCP tool availability.
- Add scheduled-job skill bindings through a top-level `skill_ids` field on cron job definitions and synchronize that field to Monitor's `swe_cron_jobs`.
- Upgrade the market skill management action from owner lookup to a unified "用户可执行性" modal that shows owner list, skill id/config hints, latest readiness run, check summaries, and paginated user results.

## Capabilities

### New Capabilities

- `skill-readiness-checks`: Managers can inspect current owners of a market skill and run asynchronous readiness checks across all current owners.

### Modified Capabilities

- None.

## Impact

- SWE backend APIs, services, storage, and strategy implementations under `src/swe/app`.
- SWE cron job model, API handling, monitor sync payloads, and CLI compatibility under `src/swe/app/crons` and `src/swe/cli`.
- Monitor cron schema and sync service for storing `swe_cron_jobs.skill_ids`.
- Console market management UI under `console/src/pages/Market` and cron job create/edit UI under `console/src/pages/Control/CronJobs`.
- Console API types and client modules for skill readiness and cron job skill bindings.
- Targeted Python and Vitest coverage for configuration lookup, owner aggregation, run lifecycle, readiness strategies, cron skill binding normalization, monitor sync, and UI behavior.
