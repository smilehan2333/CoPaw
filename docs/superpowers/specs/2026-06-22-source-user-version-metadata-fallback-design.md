# Source User Version Metadata Fallback Design

Date: 2026-06-22

## Problem

After the My Skills save flow stopped mutating `SKILL.md.version`, syncing a skill from My Skills to the application marketplace can lose the uploader's source version information. The marketplace version snapshot supports `source_user_version`, but the publish path still partially depends on `SKILL.md.version` as a fallback.

The current relevant flow is:

```text
MySkills list item
  -> skill.version
  -> PublishModal initialData.version
  -> PublishSkillRequest.source_user_version
  -> MarketplaceService.publish_skill(...)
  -> SkillVersion.source_user_version
```

If `skill.version` is missing or inaccurate and `SKILL.md` no longer contains a version, `publish_skill()` has no reliable fallback and stores an empty `source_user_version`.

## Goals

- Preserve uploader source version information when syncing My Skills to the marketplace.
- Keep `SKILL.md` user-owned and never reintroduce automatic `SKILL.md.version` writes.
- Make My Skills list version display use the same metadata-backed version sources as publish.
- Keep marketplace `MarketItem.version` / snapshot `version_id` generation independent from user workspace versions.
- Keep old data compatible when a version exists only in `SKILL.md`.

## Non-goals

- Do not restore automatic `SKILL.md.version` insertion or bumping.
- Do not change marketplace version-id derivation rules.
- Do not batch-migrate or clean historical `SKILL.md.version` fields.
- Do not change version-history display rules such as hiding duplicate `source_user_version == version_id`.
- Do not block publish when no real source user version can be found.

## Design Principle

System-managed user skill versions should be read from metadata first. `SKILL.md.version` is only a compatibility fallback for old data, not a primary system version store.

There are two consumers with slightly different fallback behavior:

- My Skills list display may show default `1.0.0` when no version source exists, preserving current UI behavior.
- Marketplace snapshot `source_user_version` should stay empty when no real version source exists, avoiding fabricated uploader-version history.

## Proposed Backend Helper

Add a read-only helper in `market/src/market/marketplace/service.py`, for example:

```python
def _resolve_user_skill_version(
    self,
    *,
    skill_dir: Path,
    manifest_metadata: dict[str, Any] | None = None,
    skill_json: dict[str, Any] | None = None,
) -> str:
    ...
```

The helper should:

- Read only; never write `SKILL.md`, `skill.json`, or manifest files.
- Return the first non-empty normalized string version it finds.
- Swallow read/parse errors and continue fallback.
- Be safe for both user workspace skill directories and copied marketplace skill directories.

Version source priority:

1. `manifest_metadata.version_text`
2. request-provided `skill_json.version`
3. `<skill_dir>/skill.json.version`
4. `SKILL.md.version`
5. empty string

`skill_json` should be treated as optional input to avoid re-reading data already supplied by the publish request. If `skill_json` is malformed or not a dict, ignore it.

## My Skills List Flow

Current list resolution effectively does:

```text
manifest metadata.version_text
-> SKILL.md.version
-> default 1.0.0
```

Change it to:

```text
manifest metadata.version_text
-> skill_dir/skill.json.version
-> SKILL.md.version
-> default 1.0.0
```

Implementation options:

- Update `_resolve_skill_display_fields(...)` to call the new helper.
- Or keep `_resolve_skill_display_fields(...)` for name/description and resolve version in `_build_my_skill_item(...)`.

Preferred implementation: keep name/description frontmatter logic unchanged, and use `_resolve_user_skill_version(...)` for version resolution so publish and list behavior share the same source priority.

The returned `MySkillItem.version` should remain `version or "1.0.0"` for display compatibility.

## Publish Flow

Current publish fallback does:

```text
req.source_user_version
-> copied skill_dir/SKILL.md.version
```

Change it to:

```text
req.source_user_version
-> req.skill_json.version
-> source workspace manifest metadata.version_text
-> copied skill_dir/skill.json.version
-> copied skill_dir/SKILL.md.version
```

Detailed behavior:

1. If `req.source_user_version` is non-empty, trust it.
2. Otherwise, if `req.skill_json.version` exists, use it.
3. Otherwise, if `req.skill_name` is present, read the source user's workspace manifest with:
   - `self.swe_root`
   - `req.creator_id`
   - `req.agent_id`
   - `source_id`

   Then look up `manifest["skills"][req.skill_name]["metadata"]["version_text"]`.
4. Otherwise, or if manifest has no version, use copied `skill_dir/skill.json.version`.
5. Finally, read copied `skill_dir/SKILL.md.version` only for old-data compatibility.
6. If all are empty, keep `source_user_version` as `""`.

This keeps `source_user_version` independent from marketplace `version_id`. The marketplace snapshot still derives its own `version_id` using existing `SkillVersionService` logic.

## Error Handling

Publishing should not fail only because the source user version cannot be resolved.

Fallback behavior:

- Missing workspace manifest: continue.
- Missing manifest entry: continue.
- Malformed or missing `skill.json`: continue.
- Missing or malformed `SKILL.md` frontmatter: continue.
- Non-dict request `skill_json`: ignore it.

Logging should be conservative. Existing helpers that warn on malformed JSON can continue warning, but this fix should not add noisy logs for common absence cases such as missing `skill.json`.

## Backward Compatibility

- Skills saved after the metadata-only version fix will usually have `manifest metadata.version_text` and/or `skill.json.version`; these become the preferred source user version.
- Skills that only have old `SKILL.md.version` still publish that value as `source_user_version`.
- Skills with no real version source do not fabricate `source_user_version`.
- My Skills list still displays `1.0.0` when no version source exists, preserving current UI behavior.

## Frontend Impact

No frontend behavior change is required for the core fix.

Existing frontend behavior already passes:

```ts
source_user_version: initialData?.version
```

The backend list fix makes `initialData.version` more accurate. The backend publish fallback protects against older clients or incomplete list data.

A frontend comment-only update is acceptable if an existing comment becomes misleading, but runtime behavior should not change.

## Tests

Add backend tests around real service behavior.

Recommended cases:

1. `get_my_skills()` falls back to `skill.json.version`:
   - manifest has no `version_text`
   - `SKILL.md` has no version
   - skill directory `skill.json.version` is `2.3.4`
   - returned item has `version == "2.3.4"`

2. `publish_skill()` uses `req.skill_json.version`:
   - request has no `source_user_version`
   - `skill_json={"version": "2.0.1"}`
   - `SKILL.md` has no version
   - created snapshot has `source_user_version == "2.0.1"`

3. `publish_skill()` uses workspace manifest `version_text`:
   - request has `skill_name`
   - source workspace manifest metadata has `version_text == "3.0.1"`
   - request has no `source_user_version`
   - request `skill_json` has no version
   - `SKILL.md` has no version
   - created snapshot has `source_user_version == "3.0.1"`

4. `publish_skill()` preserves old `SKILL.md.version` fallback:
   - no `source_user_version`
   - no `skill_json.version`
   - no manifest `version_text`
   - copied `SKILL.md.version == "1.2.3"`
   - created snapshot has `source_user_version == "1.2.3"`

5. No real version source does not fabricate snapshot version:
   - all sources empty
   - created snapshot has `source_user_version == ""`
   - My Skills list may still display `1.0.0`

## Acceptance Criteria

- Syncing a My Skills item with metadata `version_text` records that value in marketplace snapshot `source_user_version`.
- Syncing a My Skills item whose version is only in `skill.json.version` records that value in snapshot `source_user_version`.
- Syncing old skills whose version is only in `SKILL.md.version` continues to record that value.
- Syncing a skill with no true source version leaves snapshot `source_user_version` empty.
- My Skills list version display uses `skill.json.version` when manifest `version_text` is absent.
- No code path writes or increments `SKILL.md.version` for this fix.
- Existing market version-id behavior remains unchanged.
