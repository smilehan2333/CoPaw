# -*- coding: utf-8 -*-
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def _make_service(tmp_path, mock_db=None):
    from market.marketplace.service import MarketplaceService

    if mock_db is None:
        mock_db = AsyncMock()
        mock_db.is_connected = True
        mock_db.fetch_one = AsyncMock(return_value=None)
        mock_db.fetch_all = AsyncMock(return_value=[])
    return MarketplaceService(
        db=mock_db,
        marketplace_root=tmp_path / "market",
        swe_root=tmp_path / "swe",
    )


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

    skill_json = json.loads(
        (skill_dir / "skill.json").read_text(encoding="utf-8"),
    )
    assert skill_json["version"] == "1.0.1"
    assert "updated_at" in skill_json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = manifest["skills"]["demo_skill"]["metadata"]
    assert metadata["version_text"] == "1.0.1"
    assert "updated_at" in metadata
    assert "updated_at" in manifest["skills"]["demo_skill"]


def test_save_skill_file_does_not_touch_skill_md_when_other_file_changes(
    tmp_path,
):
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
    assert (skill_dir / "SKILL.md").read_text(
        encoding="utf-8",
    ) == original_skill_md
    assert (skill_dir / "references" / "foo.md").read_text(
        encoding="utf-8",
    ) == "new reference\n"

    skill_json = json.loads(
        (skill_dir / "skill.json").read_text(encoding="utf-8"),
    )
    assert skill_json["version"] == "2.0.1"
    assert skill_json["created_at"] == "2026-01-01T00:00:00+00:00"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert (
        manifest["skills"]["demo_skill"]["metadata"]["version_text"] == "2.0.1"
    )


def test_save_skill_file_preserves_existing_skill_md_version_and_uses_it_as_fallback(
    tmp_path,
):
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
    assert (skill_dir / "SKILL.md").read_text(
        encoding="utf-8",
    ) == original_skill_md

    skill_json = json.loads(
        (skill_dir / "skill.json").read_text(encoding="utf-8"),
    )
    assert skill_json["version"] == "1.2.4"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert (
        manifest["skills"]["demo_skill"]["metadata"]["version_text"] == "1.2.4"
    )


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
    assert (skill_dir / "skill.json").read_text(
        encoding="utf-8",
    ) == skill_json_before
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
    assert (skill_dir / "SKILL.md").read_text(
        encoding="utf-8",
    ) == submitted_content
    assert (skill_dir / "skill.json").read_text(
        encoding="utf-8",
    ) == "not a valid json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert (
        manifest["skills"]["demo_skill"]["metadata"]["version_text"] == "4.0.1"
    )


@pytest.mark.asyncio
async def test_publish_skill_creates_index_entry(tmp_path):
    from market.marketplace.schemas import PublishSkillRequest

    svc = _make_service(tmp_path)
    req = PublishSkillRequest(
        name="skill_a",
        description="desc",
        creator_id="user1",
        creator_name="User One",
        skill_json={"name": "skill_a"},
        skill_md="# Skill A",
    )
    item, _ = await svc.publish_skill("src_a", req)
    assert item.name == "skill_a"
    assert item.version == "1.0.0"
    assert item.status == "active"
    # index.json should exist
    index_path = tmp_path / "market" / "src_a" / "index.json"
    assert index_path.exists()
    data = json.loads(index_path.read_text())
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_publish_skill_increments_version_on_republish(tmp_path):
    """F1/F2 修复后：内容变化才 bump；内容不变走 R7 no-op，版本号不动."""
    from market.marketplace.schemas import PublishSkillRequest

    svc = _make_service(tmp_path)
    req1 = PublishSkillRequest(
        name="skill_a",
        description="",
        creator_id="u1",
        creator_name="",
        skill_json={},
        skill_md="# v1",
    )
    item1, _ = await svc.publish_skill("src_a", req1)
    assert item1.version == "1.0.0"

    # 同样内容再 publish 一次 → R7 no-op，版本不动
    req1.overwrite = True
    item_same, _ = await svc.publish_skill("src_a", req1)
    assert (
        item_same.version == "1.0.0"
    ), "内容未变化时市场版本不应 bump（R7 no-op）"

    # 改了内容再 publish → 自动 bump 到 1.0.1
    req2 = PublishSkillRequest(
        name="skill_a",
        description="",
        creator_id="u1",
        creator_name="",
        skill_json={},
        skill_md="# v2 changed",
        overwrite=True,
    )
    item2, _ = await svc.publish_skill("src_a", req2)
    assert item2.version == "1.0.1", "内容变化时市场版本应自动 bump"


@pytest.mark.asyncio
async def test_unpublish_skill_sets_inactive(tmp_path):
    from market.marketplace.schemas import PublishSkillRequest

    svc = _make_service(tmp_path)
    req = PublishSkillRequest(
        name="skill_b",
        description="",
        creator_id="u1",
        creator_name="",
        skill_json={},
        skill_md="",
    )
    item, _ = await svc.publish_skill("src_a", req)
    await svc.unpublish_skill("src_a", item.item_id, "u1", "User One")
    items = await svc.list_skills("src_a", user_bbk_id="100")
    assert all(
        i.status == "inactive" for i in items if i.item_id == item.item_id
    )


@pytest.mark.asyncio
async def test_list_skills_filters_by_bbk_id(tmp_path):
    from market.marketplace.schemas import PublishSkillRequest

    svc = _make_service(tmp_path)
    # skill visible to all (bbk_ids=[])
    req_all = PublishSkillRequest(
        name="skill_all",
        description="",
        creator_id="u1",
        creator_name="",
        skill_json={},
        skill_md="",
        bbk_ids=[],
    )
    # skill visible only to bbk_id=200
    req_200 = PublishSkillRequest(
        name="skill_200",
        description="",
        creator_id="u1",
        creator_name="",
        skill_json={},
        skill_md="",
        bbk_ids=["200"],
    )
    await svc.publish_skill("src_a", req_all)
    await svc.publish_skill("src_a", req_200)
    # bbk_id=100 (总行) sees all
    items_100 = await svc.list_skills("src_a", user_bbk_id="100")
    assert len(items_100) == 2
    # bbk_id=300 sees only skill_all (bbk_ids=[])
    items_300 = await svc.list_skills("src_a", user_bbk_id="300")
    assert len(items_300) == 1
    assert items_300[0].name == "skill_all"


@pytest.mark.asyncio
async def test_get_skill_detail_returns_item(tmp_path):
    from market.marketplace.schemas import PublishSkillRequest

    svc = _make_service(tmp_path)
    req = PublishSkillRequest(
        name="skill_c",
        description="",
        creator_id="u1",
        creator_name="",
        skill_json={},
        skill_md="",
    )
    item, _ = await svc.publish_skill("src_a", req)
    detail = await svc.get_skill_detail(
        "src_a",
        item.item_id,
        user_bbk_id="100",
    )
    assert detail is not None
    assert detail.item_id == item.item_id


@pytest.mark.asyncio
async def test_get_skill_detail_returns_none_for_unknown(tmp_path):
    svc = _make_service(tmp_path)
    detail = await svc.get_skill_detail(
        "src_a",
        "nonexistent-id",
        user_bbk_id="100",
    )
    assert detail is None


@pytest.mark.asyncio
async def test_get_my_skills_returns_time_fields(tmp_path):
    """get_my_skills 应返回 created_at 和 updated_at 字段."""
    from market.marketplace.fs import get_user_skill_manifest_path
    from market.marketplace.service import get_user_skills_dir

    svc = _make_service(tmp_path)
    user_id = "test_user"
    source_id = "test_source"
    agent_id = "default"

    # 创建用户技能目录
    skills_dir = get_user_skills_dir(
        tmp_path / "swe",
        user_id,
        agent_id,
        source_id,
    )
    skill_dir = skills_dir / "test_skill"
    skill_dir.mkdir(parents=True)

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
                    "test_skill": {
                        "source": "customized",
                        "created_at": "2025-05-14T10:00:00+00:00",
                        "updated_at": "2025-05-14T12:00:00+00:00",
                        "metadata": {
                            "name": "Test Skill",
                            "description": "A test skill",
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("# Test Skill", encoding="utf-8")

    # 调用服务
    result = await svc.get_my_skills(source_id, user_id, agent_id)

    assert len(result) == 1
    assert result[0].skill_name == "test_skill"
    assert result[0].created_at == "2025-05-14T10:00:00+00:00"
    assert result[0].updated_at == "2025-05-14T12:00:00+00:00"


@pytest.mark.asyncio
async def test_get_my_skills_handles_missing_time_fields(tmp_path):
    """get_my_skills 应处理缺失的时间字段."""
    from market.marketplace.fs import get_user_skill_manifest_path
    from market.marketplace.service import get_user_skills_dir

    svc = _make_service(tmp_path)
    user_id = "test_user"
    source_id = "test_source"
    agent_id = "default"

    # 创建用户技能目录
    skills_dir = get_user_skills_dir(
        tmp_path / "swe",
        user_id,
        agent_id,
        source_id,
    )
    skill_dir = skills_dir / "old_skill"
    skill_dir.mkdir(parents=True)

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
                    "old_skill": {
                        "source": "customized",
                        "metadata": {
                            "name": "Old Skill",
                            "description": "An old skill without time fields",
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("# Old Skill", encoding="utf-8")

    # 调用服务
    result = await svc.get_my_skills(source_id, user_id, agent_id)

    assert len(result) == 1
    assert result[0].skill_name == "old_skill"
    assert result[0].created_at is None
    assert result[0].updated_at is None


@pytest.mark.asyncio
async def test_get_my_skills_reads_frontmatter_and_market_metadata(tmp_path):
    """get_my_skills 应组合 frontmatter、manifest 和市场版本信息."""
    from market.marketplace.fs import get_user_skill_manifest_path
    from market.marketplace.schemas import PublishSkillRequest
    from market.marketplace.service import get_user_skills_dir

    svc = _make_service(tmp_path)
    user_id = "test_user"
    source_id = "test_source"
    agent_id = "default"

    published, _ = await svc.publish_skill(
        source_id,
        PublishSkillRequest(
            name="Market Skill",
            description="market desc",
            creator_id="creator-1",
            creator_name="张三",
            skill_json={},
            skill_md="",
        ),
    )

    skills_dir = get_user_skills_dir(
        tmp_path / "swe",
        user_id,
        agent_id,
        source_id,
    )
    skill_dir = skills_dir / "market_skill_copy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: Market Skill\n"
        "description: 从前言读取\n"
        "---\n"
        "# Market Skill\n",
        encoding="utf-8",
    )

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
                    "market_skill_copy": {
                        "source": f"marketplace:{published.item_id}",
                        "enabled": False,
                        "created_at": "2025-05-14T10:00:00+00:00",
                        "updated_at": "2025-05-14T12:00:00+00:00",
                        "metadata": {
                            "received_version": "0.9.0",
                            "distributed_by": "admin1",
                            "creator_name": "%E5%BC%A0%E4%B8%89",
                            "category_id": 9,
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = await svc.get_my_skills(source_id, user_id, agent_id)

    assert len(result) == 1
    assert result[0].display_name == "Market Skill"
    assert result[0].description == "从前言读取"
    assert result[0].is_received is True
    assert result[0].has_update is True
    assert result[0].enabled is False
    assert result[0].distributed_by == "admin1"
    assert result[0].creator_name == "张三"
    assert result[0].category == "9"
    assert result[0].created_at == "2025-05-14T10:00:00+00:00"
    assert result[0].updated_at == "2025-05-14T12:00:00+00:00"


@pytest.mark.asyncio
async def test_recall_skill_by_name_removes_skill_dir_and_manifest(tmp_path):
    """按名称撤回技能时，应删除目录并移除 manifest 记录."""
    from market.marketplace.fs import (
        get_user_skill_manifest_path,
        get_user_skills_dir,
    )
    from market.marketplace.schemas import RecallRequest

    mock_db = AsyncMock()
    mock_db.is_connected = False
    svc = _make_service(tmp_path, mock_db=mock_db)
    svc.disable_skill = AsyncMock(return_value={"success": True})
    svc._trigger_agent_reload = AsyncMock()

    user_id = "user-1"
    source_id = "source-1"
    skill_name = "skill_to_recall"

    skills_dir = get_user_skills_dir(
        tmp_path / "swe",
        user_id,
        "default",
        source_id,
    )
    skill_dir = skills_dir / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Skill", encoding="utf-8")

    manifest_path = get_user_skill_manifest_path(
        tmp_path / "swe",
        user_id,
        "default",
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
                        "metadata": {"name": skill_name},
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = await svc.recall_skill(
        source_id,
        None,
        "admin-1",
        "Admin",
        RecallRequest(skill_name=skill_name, target_user_ids=[user_id]),
    )

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result.recalled_count == 1
    assert result.failed_count == 0
    assert result.results[0].success is True
    assert not skill_dir.exists()
    assert skill_name not in manifest_data["skills"]


@pytest.mark.asyncio
async def test_recall_mcp_by_name_removes_client_from_agent_config(tmp_path):
    """按名称撤回 MCP 时，应从 agent 配置中移除目标 client.

    撤回使用 mcp_name（name 字段）匹配，不依赖 dict key。
    即使用户配置中的 dict key 与 name 不同，也能正确找到并移除。
    """
    from market.marketplace.fs import resolve_effective_user_id
    from market.marketplace.schemas import RecallRequest

    mock_db = AsyncMock()
    mock_db.is_connected = False
    svc = _make_service(tmp_path, mock_db=mock_db)
    svc._trigger_agent_reload = AsyncMock()

    user_id = "user-1"
    source_id = "source-1"
    effective_user_id = resolve_effective_user_id(user_id, source_id)
    agent_config_path = (
        tmp_path
        / "swe"
        / effective_user_id
        / "workspaces"
        / "default"
        / "agent.json"
    )
    agent_config_path.parent.mkdir(parents=True, exist_ok=True)
    agent_config_path.write_text(
        json.dumps(
            {
                "mcp": {
                    "clients": {
                        "my-mcp-tool": {
                            "name": "My MCP Tool",
                            "source": "marketplace:item-1",
                        },
                        "other-client": {
                            "name": "Other Client",
                            "source": "marketplace:item-2",
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 按 mcp_name 撤回，dict key "my-mcp-tool" 与 name "My MCP Tool" 不同
    result = await svc.recall_mcp(
        source_id,
        None,
        "admin-1",
        "Admin",
        RecallRequest(mcp_name="My MCP Tool", target_user_ids=[user_id]),
    )

    config_data = json.loads(agent_config_path.read_text(encoding="utf-8"))
    assert result.recalled_count == 1
    assert result.failed_count == 0
    assert result.results[0].success is True
    assert "my-mcp-tool" not in config_data["mcp"]["clients"]
    assert "other-client" in config_data["mcp"]["clients"]


@pytest.mark.asyncio
async def test_publish_skill_appends_version_for_different_user(tmp_path):
    """T5 R4：不同用户同名 skill → 续接到现有 MarketItem，不再抛 SkillNameConflictError."""
    from market.marketplace.schemas import PublishSkillRequest
    from market.marketplace.fs import load_index

    svc = _make_service(tmp_path)
    # 用户 A 首发
    req_a = PublishSkillRequest(
        name="demo",
        description="a",
        creator_id="alice",
        creator_name="Alice",
        skill_json={"name": "demo"},
        skill_md='---\nname: demo\nversion: "1.0.0"\n---\n',
    )
    item_a, _ = await svc.publish_skill("src_a", req_a)

    # 用户 B 同名同步（不同 creator_id），确认覆盖后续接
    req_b = PublishSkillRequest(
        name="demo",
        description="b",
        creator_id="bob",
        creator_name="Bob",
        skill_json={"name": "demo"},
        skill_md='---\nname: demo\nversion: "2.0.0"\n---\n',
        overwrite=True,
    )
    item_b, _ = await svc.publish_skill("src_a", req_b)

    # 续接到同一个 item_id
    assert item_b.item_id == item_a.item_id
    # creator 跟随当前上传者
    assert item_b.creator_id == "bob"

    # 市场上仍只有一条
    items = load_index(tmp_path / "market", "src_a")
    demos = [i for i in items if i.name == "demo"]
    assert len(demos) == 1


@pytest.mark.asyncio
async def test_publish_skill_records_source_user_from_creator(tmp_path):
    """T6 R6：admin 走 PublishSkillRequest 时，source_user_id=req.creator_id;
    source_user_version 来自被引用用户工作区的 SKILL.md 中的版本.
    operator_* 用作 created_by."""
    from market.marketplace.schemas import PublishSkillRequest
    from market.marketplace.version_service import SkillVersionService

    svc = _make_service(tmp_path)
    req = PublishSkillRequest(
        name="demo",
        description="d",
        creator_id="alice",
        creator_name="Alice",
        skill_json={"name": "demo"},
        skill_md='---\nname: demo\nversion: "1.5.2"\n---\nbody',
    )
    item, _ = await svc.publish_skill(
        "src_a",
        req,
        operator_id="admin_id",
        operator_name="Admin",
    )

    vsvc = SkillVersionService(tmp_path / "market")
    listed = vsvc.list_versions("src_a", item.item_id)
    snap = listed["versions"][0]
    assert snap["source_user_id"] == "alice"
    assert snap["source_user_name"] == "Alice"
    assert snap["source_user_version"] == "1.5.2"
    assert snap["created_by"] == "admin_id"
    assert snap["created_by_name"] == "Admin"


@pytest.mark.asyncio
async def test_publish_mcp_appends_for_different_user(tmp_path):
    """T9 R4 + F1 R3：不同用户同名 MCP → 续接到现有 item，市场版本独立递增（不跟随用户本地版本）。"""
    from market.marketplace.schemas import PublishMCPRequest
    from market.marketplace.fs import load_index
    from market.marketplace.mcp_version_service import MCPVersionService

    svc = _make_service(tmp_path)

    # alice 首发（本地版本 1.0.0 → 市场首版 1.0.0）
    item_a, _ = await svc.publish_mcp(
        "src_a",
        PublishMCPRequest(
            client_key="m1",
            name="demo_mcp",
            description="a",
            creator_id="alice",
            creator_name="Alice",
            config={"name": "demo_mcp", "transport": "stdio", "command": "/a"},
            version="1.0.0",
        ),
    )

    # bob 同名同步（本地版本 2.0.0，但市场版本独立 _bump_patch 到 1.0.1）
    item_b, _ = await svc.publish_mcp(
        "src_a",
        PublishMCPRequest(
            client_key="m1",
            name="demo_mcp",
            description="b",
            creator_id="bob",
            creator_name="Bob",
            config={"name": "demo_mcp", "transport": "stdio", "command": "/b"},
            version="2.0.0",
            overwrite=True,
        ),
    )

    assert item_b.item_id == item_a.item_id
    items = load_index(tmp_path / "market", "src_a")
    demos = [i for i in items if i.name == "demo_mcp"]
    assert len(demos) == 1

    # F1 R3：市场版本独立递增，不再 follow 用户本地版本
    assert item_b.version == "1.0.1"

    # 快照里应有两个版本：1.0.0（alice 首发）和 1.0.1（bob 续接）
    vsvc = MCPVersionService(tmp_path / "market")
    listed = vsvc.list_versions("src_a", item_a.item_id)
    ids = sorted(v["version_id"] for v in listed["versions"])
    assert ids == ["1.0.0", "1.0.1"]
    # 最新快照 source_user 是 bob，且 source_user_version 保留 bob 的本地版本 2.0.0
    current = next(v for v in listed["versions"] if v["is_current"])
    assert current["version_id"] == "1.0.1"
    assert current["source_user_id"] == "bob"
    assert current["source_user_version"] == "2.0.0"


@pytest.mark.asyncio
async def test_publish_mcp_admin_zip_source_user_empty(tmp_path):
    """T9 R6：admin zip 路径（显式 source_user_id="" + v0.0.0）应记录正确."""
    from market.marketplace.schemas import PublishMCPRequest
    from market.marketplace.mcp_version_service import MCPVersionService

    svc = _make_service(tmp_path)

    item, _ = await svc.publish_mcp(
        "src_a",
        PublishMCPRequest(
            client_key="m2",
            name="zipmcp",
            description="d",
            creator_id="admin_id",
            creator_name="Admin",
            config={"name": "zipmcp", "transport": "stdio", "command": "/x"},
            version="1.0.0",
            source_user_id="",
            source_user_name="",
            source_user_version="v0.0.0",
            operator_id="admin_id",
            operator_name="Admin",
        ),
    )

    vsvc = MCPVersionService(tmp_path / "market")
    listed = vsvc.list_versions("src_a", item.item_id)
    snap = listed["versions"][0]
    assert snap["source_user_id"] == ""
    assert snap["source_user_name"] == ""
    assert snap["source_user_version"] == "v0.0.0"
    assert snap["created_by"] == "admin_id"
