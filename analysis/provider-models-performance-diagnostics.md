# Provider Models API Performance Diagnostics

Date: 2026-06-15

## Scope

This note records the diagnostic plan for slow provider model APIs:

- `GET /api/models`
- `GET /api/models/active?scope=xxx&agent_id=xxx`

The observed production symptom is that these two APIs repeatedly take
6-9 seconds while other APIs are around 100 ms. The current conclusion is not
that tenant/source double parsing is the proven root cause. Double parsing is a
confirmed correctness/cache-key issue, but repeated 6-9 second latency still
requires production evidence.

## Instrumentation Added

Slow logs are emitted only when a measured segment takes at least 500 ms.

### `provider_manager_dependency_slow`

Emitted from `get_provider_manager()` when dependency resolution is slow.

Important fields:

- `path`: request path.
- `total_ms`: total time spent in provider manager dependency resolution.
- `resolve_ms`: tenant/source/scope resolution time.
- `ensure_ms`: time spent in `ProviderManager.ensure_tenant_provider_storage(...)`.
- `get_instance_ms`: time spent in `ProviderManager.get_instance(...)`.
- `route_tenant_id`: tenant id after router-level storage resolution.
- `provider_tenant_id`: tenant id after ProviderManager-level resolution.
- `manager_tenant_id`: tenant id on the returned manager instance.
- `source_id`: request source id.
- `scope_id`: request scope id.
- `cache_hit_before`: whether the provider manager instance existed before
  `get_instance`.
- `cache_hit_after`: whether the returned manager is now in the instance cache.
- `root_path`: provider storage path used by ProviderManager.
- `root_exists`: whether that provider storage path exists.

### `provider_list_info_slow`

Emitted from `GET /api/models` when `manager.list_provider_info()` is slow.

Important fields:

- `tenant_id`: manager tenant id.
- `duration_ms`: time spent listing provider info.
- `provider_count`: number of providers returned.
- `custom_count`: number of custom providers loaded.
- `root_path`: provider storage path.

### `provider_active_model_read_slow`

Emitted from `GET /api/models/active` when the handler body is slow after
dependency injection.

Important fields:

- `tenant_id`: manager tenant id.
- `duration_ms`: time spent reading the active model from the manager.
- `scope`: request scope query value.
- `root_path`: provider storage path.

## How To Interpret Logs

### Dependency Resolution Is Slow

If `provider_manager_dependency_slow.total_ms` is high, the latency is before
the endpoint body. This explains both `/api/models` and `/api/models/active`.

Use the segment fields:

- `ensure_ms` high:
  - Provider storage existence checks are slow.
  - Provider storage initialization/copy is slow.
  - File lock wait is slow.
  - Storage path may be on slow PVC/NFS/object-backed volume.
  - `root_exists=false` with repeated requests suggests repeated failed or
    ineffective initialization.

- `get_instance_ms` high:
  - ProviderManager cache missed.
  - Constructor work is slow: directory creation, provider JSON loads,
    `active_model.json`, legacy tenant model recovery, capability annotation,
    or mtime snapshot.
  - If `cache_hit_before=false` repeats for the same logical request identity,
    investigate unstable effective tenant keys or process restarts.

- `resolve_ms` high:
  - Tenant/source/scope parsing itself is unexpectedly slow.
  - This is less likely because local reproduction shows this path is normally
    tiny.

### Tenant Key Mismatch Is Present

Compare:

- `route_tenant_id`
- `provider_tenant_id`
- `manager_tenant_id`

If these differ, router-level storage resolution and ProviderManager-level
resolution are not idempotent for the request. A known example is:

- raw identity: `tenant=default`, `source=RMASSIST`
- expected storage key: `default_RMASSIST`
- double-resolved key: an encoded scope for `default_RMASSIST + RMASSIST`

This confirms the double parsing/correctness issue. It does not by itself prove
6-9 second latency unless paired with repeated cache misses, slow storage,
directory initialization, or lock waits.

### `/api/models` Is Slow But `/api/models/active` Is Not

If only `provider_list_info_slow` appears, while
`provider_manager_dependency_slow` does not, the likely cause is inside
`list_provider_info()`:

- `_refresh_if_stale()` does per-request filesystem checks.
- Custom provider directory scanning may be slow.
- Provider JSON count or storage latency may be high.

Production follow-up:

- Count files under `{root_path}/custom/*.json`.
- Check storage latency for `stat`, `glob`, and small JSON reads.
- Check whether provider files are being modified frequently, causing reloads.

### `/api/models/active` Handler Body Is Slow

If `provider_active_model_read_slow` appears, this is abnormal because
`manager.get_active_model()` should be an in-memory read.

Likely interpretations:

- The event loop was blocked by another synchronous operation before the handler
  resumed.
- Logging timestamps around dependency and handler execution need correlation.
- The process is under CPU starvation or global interpreter/thread contention.

This log should be rare. If it appears consistently, inspect concurrent slow
logs in the same time window.

## Production Log Collection Checklist

When the issue reproduces in production, collect logs around the same time
window for these strings:

- `provider_manager_dependency_slow`
- `provider_list_info_slow`
- `provider_active_model_read_slow`
- `Initializing provider config`
- `Provider config initialized`
- `Waiting for concurrent provider initialization`
- `Failed to initialize provider config`
- `ensure_bootstrap duration_ms`
- `bootstrap_fast_path_hit`
- `bootstrap_fast_path_miss`

For each slow request, preserve the full line. The key fields needed for root
cause analysis are:

- path
- total_ms
- ensure_ms
- get_instance_ms
- route_tenant_id
- provider_tenant_id
- manager_tenant_id
- source_id
- scope_id
- cache_hit_before
- root_path
- root_exists

## Current Working Hypotheses

These remain hypotheses until production logs confirm them:

1. Provider storage key is double-resolved or unstable, causing repeated cache
   misses or wrong provider directories.
2. Provider storage is on slow production storage, making synchronous
   `exists/stat/glob/copytree` operations block the single Uvicorn worker.
3. Concurrent frontend requests to `/api/models` and `/api/models/active`
   amplify ProviderManager initialization or lock waits.
4. `/api/models` has an additional per-request filesystem scan via
   `_refresh_if_stale()`.

The next analysis step should start from production log lines, not from another
speculative code change.

## 2026-06-24 Follow-up: 30s Timeout With No Existing Slow Logs

New production facts:

- Affected tenants have already been initialized.
- Provider directories and provider JSON content already exist.
- `X-User-Name` and `X-Bbk-Id` are present on the slow requests.
- No `Error fetching user info for tenant ...` logs are emitted.
- No `provider_manager_dependency_slow` or `provider_list_info_slow` logs are
  emitted before the request fails around 30 seconds.

Interpretation:

- The user identity remote lookup path is not the active cause when both
  identity headers are present.
- Existing slow logs are return-after logs. Their absence means the request does
  not reach those completed measurement points before the client/gateway times
  out.
- With provider storage confirmed present, the highest-value suspect is a
  request stuck before `ProviderManager.get_instance(...)` returns:
  - provider storage existence checks or provider init lock;
  - global `ProviderManager._instances_lock` wait;
  - `ProviderManager(...)` construction under that global lock;
  - filesystem work during construction (`mkdir`, `glob`, `stat`, small JSON
    reads, `active_model.json`, freshness token recording).

Additional boundary logs were added to locate non-returning segments:

- `provider_manager_dependency_start`
- `provider_storage_ensure_start`
- `provider_storage_ensure_done`
- `provider_manager_get_instance_start`
- `provider_manager_get_instance_done`
- `provider_manager_instance_cache_miss`
- `provider_manager_instance_lock_acquired`
- `provider_manager_instance_create_start`
- `provider_manager_instance_create_done`
- `provider_manager_instance_reused_after_lock`
- `provider_manager_init_start`
- `provider_manager_init_step_start`
- `provider_manager_init_step_done`
- `provider_manager_init_done`

### How To Diagnose The Next Reproduction

For a timed-out `GET /api/models` request, find the last log line for the same
tenant/source/scope and apply this decision tree.

If the last line is `provider_manager_dependency_start`, the request entered the
provider dependency but did not finish the first provider storage operation.
Check whether a subsequent `provider_storage_ensure_start` is missing because
logging was interrupted or the process terminated.

If the last line is `provider_storage_ensure_start`, the request is stuck in
`ProviderManager.ensure_tenant_provider_storage(...)`.

Likely causes:

- slow `root_path.exists()` on production storage;
- waiting on `.provider_init.lock`;
- source/template copy or directory creation despite the expected directory
  already existing;
- the checked `root_path` is not the same effective provider path that was
  manually inspected.

Next evidence to collect:

- full `root_path`, `route_tenant_id`, `provider_tenant_id`, `source_id`,
  `scope_id`;
- whether `root_path` exists on the same pod/container;
- any `Waiting for concurrent provider initialization` or
  `Failed to initialize provider config` logs.

If the last line is `provider_storage_ensure_done` or
`provider_manager_get_instance_start`, the request finished storage ensure and
is entering `ProviderManager.get_instance(...)`.

If the last line is `provider_manager_instance_cache_miss` and there is no
`provider_manager_instance_lock_acquired`, the request is waiting on the global
`ProviderManager._instances_lock`. This means another request/thread is
currently constructing a ProviderManager instance. Capture a stack dump from the
same process to identify the lock holder.

Recommended command on the pod:

```bash
py-spy dump -p <server_pid>
```

Look for another thread inside:

- `ProviderManager.get_instance`
- `ProviderManager.__init__`
- `_prepare_disk_storage`
- `_init_from_storage`
- `load_provider`
- `_record_mtimes`
- `Path.glob`
- `Path.exists`
- `Path.stat`
- `json.load`

If the last line is `provider_manager_instance_lock_acquired` or
`provider_manager_instance_create_start`, the request acquired the global lock
and is constructing the manager. The next `provider_manager_init_step_start`
line identifies the current constructor phase.

Constructor phase interpretation:

- `step=prepare_disk_storage`: directory creation or chmod is slow.
- `step=init_builtins`: builtin provider registration is unexpectedly slow.
- `step=copy_builtin_defaults`: pydantic deep copy of builtin providers is slow.
- `step=init_from_storage`: provider JSON loading, custom provider globbing, or
  active model JSON reading is slow.
- `step=apply_default_annotations`: capability baseline annotation is slow.
- `step=record_mtimes`: per-file stat/glob snapshot is slow.

If `provider_manager_init_done` appears but
`provider_manager_get_instance_done` does not, inspect for an exception or
process cancellation immediately after construction.

If `provider_manager_get_instance_done` appears and the request still times out,
the next suspect is `list_provider_info()`. Add or enable finer logs around:

- `_refresh_if_stale()`;
- `_detect_changed_builtins()`;
- `_detect_custom_changes()`;
- `_detect_active_model_change()`;
- `asyncio.gather(provider.get_info(), ...)`.

### Differentiating `/api/models` From `/api/models/active`

The frontend `loadModelData()` calls `/models` and `/models/active` together.
Interpret them separately:

- `/api/models` uses `get_provider_manager()` and can block on the manager
  cache/lock/constructor path.
- `/api/models/active` reads `active_model.json` directly and does not use the
  `get_provider_manager()` dependency.

If only `/api/models` times out and `/api/models/active` is fast, focus on
`ProviderManager.get_instance(...)` and manager construction.

If both endpoints time out, look earlier:

- provider storage ensure;
- source-system config middleware;
- tenant workspace bootstrap;
- production storage latency shared by provider and active model files.
