# -*- coding: utf-8 -*-
"""版本管理服务单元测试."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone

from market.marketplace.version_service import SkillVersionService
from market.marketplace.version_models import (
    SkillVersion,
    VersionsManifest,
    VersionCompareResult,
)


def _make_version_service(tmp_path: Path) -> SkillVersionService:
    """创建版本服务实例."""
    return SkillVersionService(tmp_path / "market")


def _create_skill_dir(
    tmp_path: Path,
    source_id: str,
    item_id: str,
    skill_md: str = "",
    skill_json: dict = None,
) -> Path:
    """创建技能目录."""
    skill_dir = tmp_path / "market" / source_id / "skills" / item_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    if skill_md:
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    if skill_json:
        (skill_dir / "skill.json").write_text(
            json.dumps(skill_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return skill_dir


def test_create_version_snapshot_creates_directory(tmp_path):
    """测试创建版本快照生成目录."""
    svc = _make_version_service(tmp_path)
    skill_md = """---
name: "测试技能"
version: "1.0.0"
description: "测试技能描述"
---
# 测试技能
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md,
        skill_json={"name": "测试技能"},
    )

    version = svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="初始版本",
        creator="测试用户",
    )

    assert version.version_id == "1.0.0"
    assert version.is_current
    assert version.is_initial
    assert version.created_by == "测试用户"

    # 验证版本目录存在
    version_dir = (
        tmp_path / "market" / "src_a" / "skill_versions" / "item_1" / "1.0.0"
    )
    assert version_dir.exists()
    assert (version_dir / "SKILL.md").exists()


def test_create_version_snapshot_updates_manifest(tmp_path):
    """测试创建版本快照更新版本清单."""
    svc = _make_version_service(tmp_path)
    skill_md = """---
name: "测试技能"
version: "1.0.0"
---
# 测试技能
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md,
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="初始版本",
        creator="测试用户",
    )

    # 验证 versions.json 存在
    manifest_path = (
        tmp_path
        / "market"
        / "src_a"
        / "skill_versions"
        / "item_1"
        / "versions.json"
    )
    assert manifest_path.exists()

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(data["versions"]) == 1
    assert data["versions"][0]["version_id"] == "1.0.0"


def test_create_second_version_updates_current_flag(tmp_path):
    """测试创建第二个版本更新 is_current 标识."""
    svc = _make_version_service(tmp_path)

    # 创建第一个版本
    skill_md_v1 = """---
name: "测试技能"
version: "1.0.0"
---
# 测试技能 v1
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md_v1,
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="初始版本",
        creator="测试用户",
    )

    # 更新 SKILL.md 并创建第二个版本
    skill_md_v2 = """---
name: "测试技能"
version: "1.0.1"
---
# 测试技能 v2
"""
    (skill_dir / "SKILL.md").write_text(skill_md_v2, encoding="utf-8")

    version2 = svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="更新版本",
        creator="测试用户",
    )

    assert version2.version_id == "1.0.1"
    assert version2.is_current
    assert not version2.is_initial

    # 验证第一个版本的 is_current 已更新
    manifest = svc._load_versions_manifest("src_a", "item_1")
    v1 = next(v for v in manifest.versions if v.version_id == "1.0.0")
    assert not v1.is_current


def test_list_versions_returns_sorted_list(tmp_path):
    """测试获取版本列表按时间倒序排列."""
    svc = _make_version_service(tmp_path)

    skill_md_v1 = """---
name: "测试技能"
version: "1.0.0"
---
# v1
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md_v1,
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v1",
        creator="user",
    )

    # 创建第二个版本
    skill_md_v2 = """---
name: "测试技能"
version: "1.0.1"
---
# v2
"""
    (skill_dir / "SKILL.md").write_text(skill_md_v2, encoding="utf-8")
    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v2",
        creator="user",
    )

    versions = svc.list_versions("src_a", "item_1")

    assert len(versions["versions"]) == 2
    # 最新版本在前
    assert versions["versions"][0]["version_id"] == "1.0.1"
    assert versions["versions"][1]["version_id"] == "1.0.0"


def test_switch_version_copies_files(tmp_path):
    """测试切换版本复制文件."""
    svc = _make_version_service(tmp_path)

    skill_md_v1 = """---
name: "测试技能"
version: "1.0.0"
---
# v1 content
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md_v1,
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v1",
        creator="user",
    )

    # 创建第二个版本
    skill_md_v2 = """---
name: "测试技能"
version: "1.0.1"
---
# v2 content
"""
    (skill_dir / "SKILL.md").write_text(skill_md_v2, encoding="utf-8")
    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v2",
        creator="user",
    )

    # 切换回 v1
    result = svc.switch_version(
        source_id="src_a",
        item_id="item_1",
        target_version_id="1.0.0",
        current_skill_dir=skill_dir,
    )

    assert result.success
    assert result.previous_version == "1.0.1"
    assert result.current_version == "1.0.0"

    # 验证文件已切换
    content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "v1 content" in content

    # 验证 is_current 标识已更新
    manifest = svc._load_versions_manifest("src_a", "item_1")
    v1 = next(v for v in manifest.versions if v.version_id == "1.0.0")
    assert v1.is_current


def test_compare_versions_computes_diff(tmp_path):
    """测试版本比对计算差异."""
    svc = _make_version_service(tmp_path)

    skill_md_v1 = """---
name: "测试技能"
version: "1.0.0"
---
# v1

line 1
line 2
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md_v1,
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v1",
        creator="user",
    )

    # 创建第二个版本（有差异）
    skill_md_v2 = """---
name: "测试技能"
version: "1.0.1"
---
# v1

line 1
line 2 modified
line 3 added
"""
    (skill_dir / "SKILL.md").write_text(skill_md_v2, encoding="utf-8")
    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v2",
        creator="user",
    )

    result = svc.compare_versions(
        source_id="src_a",
        item_id="item_1",
        base_version_id="1.0.0",
        target_version_id="1.0.1",
    )

    assert result.base_version == "1.0.0"
    assert result.target_version == "1.0.1"
    assert result.stats.changed_files >= 1
    assert result.stats.added_lines >= 1
    assert result.stats.deleted_lines >= 1


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


def test_generated_version_description_ignores_root_skill_json_changes(
    tmp_path,
):
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


def test_delete_version_removes_directory(tmp_path):
    """测试删除版本移除目录."""
    svc = _make_version_service(tmp_path)

    skill_md_v1 = """---
name: "测试技能"
version: "1.0.0"
---
# v1
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md_v1,
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v1",
        creator="user",
    )

    # 创建第二个版本
    skill_md_v2 = """---
name: "测试技能"
version: "1.0.1"
---
# v2
"""
    (skill_dir / "SKILL.md").write_text(skill_md_v2, encoding="utf-8")
    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v2",
        creator="user",
    )

    # 删除 v1（非当前、非初始）
    # 先将 v1 设为非初始（模拟有更早版本）
    manifest = svc._load_versions_manifest("src_a", "item_1")
    for v in manifest.versions:
        if v.version_id == "1.0.0":
            v.is_initial = False
    svc._save_versions_manifest("src_a", "item_1", manifest)

    result = svc.delete_version(
        source_id="src_a",
        item_id="item_1",
        version_id="1.0.0",
    )

    assert result.success
    assert result.deleted_version == "1.0.0"

    # 验证版本目录已删除
    version_dir = (
        tmp_path / "market" / "src_a" / "skill_versions" / "item_1" / "1.0.0"
    )
    assert not version_dir.exists()


def test_delete_current_version_fails(tmp_path):
    """测试删除当前版本失败."""
    svc = _make_version_service(tmp_path)

    skill_md = """---
name: "测试技能"
version: "1.0.0"
---
# v1
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md,
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v1",
        creator="user",
    )

    # 删除当前版本（应该失败）
    result = svc.delete_version(
        source_id="src_a",
        item_id="item_1",
        version_id="1.0.0",
    )

    assert not result.success
    assert "current version" in result.message.lower()


def test_delete_initial_version_is_rejected(tmp_path):
    """初始版本不可删除（与 MCP 行为对称，避免破坏版本血脉）."""
    svc = _make_version_service(tmp_path)

    skill_md_v1 = """---
name: "测试技能"
version: "1.0.0"
---
# v1
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md_v1,
    )

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v1",
        creator="user",
    )

    # 内容变化，创建第二个版本（让 v1 不再是 current 但仍是 initial）
    (skill_dir / "SKILL.md").write_text(
        """---
name: "测试技能"
version: "1.0.0"
---
# v2 changed body
""",
        encoding="utf-8",
    )
    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v2",
        creator="user",
    )

    # 尝试删除初始版本 → 应被拒绝
    manifest = svc._load_versions_manifest("src_a", "item_1")
    initial_version_id = next(
        v.version_id for v in manifest.versions if v.is_initial
    )
    result = svc.delete_version(
        source_id="src_a",
        item_id="item_1",
        version_id=initial_version_id,
    )

    assert result.success is False
    assert "initial" in result.message.lower()

    # 版本目录依然存在
    version_dir = (
        tmp_path
        / "market"
        / "src_a"
        / "skill_versions"
        / "item_1"
        / initial_version_id
    )
    assert version_dir.exists()


def test_generate_timestamp_version_when_no_version_in_skill_md(tmp_path):
    """测试 SKILL.md 无版本号时生成时间戳格式."""
    svc = _make_version_service(tmp_path)

    skill_md = """---
name: "测试技能"
---
# 测试技能
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md,
    )

    # 测试无 current_market_version 时，默认使用 1.0.0
    version = svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="无版本号",
        creator="user",
    )

    # 版本号应默认为 1.0.0
    assert version.version_id == "1.0.0"


def test_version_auto_bump_when_no_version_in_skill_md(tmp_path):
    """测试 SKILL.md 无版本号时，使用传入的版本号."""
    svc = _make_version_service(tmp_path)

    skill_md = """---
name: "测试技能"
---
# 测试技能
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_2",
        skill_md=skill_md,
    )

    # 传入 current_market_version=1.0.8，无版本历史时应直接使用
    version = svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_2",
        skill_dir=skill_dir,
        description="无版本号使用传入版本",
        creator="user",
        current_market_version="1.0.8",
    )

    # 版本号应直接使用传入的版本号
    assert version.version_id == "1.0.8"


def test_version_bump_from_history(tmp_path):
    """测试版本历史存在 + 内容变化时，接着最后版本递增（F2 新逻辑）.

    F2 修复后，市场端 version_id 由 signature + 历史决定：
    - 内容未变 → 复用历史 version_id（R7 no-op）
    - 内容变化 → _bump_version 历史最新版
    """
    svc = _make_version_service(tmp_path)

    skill_md = """---
name: "测试技能"
---
# 测试技能
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_3",
        skill_md=skill_md,
    )

    # 先创建一个版本 1.0.5
    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_3",
        skill_dir=skill_dir,
        description="初始版本",
        creator="user",
        current_market_version="1.0.5",
    )

    # 修改内容（让 signature 变化）
    skill_md_v2 = """---
name: "测试技能"
---
# 测试技能 - 新增了一行
"""
    (skill_dir / "SKILL.md").write_text(skill_md_v2, encoding="utf-8")

    # 再次创建版本，应接着历史版本递增
    version2 = svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_3",
        skill_dir=skill_dir,
        description="递增版本",
        creator="user",
    )

    # 版本号应递增为 1.0.6（接着历史版本 1.0.5）
    assert version2.version_id == "1.0.6"


def test_version_new_skill_starts_from_1_0_0(tmp_path):
    """测试新技能（无版本历史）从 1.0.0 开始."""
    svc = _make_version_service(tmp_path)

    skill_md = """---
name: "新技能"
---
# 新技能
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_new",
        skill_md=skill_md,
    )

    # 新技能，无版本历史，无 current_market_version
    version = svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_new",
        skill_dir=skill_dir,
        description="新技能",
        creator="user",
    )

    # 版本号应默认为 1.0.0
    assert version.version_id == "1.0.0"


def test_calculate_signature_consistent(tmp_path):
    """测试签名计算一致性."""
    svc = _make_version_service(tmp_path)

    skill_md = """---
name: "测试技能"
version: "1.0.0"
---
# 内容
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md,
    )

    sig1 = svc._calculate_signature(skill_dir)
    sig2 = svc._calculate_signature(skill_dir)

    assert sig1 == sig2
    assert len(sig1) == 64  # SHA256 hexdigest


def test_version_detail_includes_file_tree(tmp_path):
    """测试版本详情包含文件树."""
    svc = _make_version_service(tmp_path)

    skill_md = """---
name: "测试技能"
version: "1.0.0"
---
# v1
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src_a",
        "item_1",
        skill_md=skill_md,
        skill_json={"name": "测试技能"},
    )

    # 创建子目录
    refs_dir = skill_dir / "references"
    refs_dir.mkdir(exist_ok=True)
    (refs_dir / "template.md").write_text("# template", encoding="utf-8")

    svc.create_version_snapshot(
        source_id="src_a",
        item_id="item_1",
        skill_dir=skill_dir,
        description="v1",
        creator="user",
    )

    detail = svc.get_version_detail("src_a", "item_1", "1.0.0")

    assert "version_info" in detail
    assert "file_tree" in detail
    assert len(detail["file_tree"]) >= 1


def test_create_snapshot_with_source_user(tmp_path):
    """T3：创建快照时记录 source_user_* 字段."""
    svc = _make_version_service(tmp_path)
    skill_md = """---
name: t
version: "1.0.0"
---
正文
"""
    skill_dir = _create_skill_dir(tmp_path, "src1", "item1", skill_md=skill_md)

    version = svc.create_version_snapshot(
        source_id="src1",
        item_id="item1",
        skill_dir=skill_dir,
        creator="admin_id",
        creator_name="admin",
        source_user_id="alice_id",
        source_user_name="alice",
        source_user_version="1.5.2",
    )

    assert version.created_by == "admin_id"
    assert version.created_by_name == "admin"
    assert version.source_user_id == "alice_id"
    assert version.source_user_name == "alice"
    assert version.source_user_version == "1.5.2"


def test_create_snapshot_without_source_user_defaults_to_empty(tmp_path):
    """T3：admin 直接 zip 上传场景默认 source_user_* 为空."""
    svc = _make_version_service(tmp_path)
    skill_md = """---
name: t
version: "1.0.0"
---
正文
"""
    skill_dir = _create_skill_dir(tmp_path, "src1", "item1", skill_md=skill_md)

    version = svc.create_version_snapshot(
        source_id="src1",
        item_id="item1",
        skill_dir=skill_dir,
        creator="admin_id",
        creator_name="admin",
    )

    assert version.source_user_id == ""
    assert version.source_user_name == ""
    assert version.source_user_version == ""


def test_old_versions_json_loads_with_default_empty_source_user(tmp_path):
    """T3：向后兼容——旧 versions.json 没有 source_user_* 字段时读出来为空串."""
    svc = _make_version_service(tmp_path)
    versions_path = (
        tmp_path
        / "market"
        / "src1"
        / "skill_versions"
        / "item1"
        / "versions.json"
    )
    versions_path.parent.mkdir(parents=True, exist_ok=True)
    versions_path.write_text(
        json.dumps(
            {
                "skill_name": "old",
                "versions": [
                    {
                        "version_id": "1.0.0",
                        "created_at": "2025-01-01T00:00:00+00:00",
                        "created_by": "u1",
                        "created_by_name": "user1",
                        "description": "legacy",
                        "signature": "sig",
                        "is_current": True,
                        "is_initial": True,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    listed = svc.list_versions("src1", "item1")
    assert listed["versions"][0]["source_user_id"] == ""
    assert listed["versions"][0]["source_user_name"] == ""
    assert listed["versions"][0]["source_user_version"] == ""


def test_same_version_same_content_does_not_flip_is_current(tmp_path):
    """T4 R7：同 signature 时复用历史 version_id 并 no-op，不翻 is_current.

    F2 修复后市场版本号由 signature + 历史决定，不再读 SKILL.md。
    所以 R7 触发条件改为：当前内容 signature == 历史最新版 signature。
    """
    svc = _make_version_service(tmp_path)
    skill_md_v1 = """---
name: t
---
v1 content
"""
    skill_md_v2 = """---
name: t
---
v2 content
"""
    skill_dir = _create_skill_dir(
        tmp_path,
        "src1",
        "item1",
        skill_md=skill_md_v1,
    )

    # 创建首版（version_id=1.0.0，signature=sigA）
    v1 = svc.create_version_snapshot(
        source_id="src1",
        item_id="item1",
        skill_dir=skill_dir,
        creator="u1",
        creator_name="user1",
    )
    assert v1.is_current is True
    assert v1.version_id == "1.0.0"

    # 升级（内容变化 → signature 变化 → 自动 bump 到 1.0.1）
    (skill_dir / "SKILL.md").write_text(skill_md_v2, encoding="utf-8")
    v2 = svc.create_version_snapshot(
        source_id="src1",
        item_id="item1",
        skill_dir=skill_dir,
        creator="u2",
        creator_name="user2",
    )
    assert v2.is_current is True
    assert v2.version_id == "1.0.1"

    # 当前 current=1.0.1（signature=sigB）。再次用相同内容创建快照：
    # signature 与历史最新版相同 → 复用 version_id=1.0.1 → R7 no-op
    svc.create_version_snapshot(
        source_id="src1",
        item_id="item1",
        skill_dir=skill_dir,
        creator="u3",
        creator_name="user3",
    )

    # R7：v1.0.1 仍是 current，不应被翻回旧版本，且不应产生新快照
    listed = svc.list_versions("src1", "item1")
    current_ids = [
        v["version_id"] for v in listed["versions"] if v["is_current"]
    ]
    assert current_ids == [
        "1.0.1",
    ], f"R7 violated: current should remain 1.0.1, got {current_ids}"
    # 也不应产生新快照（依然只有 2 条）
    assert (
        len(listed["versions"]) == 2
    ), f"R7 violated: snapshot count should stay 2, got {len(listed['versions'])}"
