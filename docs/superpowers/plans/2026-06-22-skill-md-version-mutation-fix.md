# Skill MD Version Mutation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop My Skills edit saves from adding or incrementing `version` in user-authored `SKILL.md` while preserving metadata version updates.

**Architecture:** Keep `SKILL.md` user-owned and move save-time version bookkeeping fully into `skill.json` and the workspace manifest. Replace the current frontmatter-writing bump helper with a read-only metadata version resolver used by `MarketplaceService.save_skill_file()`.

**Tech Stack:** Python 3, FastAPI service layer, pytest, TypeScript/React frontend comment-only adjustment.

---

## File Structure

- Modify: `market/src/market/marketplace/service.py`
  - Replace `_bump_skill_version_in_frontmatter()` with `_resolve_next_skill_metadata_version()`.
  - Update `save_skill_file()` to call the read-only resolver and update metadata only.
  - Update comments/docstrings that currently claim `SKILL.md` frontmatter is bumped.
- Modify: `market/tests/unit/marketplace/test_service.py`
  - Add service-level regression tests for no `SKILL.md` mutation, metadata version bumping, unchanged-content no-op, and malformed `skill.json` tolerance.
- Modify: `console/src/pages/MySkills/index.tsx`
  - Update the post-save re-read comment so it no longer says the backend may update frontmatter version fields.

---

### Task 1: Add backend regression tests and implement metadata-only version bumping

**Files:**
- Modify: `market/tests/unit/marketplace/test_service.py`
- Modify: `market/src/market/marketplace/service.py`

- [ ] **Step 1: Add service-level regression tests**

Append the following helper and tests to `market/tests/unit/marketplace/test_service.py` after the existing imports/helper section or near the other `get_my_skills` service tests. The helper uses the same workspace paths as the production service.

```python
def _create_user_skill_for_save(
    tmp_path,
    *,
    skill_name="demo_skill",
    skill_md="---\nname: demo_skill\ndescription: Demo skill\n---\n\nBody.\n",
    files=None,
    skill_json=None,
    manifest_version_text="",
    user_id="user-1",
    source_id="source-1",
    agent_id="default",
):
    from market.marketplace.fs import (
        get_user_skill_manifest_path,
        get_user_skills_dir,
    )

    skills_dir = get_user_skills_dir(
        tmp_path / "swe",
        user_id,
        agent_id,
        source_id,
    )
    skill_dir = skills_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    for relative_path, content in (files or {}).items():
        target = skill_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    if skill_json is not None:
        if isinstance(skill_json, str):
            skill_json_content = skill_json
        else:
            skill_json_content = json.dumps(
                skill_json,
                ensure_ascii=False,
                indent=2,
            )
        (skill_dir / "skill.json").write_text(
            skill_json_content,
            encoding="utf-8",
        )

    metadata = {
        "name": skill_name,
        "description": "Demo skill",
    }
    if manifest_version_text:
        metadata["version_text"] = manifest_version_text

    manifest_path = get_user_skill_manifest_path(
        tmp_path / "swe",
        user_id,
        agent_id,
        source_id,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "workspace-skill-manifest.v1",
                "version": 1,
                "skills": {
                    skill_name: {
                        "source": "customized",
                        "metadata": metadata,
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return skill_dir, manifest_path


def test_save_skill_file_does_not_add_version_to_skill_md(tmp_path):
    svc = _make_service(tmp_path)
    skill_dir, manifest_path = _create_user_skill_for_save(tmp_path)

    submitted_content = (
        "---\n"
        "name: demo_skill\n"
        "description: Changed demo skill\n"
        "---\n\n"
        "Changed body.\n"
    )

    ok = svc.save_skill_file(
        "user-1",
        "demo_skill",
        "SKILL.md",
        submitted_content,
        user_name="User One",
        source_id="source-1",
    )

    assert ok is True
    saved_skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert saved_skill_md == submitted_content
    assert "version:" not in saved_skill_md

    skill_json = json.loads((skill_dir / "skill.json").read_text(encoding="utf-8"))
    assert skill_json["version"] == "1.0.1"
    assert "updated_at" in skill_json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = manifest["skills"]["demo_skill"]["metadata"]
    assert metadata["version_text"] == "1.0.1"
    assert "updated_at" in metadata
    assert "updated_at" in manifest["skills"]["demo_skill"]


def test_save_skill_file_does_not_touch_skill_md_when_other_file_changes(tmp_path):
    svc = _make_service(tmp_path)
    original_skill_md = (
        "---\n"
        "name: demo_skill\n"
        "description: Demo skill\n"
        "---\n\n"
        "Body.\n"
    )
    skill_dir, manifest_path = _create_user_skill_for_save(
        tmp_path,
        skill_md=original_skill_md,
        files={"references/foo.md": "old reference\n"},
        skill_json={
            "name": "demo_skill",
            "version": "2.0.0",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        manifest_version_text="1.9.9",
    )

    ok = svc.save_skill_file(
        "user-1",
        "demo_skill",
        "references/foo.md",
        "new reference\n",
        user_name="User One",
        source_id="source-1",
    )

    assert ok is True
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == original_skill_md
    assert (skill_dir / "references" / "foo.md").read_text(encoding="utf-8") == "new reference\n"

    skill_json = json.loads((skill_dir / "skill.json").read_text(encoding="utf-8"))
    assert skill_json["version"] == "2.0.1"
    assert skill_json["created_at"] == "2026-01-01T00:00:00+00:00"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["skills"]["demo_skill"]["metadata"]["version_text"] == "2.0.1"


def test_save_skill_file_preserves_existing_skill_md_version_and_uses_it_as_fallback(tmp_path):
    svc = _make_service(tmp_path)
    original_skill_md = (
        "---\n"
        "name: demo_skill\n"
        "description: Demo skill\n"
        "version: 1.2.3\n"
        "---\n\n"
        "Body.\n"
    )
    skill_dir, manifest_path = _create_user_skill_for_save(
        tmp_path,
        skill_md=original_skill_md,
        files={"scripts/run.py": "print('old')\n"},
    )

    ok = svc.save_skill_file(
        "user-1",
        "demo_skill",
        "scripts/run.py",
        "print('new')\n",
        user_name="User One",
        source_id="source-1",
    )

    assert ok is True
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == original_skill_md

    skill_json = json.loads((skill_dir / "skill.json").read_text(encoding="utf-8"))
    assert skill_json["version"] == "1.2.4"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["skills"]["demo_skill"]["metadata"]["version_text"] == "1.2.4"


def test_save_skill_file_same_content_does_not_bump_metadata_version(tmp_path):
    svc = _make_service(tmp_path)
    skill_md = (
        "---\n"
        "name: demo_skill\n"
        "description: Demo skill\n"
        "---\n\n"
        "Body.\n"
    )
    skill_dir, manifest_path = _create_user_skill_for_save(
        tmp_path,
        skill_md=skill_md,
        skill_json={"name": "demo_skill", "version": "3.0.0"},
        manifest_version_text="3.0.0",
    )
    skill_json_before = (skill_dir / "skill.json").read_text(encoding="utf-8")
    manifest_before = manifest_path.read_text(encoding="utf-8")

    ok = svc.save_skill_file(
        "user-1",
        "demo_skill",
        "SKILL.md",
        skill_md,
        user_name="User One",
        source_id="source-1",
    )

    assert ok is True
    assert (skill_dir / "skill.json").read_text(encoding="utf-8") == skill_json_before
    assert manifest_path.read_text(encoding="utf-8") == manifest_before


def test_save_skill_file_preserves_malformed_skill_json(tmp_path):
    svc = _make_service(tmp_path)
    skill_dir, manifest_path = _create_user_skill_for_save(
        tmp_path,
        skill_json="not a valid json",
        manifest_version_text="4.0.0",
    )
    submitted_content = (
        "---\n"
        "name: demo_skill\n"
        "description: Demo skill changed\n"
        "---\n\n"
        "Changed body.\n"
    )

    ok = svc.save_skill_file(
        "user-1",
        "demo_skill",
        "SKILL.md",
        submitted_content,
        user_name="User One",
        source_id="source-1",
    )

    assert ok is True
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == submitted_content
    assert (skill_dir / "skill.json").read_text(encoding="utf-8") == "not a valid json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["skills"]["demo_skill"]["metadata"]["version_text"] == "4.0.1"
```

- [ ] **Step 2: Run tests to verify the regression is exposed**

Run from the repository root:

```bash
PYTHONPATH=market/src python -m pytest market/tests/unit/marketplace/test_service.py -k "save_skill_file" -q
```

Expected before the implementation:

- At least these tests fail:
  - `test_save_skill_file_does_not_add_version_to_skill_md`
  - `test_save_skill_file_does_not_touch_skill_md_when_other_file_changes`
  - `test_save_skill_file_preserves_existing_skill_md_version_and_uses_it_as_fallback`
- Failure reason shows `SKILL.md` contains an added or changed `version:` line.

- [ ] **Step 3: Replace frontmatter-writing version bump with read-only metadata resolver**

In `market/src/market/marketplace/service.py`, replace the entire `_bump_skill_version_in_frontmatter()` method with this method in the same class location before `_bump_skill_version_in_manifest()`:

```python
    def _resolve_next_skill_metadata_version(
        self,
        skill_dir: Path,
        manifest_version: str = "",
    ) -> str:
        """Return the next system metadata version without rewriting SKILL.md."""
        base_version = ""
        skill_json_path = skill_dir / "skill.json"
        if skill_json_path.exists():
            try:
                skill_data = json.loads(
                    skill_json_path.read_text(encoding="utf-8"),
                )
                raw_version = skill_data.get("version")
                if raw_version not in (None, ""):
                    base_version = str(raw_version).strip()
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Failed to read skill.json version for %s: %s",
                    skill_json_path,
                    e,
                )

        if not base_version and manifest_version:
            base_version = str(manifest_version).strip()

        if not base_version:
            skill_md_path = skill_dir / "SKILL.md"
            try:
                md_content = skill_md_path.read_text(encoding="utf-8")
                base_version = _extract_version_from_frontmatter(md_content)
            except OSError:
                base_version = ""

        return _bump_patch(base_version or "1.0.0")
```

- [ ] **Step 4: Update `save_skill_file()` to use metadata-only versioning**

In `market/src/market/marketplace/service.py`, update the `save_skill_file()` docstring from:

```python
        """保存技能文件内容，自动创建 skill.json（如不存在）.

        如果新内容与现有内容一致，则跳过写入和版本更新。
        只有内容发生变化时，才 bump SKILL.md frontmatter 中的 version 字段
        和 manifest 的 version_text，确保版本号与实际编辑同步。
        """
```

to:

```python
        """保存技能文件内容，自动创建 skill.json（如不存在）.

        如果新内容与现有内容一致，则跳过写入和版本更新。
        只有内容发生变化时，才 bump 系统元数据版本；不会为了版本管理
        改写用户维护的 SKILL.md frontmatter。
        """
```

Then replace this block inside the `try:` body:

```python
            current_time = datetime.now(timezone.utc).isoformat()

            # bump SKILL.md frontmatter 中的 version 字段
            new_version = self._bump_skill_version_in_frontmatter(skill_dir)
```

with:

```python
            current_time = datetime.now(timezone.utc).isoformat()
            manifest = read_user_skill_manifest(
                self.swe_root,
                user_id,
                agent_id,
                source_id,
            )
            manifest_entry = manifest.get("skills", {}).get(skill_name) or {}
            manifest_metadata = manifest_entry.get("metadata") or {}
            manifest_version = str(
                manifest_metadata.get("version_text", "") or "",
            )

            new_version = self._resolve_next_skill_metadata_version(
                skill_dir,
                manifest_version,
            )
```

Finally, in the `else:` branch that creates `base_skill_data`, add `updated_at` so new metadata files also record the edit time. Replace:

```python
                base_skill_data = {
                    "name": skill_name,
                    "description": "",
                    "version": new_version,
                    "creator_id": user_id,
                    "creator_name": user_name or "",
                    "created_at": current_time,
                    "source": "customized",
                }
```

with:

```python
                base_skill_data = {
                    "name": skill_name,
                    "description": "",
                    "version": new_version,
                    "creator_id": user_id,
                    "creator_name": user_name or "",
                    "created_at": current_time,
                    "updated_at": current_time,
                    "source": "customized",
                }
```

- [ ] **Step 5: Run targeted backend tests**

Run from the repository root:

```bash
PYTHONPATH=market/src python -m pytest market/tests/unit/marketplace/test_service.py -k "save_skill_file" -q
```

Expected after the implementation:

```text
5 passed
```

The exact number can be higher if existing tests also match `save_skill_file`, but every selected test must pass.

- [ ] **Step 6: Run broader market service tests**

Run:

```bash
PYTHONPATH=market/src python -m pytest market/tests/unit/marketplace/test_service.py -q
```

Expected:

```text
... passed
```

No failures should mention `SKILL.md`, `version_text`, `skill.json`, or market publish version regressions.

- [ ] **Step 7: Commit backend fix and tests**

Run:

```bash
git add market/src/market/marketplace/service.py market/tests/unit/marketplace/test_service.py
git commit -m "fix(market): stop mutating skill md versions on save" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Update the My Skills frontend comment

**Files:**
- Modify: `console/src/pages/MySkills/index.tsx`

- [ ] **Step 1: Update the misleading comment**

In `console/src/pages/MySkills/index.tsx`, replace this comment:

```ts
      // 重新读取文件内容（后端可能更新了 frontmatter 中的 version 等字段）
```

with:

```ts
      // 重新读取文件内容，确保展示与后端保存结果一致
```

Do not change the `readSkillFile(...)` call or any runtime behavior in this task.

- [ ] **Step 2: Run frontend type check if available**

Run:

```bash
cd console && pnpm type-check
```

Expected:

```text
No type errors
```

If `pnpm type-check` is not defined in `console/package.json`, run:

```bash
cd console && pnpm tsc --noEmit
```

Expected:

```text
No type errors
```

- [ ] **Step 3: Commit frontend comment update**

Run from the repository root:

```bash
git add console/src/pages/MySkills/index.tsx
git commit -m "chore: clarify my skills save refresh comment" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Final verification

**Files:**
- Verify: `market/src/market/marketplace/service.py`
- Verify: `market/tests/unit/marketplace/test_service.py`
- Verify: `console/src/pages/MySkills/index.tsx`

- [ ] **Step 1: Run the targeted regression tests again**

Run:

```bash
PYTHONPATH=market/src python -m pytest market/tests/unit/marketplace/test_service.py -k "save_skill_file" -q
```

Expected:

```text
5 passed
```

The exact selected count can be higher if other matching tests exist, but there must be no failures.

- [ ] **Step 2: Check for removed frontmatter mutation call**

Run:

```bash
python - <<'PY'
from pathlib import Path
text = Path('market/src/market/marketplace/service.py').read_text(encoding='utf-8')
assert '_bump_skill_version_in_frontmatter' not in text
assert '_resolve_next_skill_metadata_version' in text
print('frontmatter mutation helper removed')
PY
```

Expected:

```text
frontmatter mutation helper removed
```

- [ ] **Step 3: Inspect working tree**

Run:

```bash
git status --short
```

Expected:

```text

```

The output should be empty because Tasks 1 and 2 committed their changes. If the output lists generated caches such as `.pytest_cache`, remove only generated artifacts that were created by the test run and are not tracked project files.

- [ ] **Step 4: Summarize the result**

Report these facts:

- `SKILL.md` is no longer modified for metadata version bumps.
- Metadata versions still increment in `skill.json` and the workspace manifest.
- Targeted backend tests pass.
- Frontend runtime behavior is unchanged except for the corrected comment.

## Self-Review Notes

- Spec coverage: Tasks cover backend flow, version source priority, no `SKILL.md` mutation, unchanged-content no-op, malformed `skill.json`, and the frontend comment adjustment.
- Placeholder scan: No incomplete placeholders are intentionally left in this plan.
- Type consistency: The plan consistently uses `MarketplaceService.save_skill_file()`, `_resolve_next_skill_metadata_version()`, `skill.json.version`, and manifest `metadata.version_text`.
