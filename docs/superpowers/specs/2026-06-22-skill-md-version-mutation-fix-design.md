# Skill MD Version Mutation Fix Design

Date: 2026-06-22

## Problem

In the My Skills editor, saving an edited skill file can unexpectedly modify the skill's `SKILL.md` frontmatter by adding or incrementing a `version` field such as `version: 1.0.1`.

The current save path is:

```text
MySkills editor
  -> PUT /market/skills/mine/{skill_name}/files/{file_path}
  -> MarketplaceService.save_skill_file(...)
  -> target.write_text(content)
  -> _bump_skill_version_in_frontmatter(skill_dir)
  -> SKILL.md is rewritten
```

This is surprising because `SKILL.md` is user-authored skill content. Editing a file should not cause the system to mutate unrelated frontmatter fields for version bookkeeping.

## Goals

- Do not add `version` to `SKILL.md` during My Skills edit saves.
- Do not auto-increment an existing `SKILL.md` `version` during My Skills edit saves.
- Preserve system version tracking through metadata so the UI can continue to display a version.
- Keep existing behavior where unchanged content does not update versions or timestamps.
- Maintain backward compatibility with existing skills that already contain `SKILL.md.version`.

## Non-goals

- Do not batch-remove existing `version` fields from user `SKILL.md` files.
- Do not change marketplace publish/version-history rules.
- Do not change the regular `/skills/save` workspace skill editor flow.
- Do not introduce transactional rollback for partial save failures.
- Do not prevent users from manually editing or keeping a `version` field in `SKILL.md`.

## Design Principle

`SKILL.md` is user-owned content. System-managed versions belong in metadata files and manifests, not in the user-authored skill instruction file.

## Current Root Cause

`market/src/market/marketplace/service.py` currently calls `_bump_skill_version_in_frontmatter(skill_dir)` from `save_skill_file()` after writing the edited target file. That helper:

1. Reads `SKILL.md`.
2. Uses the existing frontmatter version or defaults to `1.0.0`.
3. Bumps the patch version.
4. Rewrites the frontmatter, appending `version: <new_version>` when missing.

Because `save_skill_file()` does not limit this to `file_path == "SKILL.md"`, editing files such as `references/foo.md` or `scripts/bar.py` can also rewrite `SKILL.md`.

## Proposed Backend Flow

The My Skills file save flow should become:

```text
MySkills editor
  -> PUT /market/skills/mine/{skill_name}/files/{file_path}
  -> MarketplaceService.save_skill_file(...)
  -> target.write_text(content)
  -> resolve next metadata version
  -> update skill.json version / updated_at
  -> update manifest metadata.version_text / updated_at
  -> do not touch SKILL.md except when it is the file explicitly submitted by the user
```

### Version Resolution

Replace the frontmatter-writing bump call with a read-only metadata version resolver, for example:

```python
def _resolve_next_skill_metadata_version(
    self,
    skill_dir: Path,
    manifest_version: str = "",
) -> str:
    ...
```

The helper must:

- Read possible version sources.
- Return the next patch version.
- Never write `SKILL.md` or any other file.

Version baseline priority:

1. `skill.json.version`
2. workspace manifest metadata `version_text`
3. `SKILL.md.version`, only as a compatibility fallback for old data
4. `1.0.0`

When content has changed, bump the selected baseline via the existing shared patch bump behavior:

```text
1.0.0 -> 1.0.1
1.0.8 -> 1.0.9
```

For non-standard versions, keep the existing `bump_patch()` behavior.

### Save Behavior

`MarketplaceService.save_skill_file()` should keep its existing high-level behavior:

- Validate the target path stays inside the skill directory.
- Reject missing/non-file targets.
- Read existing content and return success without changing metadata if content is unchanged.
- Write the submitted content when it changed.
- Update or create `skill.json`.
- Update workspace manifest metadata.

The key change is replacing:

```python
new_version = self._bump_skill_version_in_frontmatter(skill_dir)
```

with read-only version resolution.

### Metadata Updates

On changed content, update:

- `skill.json.version`
- `skill.json.updated_at`
- workspace manifest `metadata.version_text`
- workspace manifest `metadata.updated_at`
- workspace manifest entry `updated_at`

If `skill.json` does not exist, create it as today, but use the resolved metadata version instead of a version written through `SKILL.md`.

If `skill.json` is malformed, preserve the current tolerant behavior: log a warning and do not destroy the malformed file. The save should not introduce a broader error surface.

## Frontend Adjustment

Update the misleading comment in `console/src/pages/MySkills/index.tsx` near the post-save re-read.

Current meaning:

```ts
// backend may update frontmatter version fields
```

New meaning:

```ts
// re-read file content so the editor reflects the persisted backend state
```

The re-read itself can remain. It is still useful for keeping the editor aligned with the saved content, but it should no longer imply backend-managed frontmatter mutation.

## Backward Compatibility

Existing skills may already have `version` in `SKILL.md`. This fix does not remove it.

Behavior after the fix:

- If `SKILL.md.version` exists, users keep it unchanged unless they edit it themselves.
- If a skill has no metadata version but does have `SKILL.md.version`, the first post-fix save may read that value as the system version baseline and then write the bumped value to `skill.json` and manifest metadata.
- Later saves use `skill.json.version` or manifest `version_text`, so system versioning becomes separated from `SKILL.md.version`.
- If a skill has no version anywhere, the first changed save uses `1.0.0` as the baseline and writes `1.0.1` to metadata only.

## Error Handling

Keep the current external semantics:

- Path traversal or invalid target: return failure.
- Missing target file: return failure.
- Unchanged content: return success without metadata updates.
- File write failure: return failure.
- Malformed `skill.json`: warn and avoid corrupting it.

This design does not add rollback. If the target file write succeeds but later metadata update fails, the current code can already return failure after a partial write. Fixing that would be a separate transactional-save project.

## Tests

Add backend tests around the real service behavior rather than only simulating JSON mutation.

Recommended cases:

1. Saving `SKILL.md` without a version does not add `version:`.
2. Saving a non-`SKILL.md` file leaves `SKILL.md` byte-for-byte unchanged.
3. Existing `SKILL.md.version` is not auto-incremented.
4. If `SKILL.md.version` is the only available baseline, metadata version uses its bumped value.
5. Unchanged content does not bump metadata version.
6. Malformed `skill.json` remains uncorrupted and the save flow keeps the existing tolerant behavior.

The most important regression assertion is that no service-managed save path rewrites `SKILL.md` unless the submitted file path itself is `SKILL.md`, and even then the saved content must match the user-submitted content.

## Implementation Scope

Expected code changes:

- `market/src/market/marketplace/service.py`
  - Add a read-only metadata version resolver.
  - Replace `_bump_skill_version_in_frontmatter()` usage in `save_skill_file()`.
  - Remove or leave unused the frontmatter-writing helper, depending on whether other call sites still need it.
- `console/src/pages/MySkills/index.tsx`
  - Update the misleading post-save comment.
- Market unit tests
  - Add regression coverage for no `SKILL.md` mutation and metadata version updates.

## Acceptance Criteria

- Editing and saving a `SKILL.md` that has no `version` does not add `version`.
- Editing and saving a `SKILL.md` that has `version` does not change that version unless the user-submitted content changed it.
- Editing and saving `references/`, `scripts/`, or any other skill file does not change `SKILL.md`.
- Metadata version still increments on changed saves.
- Unchanged saves do not increment metadata version.
- Existing market publish/version-history behavior remains unchanged.
