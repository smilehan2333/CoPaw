# Market Skill Version Compare skill.json Exclusion Design

Date: 2026-06-22

## Problem

Application marketplace skill version comparison currently compares every collected skill file that is not globally ignored. When `skill.json` differs between two version snapshots, the compare result can show metadata-only changes and count them in changed file and line statistics.

For the marketplace version comparison UI, `skill.json` is system/metadata bookkeeping and should not appear as a user-facing content difference.

## Goal

Exclude `skill.json` from user-facing skill version comparison output in the application marketplace, including both version compare details and automatically generated version history descriptions.

## Non-goals

- Do not change marketplace version content signatures.
- Do not change content unchanged / no-op detection.
- Do not change marketplace version ID derivation.
- Do not change version snapshot storage.
- Do not remove `skill.json` from version detail file trees.
- Do not change MCP version comparison behavior.

## Design

Apply the exclusion locally inside user-facing diff paths in `SkillVersionService`:

- `compare_versions()` for detailed compare output.
- `_compute_quick_diff_stats()` for automatically generated version history descriptions such as `变更 N 个文件，新增 N 行，删除 N 行`.

After collecting the two version file sets with `_collect_skill_files(...)`, remove only the root-level `skill.json` path from both sets before calculating added, deleted, and common files.

The comparison result should then behave as follows:

- A newly added `skill.json` is not reported as an added file.
- A deleted `skill.json` is not reported as a deleted file.
- A changed `skill.json` is not diffed.
- `VersionCompareResult.files` does not include `skill.json`.
- `VersionDiffStats.changed_files`, `added_lines`, and `deleted_lines` do not count `skill.json` changes.
- Other files, including unchanged files such as `SKILL.md`, continue to be returned as before.

This should be implemented as a compare-only rule, not a global ignore rule.

## Files and Components

- `market/src/market/marketplace/version_service.py`
  - Modify `SkillVersionService.compare_versions()` to filter `skill.json` out of `base_files` and `target_files` after collection.
  - Modify `SkillVersionService._compute_quick_diff_stats()` to use the same filtered file sets for automatic version descriptions.
  - Do not add `skill.json` to `_IGNORED_ARTIFACTS`.
  - Do not modify `_calculate_signature()`, `_copy_skill_to_version()`, or `_build_file_tree()`.

- `market/tests/unit/marketplace/test_version_service.py`
  - Add a regression test proving compare output ignores `skill.json` changes while retaining normal comparison output for other files.

## Data Flow

Current flow:

```text
compare_versions()
  -> _collect_skill_files(base_dir)
  -> _collect_skill_files(target_dir)
  -> added/deleted/common set calculations
  -> per-file diff generation
  -> VersionCompareResult
```

New flow:

```text
compare_versions()
  -> _collect_skill_files(base_dir)
  -> discard "skill.json" from base set
  -> _collect_skill_files(target_dir)
  -> discard "skill.json" from target set
  -> added/deleted/common set calculations
  -> per-file diff generation
  -> VersionCompareResult
```

## Error Handling

No new error paths are needed.

If a version directory is missing, existing `ValueError` behavior remains unchanged. If files cannot be read, existing read helpers continue to return empty content or line lists as they do today.

## Compatibility

This change is intentionally narrow:

- Existing version snapshots remain readable.
- Existing snapshot directories are not migrated.
- Existing version signatures are not recalculated.
- Version comparison for all non-`skill.json` files remains unchanged.
- Market version IDs and no-op behavior remain unchanged.

## Tests

Add backend unit tests with two version snapshots where `SKILL.md` is identical and `skill.json` differs.

Compare detail assertions:

- `result.stats.changed_files == 0`
- `result.stats.added_lines == 0`
- `result.stats.deleted_lines == 0`
- `"skill.json" not in [file.path for file in result.files]`
- `"SKILL.md" in [file.path for file in result.files]`
- The `SKILL.md` diff entry has `diff == ""`, `added_lines == 0`, and `deleted_lines == 0`.

Version history description assertions:

- When the only changed file is `skill.json`, the generated second snapshot description is `无变更`.
- When `SKILL.md` and `skill.json` both change, the generated second snapshot description counts only the `SKILL.md` diff.

## Acceptance Criteria

- Version comparison does not display `skill.json`.
- Version comparison statistics do not count `skill.json` changes.
- Automatically generated version history descriptions do not count `skill.json` changes.
- Version signature generation still includes the same files it includes today.
- Version snapshot copying still stores the same files it stores today.
- Version detail file tree behavior remains unchanged.
- Focused backend regression test passes.
