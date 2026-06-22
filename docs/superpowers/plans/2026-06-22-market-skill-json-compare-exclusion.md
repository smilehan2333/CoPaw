# Market Skill JSON Compare Exclusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide `skill.json` from application marketplace skill version comparison results and generated version history descriptions without changing market version generation behavior.

**Architecture:** Keep the exclusion local to user-facing diff paths in `SkillVersionService` by filtering root-level `skill.json` out of the two file sets after collection. Apply the same filtered sets in `compare_versions()` and `_compute_quick_diff_stats()`. Do not modify global ignored artifacts, snapshot copying, signatures, or version detail file trees.

**Tech Stack:** Python 3, pytest, existing `SkillVersionService` and version model classes.

---

## File Structure

- Modify: `market/src/market/marketplace/version_service.py`
  - Add a small display-diff-only constant for excluded file paths.
  - Filter `skill.json` out of `compare_versions()` file sets before diff calculations.
  - Filter `skill.json` out of `_compute_quick_diff_stats()` so generated version history descriptions match compare output.
- Modify: `market/tests/unit/marketplace/test_version_service.py`
  - Add one regression test for `skill.json`-only changes being hidden from compare output.
  - Add one regression test for `skill.json`-only changes generating `无变更` as the version history description.

---

### Task 1: Add regression test for compare-only `skill.json` exclusion

**Files:**
- Test: `market/tests/unit/marketplace/test_version_service.py`

- [ ] **Step 1: Write the failing test**

Append this test near the existing compare-version tests in `market/tests/unit/marketplace/test_version_service.py`:

```python
def test_compare_versions_ignores_root_skill_json_changes(tmp_path):
    """版本比对展示不应包含根目录 skill.json 的元数据差异."""
    svc = _make_version_service(tmp_path)
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md="# Same Skill\n",
        skill_json={"name": "same", "version": "1.0.0"},
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v1",
        creator="user",
        current_market_version="1.0.0",
    )

    (skill_dir / "skill.json").write_text(
        json.dumps(
            {"name": "same", "version": "1.0.1", "updated_at": "now"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v2",
        creator="user",
        current_market_version="1.0.1",
    )

    result = svc.compare_versions("src_a", "item_1", "1.0.0", "1.0.1")

    paths = [file.path for file in result.files]
    assert "skill.json" not in paths
    assert "SKILL.md" in paths
    assert result.stats.changed_files == 0
    assert result.stats.added_lines == 0
    assert result.stats.deleted_lines == 0

    skill_md = next(file for file in result.files if file.path == "SKILL.md")
    assert skill_md.diff == ""
    assert skill_md.added_lines == 0
    assert skill_md.deleted_lines == 0
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
PYTHONPATH=market/src python -m pytest market/tests/unit/marketplace/test_version_service.py::test_compare_versions_ignores_root_skill_json_changes -q
```

Expected before implementation:

```text
FAILED
```

The failure should show that `skill.json` appears in `paths` or that change stats count the metadata difference.

---

### Task 2: Filter `skill.json` only in version compare output

**Files:**
- Modify: `market/src/market/marketplace/version_service.py`

- [ ] **Step 1: Add a compare-only excluded path constant**

Near `_IGNORED_ARTIFACTS`, add:

```python
# 仅用于版本比对展示；不要用于签名、快照复制或版本详情文件树。
_COMPARE_EXCLUDED_FILES = {"skill.json"}
```

- [ ] **Step 2: Filter collected file sets in `compare_versions()`**

Replace:

```python
        base_files = self._collect_skill_files(base_dir)
        target_files = self._collect_skill_files(target_dir)
```

with:

```python
        base_files = self._collect_skill_files(base_dir) - _COMPARE_EXCLUDED_FILES
        target_files = self._collect_skill_files(target_dir) - _COMPARE_EXCLUDED_FILES
```

Do not modify `_IGNORED_ARTIFACTS`, `_calculate_signature()`, `_copy_skill_to_version()`, or `_build_file_tree()`.

- [ ] **Step 3: Run the focused test and verify it passes**

Run:

```bash
PYTHONPATH=market/src python -m pytest market/tests/unit/marketplace/test_version_service.py::test_compare_versions_ignores_root_skill_json_changes -q
```

Expected:

```text
1 passed
```

---

### Task 3: Exclude `skill.json` from generated version history descriptions

**Files:**
- Test: `market/tests/unit/marketplace/test_version_service.py`
- Modify: `market/src/market/marketplace/version_service.py`

- [ ] **Step 1: Write the failing description test**

Append this test near `test_compare_versions_ignores_root_skill_json_changes` in `market/tests/unit/marketplace/test_version_service.py`:

```python
def test_generated_version_description_ignores_root_skill_json_changes(tmp_path):
    """版本历史自动说明不应统计根目录 skill.json 的元数据差异."""
    svc = _make_version_service(tmp_path)
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md="# Same Skill\n",
        skill_json={"name": "same", "version": "1.0.0"},
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        creator="user",
        current_market_version="1.0.0",
    )

    (skill_dir / "skill.json").write_text(
        json.dumps(
            {"name": "same", "version": "1.0.1", "updated_at": "now"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    version = svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        creator="user",
        current_market_version="1.0.1",
    )

    assert version.description == "无变更"
```

- [ ] **Step 2: Run the focused description test and verify it fails**

Run:

```bash
PYTHONPATH=market/src python -m pytest market/tests/unit/marketplace/test_version_service.py::test_generated_version_description_ignores_root_skill_json_changes -q
```

Expected before implementation:

```text
FAILED
```

The failure should show the generated description still counts `skill.json`, such as `变更 1 个文件，新增 ...，删除 ...`.

- [ ] **Step 3: Filter collected file sets in `_compute_quick_diff_stats()`**

In `market/src/market/marketplace/version_service.py`, replace:

```python
        base_files = self._collect_skill_files(base_dir)
        target_files = self._collect_skill_files(target_dir)
```

inside `_compute_quick_diff_stats()` with:

```python
        base_files = self._collect_skill_files(base_dir) - _COMPARE_EXCLUDED_FILES
        target_files = self._collect_skill_files(target_dir) - _COMPARE_EXCLUDED_FILES
```

Do not change `_calculate_signature()`, `_copy_skill_to_version()`, or `_build_file_tree()`.

- [ ] **Step 4: Run the focused description test and verify it passes**

Run:

```bash
PYTHONPATH=market/src python -m pytest market/tests/unit/marketplace/test_version_service.py::test_generated_version_description_ignores_root_skill_json_changes -q
```

Expected:

```text
1 passed
```

---

### Task 4: Run focused regression suite

**Files:**
- Verify: `market/src/market/marketplace/version_service.py`
- Verify: `market/tests/unit/marketplace/test_version_service.py`

- [ ] **Step 1: Run all version service unit tests**

Run:

```bash
PYTHONPATH=market/src python -m pytest market/tests/unit/marketplace/test_version_service.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Report results**

Report:

- `skill.json` is excluded only from `SkillVersionService.compare_versions()` output.
- Market signatures, snapshot copy, version detail file trees, and MCP compare behavior were not changed.
- Focused tests passed or provide the exact failing output.

## Self-Review Notes

- Spec coverage: Tasks cover compare output exclusion, stats exclusion, non-goals around signatures/snapshots/detail trees, and focused tests.
- Placeholder scan: No TBD/TODO placeholders.
- Type consistency: Plan uses existing `SkillVersionService.compare_versions()`, `VersionCompareResult.files`, and `VersionDiffStats` fields.
