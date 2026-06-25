# Skill Readiness Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backend-owned skill readiness workflow that checks whether every current owner of a market skill can execute that skill, and expose it from the market management UI.

**Architecture:** SWE owns readiness config, owner aggregation, async run state, strategy execution, and result APIs. Cron jobs carry a normalized top-level `skill_ids` binding that is synchronized to Monitor for observability. Console becomes a thin client: it sends the effective `skill_id`, shows backend overview/results, and edits cron bindings.

**Tech Stack:** Python FastAPI/Pydantic/pytest, existing SWE database connection wrapper, Monitor MySQL schema bootstrap, React/TypeScript/Ant Design/Vitest, GitNexus CLI for impact/change checks.

---

## Guardrails

- Do not commit unless the user explicitly asks for a commit.
- Do not revert unrelated workspace changes.
- Before modifying an existing symbol, run GitNexus impact analysis and record the blast radius in the working notes or final summary.
- New Python comments and docstrings must be concise Simplified Chinese where comments are necessary.
- Preserve `swe cron create` compatibility: omitted `skill_ids` must be accepted and saved as an empty binding.
- Readiness APIs must resolve `source_id` from headers/context only; do not add a query parameter override.

## File Map

Create:

- `src/swe/app/skill_readiness/__init__.py`: service/router package exports.
- `src/swe/app/skill_readiness/models.py`: Pydantic request/response and persisted-domain models.
- `src/swe/app/skill_readiness/store.py`: readiness table DDL and query/update methods.
- `src/swe/app/skill_readiness/service.py`: overview, run start, result pagination orchestration.
- `src/swe/app/skill_readiness/owner_resolver.py`: source user and market skill owner aggregation.
- `src/swe/app/skill_readiness/runner.py`: async user-run scheduling and incremental persistence.
- `src/swe/app/skill_readiness/strategies.py`: strategy protocol/registry and built-in checks.
- `src/swe/app/skill_readiness/router.py`: FastAPI routes and manager/admin/source validation.
- `tests/unit/app/skill_readiness/test_store.py`: config/run/result store behavior.
- `tests/unit/app/skill_readiness/test_service.py`: owner aggregation, run dedupe, filters.
- `tests/unit/app/skill_readiness/test_strategies.py`: pass/fail/skip strategy cases.
- `tests/unit/app/skill_readiness/test_router.py`: API auth, validation, and response behavior.
- `console/src/api/skillReadiness.ts`: readiness API client.
- `console/src/api/types/skillReadiness.ts`: readiness TypeScript contracts.
- `console/src/pages/Market/components/SkillReadinessModal.tsx`: unified owner/readiness modal.
- `console/src/pages/Market/components/__tests__/SkillReadinessModal.test.tsx`: focused modal tests.

Modify:

- `src/swe/app/_app.py`: initialize readiness tables/services during app startup.
- `src/swe/app/routers/__init__.py`: register `skill_readiness.router`.
- `src/swe/app/crons/models.py`: add normalized optional `CronJobSpec.skill_ids`.
- `src/swe/app/crons/monitor_sync_client.py`: include `skill_ids` in sync payloads.
- Existing cron repository/manager/broadcast files identified by impact/explorer pass: preserve top-level `skill_ids`.
- `src/swe/cli/cron_cmd.py`: keep create command compatible; no CLI flag required.
- `monitor/src/monitor/app/database/schema.py`: add `skill_ids` DDL and idempotent extra-column migration.
- Monitor cron sync request/service files identified by explorer pass: accept/store `skill_ids`.
- `console/src/api/types/cronjob.ts`: add optional `skill_ids`.
- `console/src/pages/Control/CronJobs/helpers.ts`: normalize/validate form values and payload.
- Cron drawer component identified by explorer pass: add manual skill binding input.
- Existing market skill card/detail management files identified by explorer pass: replace owner lookup action with readiness modal action.
- `openspec/changes/add-skill-readiness-checks/tasks.md`: check off completed implementation tasks only after tests pass.

## Task 0: Impact Checks And Baseline

**Files:**
- Read-only: `.gitnexus/`, `src/swe/app/crons/models.py`, `src/swe/app/_app.py`, `src/swe/app/routers/__init__.py`, `monitor/src/monitor/app/database/schema.py`

- [ ] **Step 0.1: Check GitNexus command availability**

Run:

```powershell
npx gitnexus status
npx gitnexus impact --help
```

Expected: status reports the CoPaw index; help shows impact command syntax.

- [ ] **Step 0.2: Run impact for existing backend symbols before editing**

Run the valid syntax discovered in Step 0.1 for these targets:

```text
CronJobSpec
MonitorSyncClient
_build_job_sync_data
_ROUTER_MODULES
create_app
CREATE_CRON_JOBS_TABLE
_ensure_cron_jobs_extra_schema
```

Expected: record direct callers, affected processes, and risk level. If any target is HIGH or CRITICAL, warn before editing that slice.

- [ ] **Step 0.3: Run current focused baseline tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/app/test_source_system_config.py -q
& .\.venv\Scripts\python.exe -m pytest tests/unit/app/test_cron*.py -q
```

Expected: either pass, or record pre-existing missing-test-file/collection issues before changing code.

## Task 1: Readiness Storage And Models

**Files:**
- Create: `src/swe/app/skill_readiness/models.py`
- Create: `src/swe/app/skill_readiness/store.py`
- Create: `tests/unit/app/skill_readiness/test_store.py`
- Modify: `src/swe/app/_app.py`

- [ ] **Step 1.1: Write store tests first**

Create tests that use an in-memory/fake database wrapper matching `src/swe/database/connection.py` methods. Cover:

```python
def test_config_lookup_reports_missing_config(): ...
def test_config_lookup_parses_enabled_checks(): ...
def test_create_run_reuses_existing_running_run(): ...
def test_record_user_result_updates_completed_and_failed_counts(): ...
def test_results_filter_by_failed_check_but_return_all_checks(): ...
```

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/app/skill_readiness/test_store.py -q
```

Expected before implementation: failures for missing module/classes.

- [ ] **Step 1.2: Implement model contracts**

Define exact statuses and response shapes in `models.py`:

```python
CHECK_STATUSES = {"pass", "fail", "skip"}
RUN_STATUSES = {"running", "completed", "partial", "failed"}
USER_STATUSES = {"normal", "abnormal"}
```

Models must include config checks `{name, enabled, params}`, owner rows `{user_id, user_name, bbk_id}`, run progress `{total_users, completed_users, failed_users}`, check summaries `{check_name, display_name, total, pass_count, fail_count, skip_count}`, and paginated results with full checks per user.

- [ ] **Step 1.3: Implement table DDL and store methods**

`store.py` must expose idempotent initialization for:

```sql
swe_skill_readiness_configs(skill_id, config_json, created_at, updated_at)
swe_skill_readiness_runs(run_id, source_id, skill_id, status, total_users, completed_users, failed_users, config_snapshot, owner_lookup_summary, failure_summary, created_at, started_at, completed_at, updated_at)
swe_skill_readiness_user_results(run_id, user_id, user_name, bbk_id, aggregate_status, summary, duration_ms, created_at, updated_at)
swe_skill_readiness_check_results(run_id, user_id, check_name, display_name, status, message, details_json, duration_ms, created_at)
```

Add indexes for `(source_id, skill_id, status)`, `(source_id, skill_id, created_at)`, `(run_id, aggregate_status)`, and `(run_id, check_name, status, user_id)`.

- [ ] **Step 1.4: Register initialization in app startup**

Follow the source-system-config service/store pattern in `src/swe/app/_app.py`. Initialization must be safe when database connection is unavailable and must not block app creation if the optional service cannot be created.

- [ ] **Step 1.5: Verify storage tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/app/skill_readiness/test_store.py -q
```

Expected: all store tests pass.

## Task 2: Cron Skill Binding And Monitor Sync

**Files:**
- Modify: `src/swe/app/crons/models.py`
- Modify: cron repository/manager/broadcast files located by explorer/impact
- Modify: `src/swe/app/crons/monitor_sync_client.py`
- Modify: `monitor/src/monitor/app/database/schema.py`
- Modify: Monitor cron sync request/service files located by explorer/impact
- Modify: `tests/unit/app/...` cron and monitor sync tests

- [ ] **Step 2.1: Write cron binding tests first**

Add tests for:

```python
def test_cron_job_spec_defaults_skill_ids_to_empty_string(): ...
def test_cron_job_spec_normalizes_skill_ids(): ...
def test_cron_job_spec_rejects_invalid_skill_ids(): ...
def test_skill_id_matching_uses_comma_boundaries(): ...
def test_paused_job_counts_but_disabled_job_does_not_count(): ...
def test_monitor_sync_payload_includes_skill_ids(): ...
```

Run the new/updated test files with pytest. Expected before implementation: failures.

- [ ] **Step 2.2: Add normalization helper**

Implement a helper equivalent to:

```python
VALID_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")

def normalize_skill_ids(value: str | Sequence[str] | None) -> str:
    if not value:
        return ""
    raw = value if isinstance(value, str) else ",".join(value)
    parts = [part.strip() for part in re.split(r"[\s,]+", raw) if part.strip()]
    deduped = list(dict.fromkeys(parts))
    for part in deduped:
        if not VALID_SKILL_ID_RE.fullmatch(part):
            raise ValueError("skill_id 只能包含字母、数字、下划线、短横线、点和冒号")
    normalized = ",".join(deduped)
    if len(normalized) > 200:
        raise ValueError("skill_ids 总长度不能超过 200")
    return normalized
```

Expose exact comma-boundary matching through `cron_skill_ids_contains(skill_ids: str, skill_id: str) -> bool`.

- [ ] **Step 2.3: Add `CronJobSpec.skill_ids`**

Set default `""`, normalize in model validation, and preserve omitted values from old CLI/API payloads.

- [ ] **Step 2.4: Preserve binding through cron flows**

Ensure create/replace/list/persist/copy/broadcast paths serialize the new top-level field without adding a CLI flag.

- [ ] **Step 2.5: Sync binding to Monitor**

Add `skill_ids` to SWE monitor sync payload and Monitor request/upsert handling. Add `skill_ids VARCHAR(200) DEFAULT ''` to `CREATE_CRON_JOBS_TABLE` and the idempotent extra-column map.

- [ ] **Step 2.6: Verify cron/monitor tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/app -k "cron or monitor" -q
```

Expected: targeted cron and monitor tests pass or unrelated pre-existing tests are recorded.

## Task 3: Readiness Service, Owner Resolver, Runner, And APIs

**Files:**
- Create: `src/swe/app/skill_readiness/owner_resolver.py`
- Create: `src/swe/app/skill_readiness/service.py`
- Create: `src/swe/app/skill_readiness/runner.py`
- Create: `src/swe/app/skill_readiness/router.py`
- Modify: `src/swe/app/routers/__init__.py`
- Create: `tests/unit/app/skill_readiness/test_service.py`
- Create: `tests/unit/app/skill_readiness/test_router.py`

- [ ] **Step 3.1: Write owner/service/API tests first**

Cover:

```python
def test_overview_uses_backend_owner_aggregation_and_config_summary(): ...
def test_start_run_rejects_missing_config(): ...
def test_start_run_reuses_running_run_for_source_and_skill(): ...
def test_partial_owner_failures_mark_run_partial_when_results_exist(): ...
def test_all_owner_lookup_failure_marks_run_failed(): ...
def test_results_filter_by_failed_check_returns_full_check_list(): ...
def test_api_rejects_non_manager_role(): ...
def test_api_rejects_missing_source_context(): ...
def test_api_rejects_invalid_skill_id(): ...
```

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/app/skill_readiness/test_service.py tests/unit/app/skill_readiness/test_router.py -q
```

Expected before implementation: failures.

- [ ] **Step 3.2: Implement request validation**

Router must accept only skill ids matching `^[A-Za-z0-9_.:-]+$`, require role header/context `manager` or `admin`, and require resolved `source_id` from existing request/header helpers. Do not accept `source_id` query parameters.

- [ ] **Step 3.3: Implement owner aggregation**

Owner resolver must enumerate active source users through existing source-system/user APIs, call market HTTP APIs for each user's mine/received skill lists, match by `skill_id` when present and fallback `skill_name`, and de-duplicate by `user_id`. Partial failures must return a summary instead of raising when at least one user lookup succeeds.

- [ ] **Step 3.4: Implement overview and latest-run projection**

Overview response must include effective `skill_id`, config found/startable state, enabled check summaries, owner summary/list, latest run progress/status, and latest run check summaries.

- [ ] **Step 3.5: Implement start-run orchestration**

Start must load config, require enabled checks, reuse existing running run for `(source_id, skill_id)`, create a new run with config snapshot, resolve full owner set, and schedule async execution. It must return immediately with run id/progress.

- [ ] **Step 3.6: Implement result pagination**

Support `page`, `page_size`, `status=all|normal|abnormal`, `check_name`, and `check_status=fail`. Sort abnormal users first by default and return all check rows for every returned user.

- [ ] **Step 3.7: Verify service/API tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/app/skill_readiness/test_service.py tests/unit/app/skill_readiness/test_router.py -q
```

Expected: tests pass.

## Task 4: Readiness Strategies

**Files:**
- Create/modify: `src/swe/app/skill_readiness/strategies.py`
- Create: `tests/unit/app/skill_readiness/test_strategies.py`

- [ ] **Step 4.1: Write strategy tests first**

Tests must cover:

```python
def test_profile_identity_block_requires_heading_and_four_fields(): ...
def test_bound_cron_job_requires_enabled_non_deleted_binding_and_counts_paused(): ...
def test_cron_auth_valid_requires_future_user_info_expires_at(): ...
def test_cron_model_connection_skips_when_no_model_running_bound_jobs(): ...
def test_cron_model_connection_fails_failed_model_test(): ...
def test_mcp_tools_available_skips_empty_config(): ...
def test_mcp_tools_available_fails_missing_server_or_tool(): ...
def test_strategy_technical_exception_is_fail_not_error(): ...
```

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/app/skill_readiness/test_strategies.py -q
```

Expected before implementation: failures.

- [ ] **Step 4.2: Implement shared strategy contract**

Each strategy returns `check_name`, `display_name`, `status`, `message`, `details`, and `duration_ms`. Registry display names must be:

```text
profile_identity_block -> 用户身份信息
bound_cron_job -> 绑定定时任务
cron_auth_valid -> 定时任务鉴权
cron_model_connection -> 模型连通性
mcp_tools_available -> MCP 工具可用性
```

- [ ] **Step 4.3: Implement profile check**

Read the tenant user's `PROFILE.md`, require heading `### 用户身份信息`, and require non-empty `分行号`, `网点机构编号`, `岗位编号`, `客户经理ID`.

- [ ] **Step 4.4: Implement cron binding check**

Use current SWE cron manager/list jobs for the user, exact comma-boundary `skill_ids` matching, enabled and non-deleted jobs only. Paused jobs count as present. Disabled-only matches fail with a clear message.

- [ ] **Step 4.5: Implement cron auth check**

Use the same source-scoped tenant secret path logic as `/system-check/cron-auth-expiry`: `resolve_scope_id(tenant_id, source_id)` and `get_tenant_secrets_dir(scope_id) / "cron_auth.json"`. Pass only when `user_info_expires_at` is present and in the future. Missing, unreadable, malformed, and expired files fail.

- [ ] **Step 4.6: Implement model and MCP checks**

Model check inspects enabled/non-deleted model-running bound jobs, includes paused jobs, falls back to tenant default model when no explicit model slot exists, de-duplicates `(provider_id, model_id)`, and uses existing model-level connectivity behavior. MCP check validates configured `{name, tools}` servers, uses a 10-second per-server timeout, and fails on missing/disabled/list-tools/missing-tool conditions.

- [ ] **Step 4.7: Verify strategy tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/app/skill_readiness/test_strategies.py -q
```

Expected: tests pass.

## Task 5: Console Cron Binding

**Files:**
- Modify: `console/src/api/types/cronjob.ts`
- Modify: `console/src/pages/Control/CronJobs/helpers.ts`
- Modify: Cron drawer component located by explorer pass
- Create/modify: focused Vitest tests for CronJobs helpers

- [ ] **Step 5.1: Write helper tests first**

Test:

```ts
expect(normalizeSkillIdsInput("a, b\nc a")).toBe("a,b,c");
expect(() => normalizeSkillIdsInput("bad/id")).toThrow();
expect(() => normalizeSkillIdsInput("x".repeat(201))).toThrow();
expect(buildCronJobSubmitPayload({ skillIds: "" }).skill_ids).toBe("");
```

Run the matching Vitest file with:

```powershell
.\node_modules\.bin\vitest.cmd run console/src/pages/Control/CronJobs --runInBand
```

Expected before implementation: failures.

- [ ] **Step 5.2: Add cron type field**

Add optional `skill_ids?: string` to cron job input/output types without changing table columns.

- [ ] **Step 5.3: Add helper normalization**

Implement `normalizeSkillIdsInput` in `helpers.ts` using the same split/dedupe/character/length rules as backend. Use `skillIds` as form field name if existing form uses camelCase values, and serialize to top-level `skill_ids`.

- [ ] **Step 5.4: Add drawer input**

Add a manual input labeled `绑定技能ID`. Existing jobs must populate the field; submitting empty input must send `skill_ids: ""` or omit only if existing helper convention omits empty optional fields safely.

- [ ] **Step 5.5: Verify cron UI tests**

Run the focused Vitest command from Step 5.1. Expected: tests pass.

## Task 6: Console Market Readiness Modal

**Files:**
- Create: `console/src/api/types/skillReadiness.ts`
- Create: `console/src/api/skillReadiness.ts`
- Create: `console/src/pages/Market/components/SkillReadinessModal.tsx`
- Modify: existing market skill card/detail management action files located by explorer pass
- Create: `console/src/pages/Market/components/__tests__/SkillReadinessModal.test.tsx`

- [ ] **Step 6.1: Write modal tests first**

Tests must cover:

```ts
it("uses skill.skill_id when present and labels source as market skill id", ...);
it("falls back to skill_name when skill_id is missing", ...);
it("disables start when overview reports no usable config", ...);
it("starts a run only after clicking the start button", ...);
it("passes check_name and check_status=fail when a failed check summary is selected", ...);
```

Run:

```powershell
.\node_modules\.bin\vitest.cmd run console/src/pages/Market --runInBand
```

Expected before implementation: failures.

- [ ] **Step 6.2: Add API client/types**

Client functions:

```ts
getSkillReadinessOverview(skillId: string)
startSkillReadinessRun(skillId: string)
getSkillReadinessResults(runId: string, params)
```

Types must include config status, owner summary/list, latest run progress/status, check summaries, paginated users, and full check details.

- [ ] **Step 6.3: Implement modal loading and header**

Opening modal loads overview only. Header shows skill name, current `skill_id`, id source, and whether self-check config was found/startable.

- [ ] **Step 6.4: Implement owner/run/results UI**

Show backend owner summary/list. Show latest run progress and manual refresh. Start button is explicit and disabled when not startable. No polling.

- [ ] **Step 6.5: Implement failure filtering and result display**

Summary controls request `check_name=<name>&check_status=fail`. Returned users must render all checks. Abnormal users are highlighted; normal users are collapsed or visually de-emphasized.

- [ ] **Step 6.6: Replace owner lookup action**

Replace existing manager action label with `用户可执行性` and wire it to the new modal. Remove old frontend fan-out owner lookup from this path.

- [ ] **Step 6.7: Verify market UI tests**

Run focused Vitest command from Step 6.1. Expected: tests pass.

## Task 7: Documentation, OpenSpec, And Final Verification

**Files:**
- Modify: `analysis/observability-and-supporting-systems.md` or a closer cron/market playbook if discovered
- Modify: `openspec/changes/add-skill-readiness-checks/tasks.md`

- [ ] **Step 7.1: Update docs**

Document backend-owned readiness flow, DB-backed config, cron `skill_ids`, and Monitor's observability-only role. Use the existing `analysis/` document that best matches cron/supporting systems.

- [ ] **Step 7.2: Update OpenSpec task checkboxes**

Check only tasks whose implementation and tests have passed. Leave unchecked any intentionally deferred or unverified item with a short note in the final summary.

- [ ] **Step 7.3: Run backend verification**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/app/skill_readiness tests/unit/app -k "cron or monitor" -q
```

Expected: targeted backend tests pass.

- [ ] **Step 7.4: Run frontend verification**

Run:

```powershell
.\node_modules\.bin\vitest.cmd run console/src/pages/Control/CronJobs console/src/pages/Market --runInBand
```

Expected: targeted frontend tests pass.

- [ ] **Step 7.5: Validate OpenSpec**

Run:

```powershell
openspec.cmd validate "add-skill-readiness-checks"
```

Expected: validation passes.

- [ ] **Step 7.6: Run GitNexus change detection**

Run the available GitNexus change-detection command or MCP `detect_changes` equivalent. If CLI help does not expose it, run `npx gitnexus analyze` and record that MCP change detection was unavailable.

Expected: affected scope is limited to readiness, cron binding, Monitor sync schema, and Console market/cron UI.
