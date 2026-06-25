# -*- coding: utf-8 -*-
"""管理员市场 API."""

import asyncio
import io
import json
import logging
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

from fastapi import (
    APIRouter,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from ...marketplace.fs import get_skill_dir, _atomic_write_json
from ...marketplace.schemas import (
    DistributeRequest,
    DistributeResponse,
    MarketSkillResponse,
    PublishSkillRequest,
    UploadSkillResponse,
)
from ...marketplace.service import (
    MarketItem,
    SkillNameConflictError,
    SkillVersionConflictError,
    load_index,
    save_index,
)
from ...marketplace.version_service import SkillVersionService
from ..deps import decode_user_name, require_source_id
from .skills_browse import (
    _decode_zip_filename,
    _extract_zip_skills,
    _read_validated_zip_upload,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class _InitUserSkillsResult(TypedDict):
    """init_user_skills 返回结果类型."""

    dry_run: bool
    processed_users: int
    processed_workspaces: int
    processed_skills: int
    created_skill_json: int
    updated_source: int
    skipped_marketplace: int
    errors: list[dict[str, str]]
    details: list[dict[str, str]]


def _require_manager(x_manager: Optional[str]) -> None:
    """验证管理员权限."""
    if x_manager != "true":
        raise HTTPException(status_code=403, detail="Manager access required")


def _parse_skill_metadata(
    skill_dir: Path,
    skill_name: str,
) -> tuple[dict, str, str, str, str]:
    """解析技能元数据.

    Returns:
        (skill_json, skill_md, name, description, version)
    """
    skill_json_path = skill_dir / "skill.json"
    skill_md_path = skill_dir / "SKILL.md"

    skill_json = {}
    skill_md = ""
    name_from_skill = skill_name
    description_from_skill = ""
    version_from_skill = ""

    # 读取 skill.json
    if skill_json_path.exists():
        try:
            skill_json = json.loads(
                skill_json_path.read_text(encoding="utf-8"),
            )
            name_from_skill = skill_json.get("name", skill_name)
            description_from_skill = skill_json.get("description", "")
            version_from_skill = skill_json.get("version", "")
        except json.JSONDecodeError:
            pass

    # 读取 SKILL.md 并解析 frontmatter
    if skill_md_path.exists():
        skill_md = skill_md_path.read_text(encoding="utf-8")
        name_from_skill, description_from_skill, version_from_md = (
            _parse_frontmatter(
                skill_md,
                name_from_skill,
                description_from_skill,
            )
        )
        # SKILL.md 中的 version 优先级更高（与版本历史对齐）
        if version_from_md:
            version_from_skill = version_from_md

    return (
        skill_json,
        skill_md,
        name_from_skill,
        description_from_skill,
        version_from_skill,
    )


def _parse_frontmatter(
    skill_md: str,
    default_name: str,
    default_desc: str,
) -> tuple[str, str, str]:
    """从 SKILL.md 解析 frontmatter（委托共享工具）.

    Returns:
        (name, description, version)
    """
    from ...utils.skill_md import extract_metadata

    meta = extract_metadata(skill_md)
    name = meta["name"] or default_name
    desc = meta["description"] or default_desc
    version = meta["version"]
    return name, desc, version


def _copy_skill_to_market(
    skill_dir: Path,
    market_skill_dir: Path,
    skill_json: dict,  # noqa: ARG001 - 保留参数签名兼容，但不再写入
    skill_md: str,
) -> None:
    """复制技能文件到市场目录.

    覆盖时先清空目标目录，确保旧文件不会残留。
    不再写入 skill.json，元数据从 SKILL.md frontmatter 读取。
    """
    market_skill_dir.mkdir(parents=True, exist_ok=True)

    # 清空目标目录中的旧文件（覆盖场景）
    for existing in market_skill_dir.iterdir():
        if existing.is_dir():
            shutil.rmtree(existing)
        else:
            existing.unlink()

    # 复制 SKILL.md（newline="" 防止 Windows 上 write_text 把 LF 转为 CRLF，
    # 导致与 copytree 路径写入的文件签名不一致，R7 no-op 跨路径失效）
    if skill_md:
        (market_skill_dir / "SKILL.md").write_text(
            skill_md,
            encoding="utf-8",
            newline="",
        )

    # 复制其他文件（排除 skill.json）
    for f in skill_dir.iterdir():
        if f.name not in ("skill.json", "SKILL.md"):
            target = market_skill_dir / f.name
            if f.is_dir():
                shutil.copytree(f, target)
            else:
                shutil.copy2(f, target)


async def _log_publish_operation(
    svc,
    source_id: str,
    user_id: str,
    user_name: str,
    item: MarketItem,
) -> None:
    """记录上架操作日志."""
    if not svc.db.is_connected:
        return

    try:
        await svc.db.execute(
            """
            INSERT INTO swe_marketplace_operation_logs
                (source_id, operator_id, operator_name, operation,
                 item_type, item_id, item_name,
                 target_user_id, target_user_name, target_bbk_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                source_id,
                user_id,
                user_name,
                "publish",
                "skill",
                item.item_id,
                item.name,
                None,
                None,
                None,
            ),
        )
    except Exception as e:
        logger.warning("Failed to log publish operation: %s", e)


def _create_market_item(
    name: str,
    chinese_name: str,
    description: str,
    version: str,
    user_id: str,
    user_name: str,
    category_id: Optional[int],
    skill_id: str = "",
) -> MarketItem:
    """创建市场条目."""
    now = datetime.now(timezone.utc).isoformat()
    return MarketItem(
        item_id=str(uuid.uuid4()),
        item_type="skill",
        name=name,
        skill_id=skill_id,
        chinese_name=chinese_name,
        description=description,
        version=version or "1.0.0",
        creator_id=user_id,
        creator_name=user_name,
        category_id=category_id,
        bbk_ids=[],
        status="active",
        created_at=now,
        updated_at=now,
    )


def _resolve_skill_cn_name_and_id(
    skill_md: str,
    name: str,
    cn_name: str,
    user_id: str,
) -> tuple[str, str]:
    """解析技能的 cn_name 和 skill_id.

    Args:
        skill_md: SKILL.md 内容
        name: 技能名称
        cn_name: 用户输入的中文展示名
        user_id: 用户 ID

    Returns:
        (resolved_cn_name, resolved_skill_id)
    """
    from ...utils.skill_md import (
        extract_cn_name_from_title,
        extract_skill_id,
        parse_frontmatter,
    )

    # 解析 chinese_name：优先用户输入，其次 metadata.cn_name，再次一级标题
    resolved_cn_name = cn_name.strip() if cn_name else ""
    if not resolved_cn_name:
        fm = parse_frontmatter(skill_md) if skill_md else {}
        metadata = fm.get("metadata", {})
        if isinstance(metadata, dict):
            resolved_cn_name = metadata.get("cn_name", "") or ""
    if not resolved_cn_name and skill_md:
        resolved_cn_name = extract_cn_name_from_title(skill_md)
    if not resolved_cn_name:
        resolved_cn_name = name  # fallback 到技能名

    # 提取 skill_id（从 SKILL.md metadata.skill_id）
    resolved_skill_id = ""
    if skill_md:
        resolved_skill_id = extract_skill_id(
            skill_md,
            source="",  # 市场上传时 item_id 未生成，使用空 source
            skill_name=name,
            creator_id=user_id,
        )

    return resolved_cn_name, resolved_skill_id


def _update_existing_market_item(
    existing: MarketItem,
    description: str,
    cn_name: str,
    skill_id: str,
    user_id: str,
    user_name: str,
    category_id: Optional[int],
) -> bool:
    """更新已有的市场条目.

    Returns:
        cn_name 是否发生变化
    """
    from ...marketplace.service import _bump_patch

    now = datetime.now(timezone.utc).isoformat()
    cn_name_changed = existing.chinese_name != cn_name
    existing.created_at = now
    existing.status = "active"
    existing.chinese_name = cn_name
    existing.description = description
    existing.version = _bump_patch(existing.version)
    existing.creator_id = user_id
    existing.creator_name = user_name
    existing.category_id = category_id
    existing.updated_at = now
    # 同名技能覆盖时，复用已有 skill_id（若已有）
    if existing.skill_id:
        skill_id = existing.skill_id
    elif not existing.skill_id and skill_id:
        existing.skill_id = skill_id
    return cn_name_changed


def _create_market_version_snapshot(
    svc,
    source_id: str,
    item: MarketItem,
    market_skill_dir: Path,
    user_id: str,
    user_name: str,
    cn_name_changed: bool,
) -> bool:
    """创建市场版本快照.

    Args:
        cn_name_changed: cn_name 是否发生变化

    Returns:
        version_unchanged 标志
    """
    version_svc = SkillVersionService(svc.marketplace_root)
    version_unchanged = False
    try:
        snapshot = version_svc.create_version_snapshot(
            source_id=source_id,
            item_id=item.item_id,
            skill_dir=market_skill_dir,
            description="",  # 去掉重复的版本号信息
            creator=user_id,
            creator_name=user_name,
            current_market_version=item.version,
            source_user_id="",
            source_user_name="",
            source_user_version="v0.0.0",
        )
        # F2：让 MarketItem.version 严格跟随快照的 version_id
        # F3：cn_name 变化时不应返回 version_unchanged，即使文件内容未变
        if snapshot.version_id and snapshot.version_id != item.version:
            version_unchanged = not cn_name_changed
            item.version = snapshot.version_id
        elif cn_name_changed:
            version_unchanged = False
    except Exception as e:
        logger.warning("Failed to create version snapshot: %s", e)
    return version_unchanged


def _process_skill_upload_single(
    skill_dir: Path,
    skill_name: str,
    svc,
    source_id: str,
    user_id: str,
    user_name: str,
    category_id: Optional[int],
    overwrite: bool = False,
    cn_name: str = "",
    skill_id: str = "",  # parse-zip 生成的 skill_id
) -> tuple[Optional[str], Optional[dict], Optional[str], str, bool]:
    """处理单个技能的上架逻辑.

    Args:
        overwrite: 是否覆盖同名技能，默认 False（返回冲突）
        cn_name: 用户输入的中文展示名
        skill_id: parse-zip 生成的 skill_id，前端传入确保一致性

    Returns:
        (imported_name, conflict_info, parsed_name_for_first, resolved_cn_name, version_unchanged)
    """
    skill_json, skill_md, name, description, version = _parse_skill_metadata(
        skill_dir,
        skill_name,
    )

    # 直接使用前端传入的 cn_name 和 skill_id（parse-zip 已解析）
    # 如果前端未传（向后兼容），则从 SKILL.md 解析
    resolved_cn_name = cn_name.strip() if cn_name else ""
    final_skill_id = skill_id.strip() if skill_id else ""

    # 向后兼容：前端未传时，从 SKILL.md 解析
    if not resolved_cn_name or not final_skill_id:
        parsed_cn_name, parsed_skill_id = _resolve_skill_cn_name_and_id(
            skill_md,
            name,
            resolved_cn_name,
            user_id,
        )
        if not resolved_cn_name:
            resolved_cn_name = parsed_cn_name
        if not final_skill_id:
            final_skill_id = parsed_skill_id

    # 检查市场是否已存在同名技能
    items = load_index(svc.marketplace_root, source_id)
    existing = next((i for i in items if i.name == name), None)

    # 未显式 overwrite 时返回冲突信息，由前端弹窗让用户确认
    if existing and not overwrite:
        conflict_info = {
            "skill_name": name,
            "suggested_name": name,
            "existing_creator_id": existing.creator_id,
            "existing_creator_name": existing.creator_name,
            "existing_version": existing.version,
        }
        return None, conflict_info, name, resolved_cn_name, False

    version_unchanged = False
    cn_name_changed = False

    if existing:
        # R4: 同名（已确认覆盖） → 续接到现有条目
        cn_name_changed = _update_existing_market_item(
            existing,
            description,
            resolved_cn_name,
            final_skill_id,
            user_id,
            user_name,
            category_id,
        )
        item = existing
    else:
        # 创建新市场条目，市场首发版本固定为 1.0.0
        item = _create_market_item(
            name,
            resolved_cn_name,
            description,
            "",  # 让 _create_market_item 内部 fallback 到 1.0.0
            user_id,
            user_name,
            category_id,
            skill_id=final_skill_id,
        )
        items.append(item)

    # 复制技能文件到市场目录
    market_skill_dir = get_skill_dir(
        svc.marketplace_root,
        source_id,
        item.item_id,
    )
    _copy_skill_to_market(skill_dir, market_skill_dir, skill_json, skill_md)

    # 创建版本快照
    version_unchanged = _create_market_version_snapshot(
        svc,
        source_id,
        item,
        market_skill_dir,
        user_id,
        user_name,
        cn_name_changed,
    )

    save_index(svc.marketplace_root, source_id, items)

    return name, None, name, resolved_cn_name, version_unchanged


async def _process_published_skill_record(
    skill_dir: Path,
    skill_name: str,
    imported_name: str,
    resolved_cn_name: str,
    svc,
    source_id: str,
    x_user_id: str,
    user_name: str,
    parsed_name: Optional[str],
    parsed_description: Optional[str],
    parsed_cn_name: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """处理已发布技能的记录逻辑.

    Returns:
        (parsed_name, parsed_description, parsed_cn_name) 更新后的值
    """
    # 记录首次解析的名称和描述
    if parsed_name is None and imported_name:
        skill_json, skill_md, _, desc, _ = _parse_skill_metadata(
            skill_dir,
            skill_name,
        )
        parsed_name = imported_name
        parsed_description = desc

    # 记录首次解析的中文名
    if parsed_cn_name is None:
        parsed_cn_name = resolved_cn_name

    # 异步记录操作日志
    item = next(
        (
            i
            for i in load_index(svc.marketplace_root, source_id)
            if i.name == imported_name
        ),
        None,
    )
    if item:
        await _log_publish_operation(
            svc,
            source_id,
            x_user_id,
            user_name,
            item,
        )

    return parsed_name, parsed_description, parsed_cn_name


@router.post(
    "/market/skills/publish-upload",
    response_model=UploadSkillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_skill_upload(
    request: Request,
    file: UploadFile = File(..., description="Skill zip file to publish"),
    category_id: Optional[int] = None,
    overwrite: bool = False,
    cn_name: str = "",
    skill_id: str = "",  # parse-zip 生成的 skill_id
    x_source_id: Optional[str] = Header(default=None, alias="X-Source-Id"),
    x_manager: Optional[str] = Header(default=None, alias="X-Manager"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user_name: Optional[str] = Header(default=None, alias="X-User-Name"),
):
    """上传 zip 文件上架技能到市场（管理员）.

    Args:
        overwrite: 是否覆盖同名技能，默认 False（返回冲突提示）
        skill_id: parse-zip 生成的 skill_id，前端传入确保一致性
    """
    source_id = require_source_id(x_source_id)
    _require_manager(x_manager)
    if not x_user_id:
        raise HTTPException(
            status_code=400,
            detail="X-User-Id header is required",
        )

    svc = request.app.state.marketplace
    user_name = decode_user_name(x_user_name) or x_user_id

    # 读取并验证 zip 文件
    data = await _read_validated_zip_upload(file)

    # 解压 zip 文件
    tmp_dir, found_skills = await asyncio.to_thread(
        _extract_zip_skills,
        data,
        file.filename,
    )
    if not found_skills:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return UploadSkillResponse(imported=[], count=0, enabled=True)

    imported = []
    conflicts = []
    parsed_name = None
    parsed_description = None
    parsed_cn_name = None
    has_unchanged = False

    try:
        for skill_dir, skill_name in found_skills:
            (
                imported_name,
                conflict,
                first_name,
                resolved_cn_name,
                version_unchanged,
            ) = await asyncio.to_thread(
                _process_skill_upload_single,
                skill_dir,
                skill_name,
                svc,
                source_id,
                x_user_id,
                user_name,
                category_id,
                overwrite,
                cn_name,
                skill_id,  # 传递 parse-zip 生成的 skill_id
            )

            if conflict:
                conflicts.append(conflict)
                continue

            if version_unchanged:
                has_unchanged = True

            if imported_name:
                imported.append(imported_name)
                parsed_name, parsed_description, parsed_cn_name = (
                    await _process_published_skill_record(
                        skill_dir,
                        skill_name,
                        imported_name,
                        resolved_cn_name,
                        svc,
                        source_id,
                        x_user_id,
                        user_name,
                        parsed_name,
                        parsed_description,
                        parsed_cn_name,
                    )
                )
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    result = UploadSkillResponse(
        imported=imported,
        count=len(imported),
        enabled=True,
        name=parsed_name,
        description=parsed_description,
        cn_name=parsed_cn_name,
        version_unchanged=has_unchanged,
    )
    if conflicts:
        result.conflicts = conflicts
    return result


@router.post(
    "/market/skills",
    response_model=MarketSkillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_skill(
    req: PublishSkillRequest,
    request: Request,
    x_source_id: Optional[str] = Header(default=None, alias="X-Source-Id"),
    x_manager: Optional[str] = Header(default=None, alias="X-Manager"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user_name: Optional[str] = Header(default=None, alias="X-User-Name"),
):
    """上架技能（管理员）."""
    source_id = require_source_id(x_source_id)
    _require_manager(x_manager)
    svc = request.app.state.marketplace
    operator_name = ""
    if x_user_name:
        from urllib.parse import unquote

        try:
            operator_name = unquote(x_user_name)
        except Exception:  # pylint: disable=broad-except
            operator_name = x_user_name
    try:
        item, version_unchanged = await svc.publish_skill(
            source_id,
            req,
            operator_id=x_user_id or "",
            operator_name=operator_name,
        )
    except SkillNameConflictError as exc:
        # 同名续接后此分支理论上不会触发；保留为兜底
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "existing_item_id": exc.existing_item_id,
                "existing_name": exc.existing_name,
                "existing_creator_id": exc.existing_creator_id,
                "existing_creator_name": exc.existing_creator_name,
                "existing_version": exc.existing_version,
            },
        ) from exc
    except SkillVersionConflictError as exc:
        # F3 修复：版本快照撞车不再静默吞掉，让前端可见
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VERSION_CONFLICT",
                "message": str(exc),
                "hint": "本次同步内容与已有版本撞车，请稍后重试或联系管理员",
            },
        ) from exc
    return MarketSkillResponse(
        item_id=item.item_id,
        name=item.name,
        description=item.description,
        version=item.version,
        creator_id=item.creator_id,
        creator_name=item.creator_name,
        category_id=item.category_id,
        bbk_ids=item.bbk_ids,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
        version_unchanged=version_unchanged,
    )


@router.delete(
    "/market/skills/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unpublish_skill(
    item_id: str,
    request: Request,
    x_source_id: Optional[str] = Header(default=None, alias="X-Source-Id"),
    x_manager: Optional[str] = Header(default=None, alias="X-Manager"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user_name: Optional[str] = Header(default=None, alias="X-User-Name"),
):
    """下架技能（管理员）."""
    source_id = require_source_id(x_source_id)
    _require_manager(x_manager)
    svc = request.app.state.marketplace
    ok = await svc.unpublish_skill(
        source_id,
        item_id,
        operator_id=x_user_id or "",
        operator_name=decode_user_name(x_user_name) or "",
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Skill not found")


@router.delete(
    "/market/skills/{item_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_skill_permanently(
    item_id: str,
    request: Request,
    x_source_id: Optional[str] = Header(default=None, alias="X-Source-Id"),
    x_manager: Optional[str] = Header(default=None, alias="X-Manager"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user_name: Optional[str] = Header(default=None, alias="X-User-Name"),
):
    """彻底删除技能及其版本历史（管理员）。"""
    source_id = require_source_id(x_source_id)
    _require_manager(x_manager)
    svc = request.app.state.marketplace
    ok = await svc.delete_market_skill(
        source_id,
        item_id,
        operator_id=x_user_id or "",
        operator_name=decode_user_name(x_user_name) or "",
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Skill not found")


@router.post(
    "/market/skills/{item_id}/distribute",
    response_model=DistributeResponse,
)
async def distribute_skill(
    item_id: str,
    req: DistributeRequest,
    request: Request,
    x_source_id: Optional[str] = Header(default=None, alias="X-Source-Id"),
    x_manager: Optional[str] = Header(default=None, alias="X-Manager"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user_name: Optional[str] = Header(default=None, alias="X-User-Name"),
):
    """分发技能（管理员）."""
    source_id = require_source_id(x_source_id)
    _require_manager(x_manager)
    svc = request.app.state.marketplace
    try:
        result = await svc.distribute_skill(
            source_id,
            item_id,
            operator_id=x_user_id or "",
            operator_name=decode_user_name(x_user_name) or "",
            req=req,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


def _process_user_skill(
    skill_dir: Path,
    skill_name: str,
    user_id: str,
    agent_id: str,
    dry_run: bool,
    results: _InitUserSkillsResult,
) -> None:
    """处理单个技能的初始化逻辑."""
    skill_json_path = skill_dir / "skill.json"

    try:
        if not skill_json_path.exists():
            # 无 skill.json，创建新文件
            skill_data = {
                "schema_version": "workspace-skill.v1",
                "name": skill_name,
                "source": "customized",
                "description": "",
                "version": "1.0.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            results["created_skill_json"] += 1
            results["details"].append(
                {
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "skill_name": skill_name,
                    "action": "created",
                },
            )

            if not dry_run:
                _atomic_write_json(skill_json_path, skill_data)
            return

        # 已有 skill.json，检查 source 字段
        try:
            skill_data = json.loads(
                skill_json_path.read_text(encoding="utf-8"),
            )
        except json.JSONDecodeError as e:
            results["errors"].append(
                {
                    "user_id": user_id,
                    "skill_name": skill_name,
                    "error": f"JSON decode error: {e}",
                },
            )
            return

        current_source = skill_data.get("source", "")

        if current_source.startswith("marketplace:"):
            # 已是分发技能，跳过
            results["skipped_marketplace"] += 1
            return

        if current_source == "customized":
            # 已是正确的值，跳过
            return

        # 需要更新 source
        skill_data["source"] = "customized"
        results["updated_source"] += 1
        results["details"].append(
            {
                "user_id": user_id,
                "agent_id": agent_id,
                "skill_name": skill_name,
                "action": "updated",
                "old_source": current_source,
            },
        )

        if not dry_run:
            _atomic_write_json(skill_json_path, skill_data)

    except Exception as e:
        results["errors"].append(
            {
                "user_id": user_id,
                "skill_name": skill_name,
                "error": str(e),
            },
        )


def _process_workspace_skills(
    workspace_dir: Path,
    user_id: str,
    dry_run: bool,
    results: _InitUserSkillsResult,
) -> None:
    """处理单个 workspace 下的所有技能."""
    agent_id = workspace_dir.name
    skills_dir = workspace_dir / "skills"
    if not skills_dir.exists():
        return

    results["processed_workspaces"] += 1

    for skill_dir in skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        results["processed_skills"] += 1
        _process_user_skill(
            skill_dir,
            skill_name,
            user_id,
            agent_id,
            dry_run,
            results,
        )


@router.post(
    "/market/admin/skills/init-user-skills",
)
async def init_user_skills(
    request: Request,
    dry_run: bool = True,
    user_id: str | None = None,
):
    """初始化用户的历史技能数据为「我创建的」.

    处理逻辑：
    1. 遍历 SWE_ROOT 下用户目录（指定 user_id 则仅处理该用户）
    2. 对于每个用户的技能目录：
       - 无 skill.json：创建文件，设置 source=customized
       - 有 skill.json 但 source 为空或非 marketplace:：设置 source=customized
       - 已是 marketplace: 开头：跳过（保持为「我接收的」）

    Args:
        dry_run: True 仅预览变更，不实际写入；False 执行写入
        user_id: 可选，指定要初始化的用户 ID，不传则处理所有用户
    """
    svc = request.app.state.marketplace
    swe_root = svc.swe_root

    results: _InitUserSkillsResult = {
        "dry_run": dry_run,
        "processed_users": 0,
        "processed_workspaces": 0,
        "processed_skills": 0,
        "created_skill_json": 0,
        "updated_source": 0,
        "skipped_marketplace": 0,
        "errors": [],
        "details": [],
    }

    # 遍历用户目录（支持按 user_id 过滤）
    for user_dir in swe_root.iterdir():
        if not user_dir.is_dir():
            continue
        uid = user_dir.name

        # 指定了 user_id 时跳过不匹配的用户
        if user_id and uid != user_id:
            continue

        results["processed_users"] += 1

        workspace_base = user_dir / "workspaces"
        if not workspace_base.exists():
            continue

        for workspace_dir in workspace_base.iterdir():
            if not workspace_dir.is_dir():
                continue
            _process_workspace_skills(workspace_dir, uid, dry_run, results)

    return results


class _ListSkillsRequest(BaseModel):
    """查询技能列表请求参数."""

    source_id: str = Field(..., description="来源ID")

    # 预留未来扩展参数
    # user_ids: list[str] | None = Field(default=None, description="用户ID列表")
    # skill_types: list[str] | None = Field(default=None, description="技能类型过滤")


class _InitSweSkillsRequest(BaseModel):
    """初始化 swe_skills 表请求参数."""

    source_ids: list[str] = Field(
        default_factory=list,
        description="租户 source_id 列表",
    )
    user_ids: list[str] = Field(
        default_factory=list,
        description="用户 user_id 列表，不传或为空时初始化所有用户，否则只初始化指定用户",
    )
    force: bool = Field(
        default=False,
        description="是否强制重新初始化（覆盖已有数据）",
    )
    dry_run: bool = Field(
        default=False,
        description="试运行模式，仅统计不实际写入",
    )


class _InitSweSkillsResult(TypedDict):
    """初始化 swe_skills 表返回结果."""

    dry_run: bool
    source_ids: list[str]
    user_ids: list[str]
    total_users: int
    total_skills: int
    processed: int
    inserted_db: int
    skipped: int
    errors: list[dict]
    details: list[dict]


@router.post(
    "/market/skills/list",
)
async def list_skills(
    request: Request,
    body: _ListSkillsRequest,
):
    """查询技能列表.

    Args:
        body: 请求参数，包含 source_id 等

    Returns:
        技能列表，每个 skill_id 只返回一条记录，包含 skill_id、skill_name、cn_name
    """
    from ...marketplace.skill_registry import SkillRegistry

    svc = request.app.state.marketplace
    registry = SkillRegistry(svc.db)

    skills = await registry.list_unique_skills_by_source_id(body.source_id)
    return {
        "source_id": body.source_id,
        "count": len(skills),
        "skills": skills,
    }


def _find_tenant_dirs_for_source_id(
    swe_root: Path,
    source_id: str,
    user_ids: list[str] | None = None,
) -> list[Path]:
    """查找指定 source_id 下的租户目录.

    Args:
        swe_root: SWE 根目录
        source_id: 租户 source_id
        user_ids: 可选，用户 user_id 列表，为空时返回所有匹配的用户

    Returns:
        租户目录列表
    """
    from ...runtime.context import encode_scope_id
    from ...marketplace.fs import resolve_effective_user_id

    tenant_dirs = []

    # 如果指定了 user_ids，根据 user_id 和 source_id 计算目录名
    if user_ids:
        for user_id in user_ids:
            # 计算有效的目录名
            effective_user_id = resolve_effective_user_id(user_id, source_id)
            tenant_dir = swe_root / effective_user_id
            logger.debug(
                "查找用户目录: user_id=%s, source_id=%s, effective_user_id=%s, path=%s",
                user_id,
                source_id,
                effective_user_id,
                tenant_dir,
            )
            if tenant_dir.exists() and tenant_dir.is_dir():
                tenant_dirs.append(tenant_dir)
        return tenant_dirs

    # 未指定 user_ids，查找所有匹配 source_id 的用户目录
    # 直接匹配 default_<source_id>
    default_dir = swe_root / f"default_{source_id}"
    if default_dir.exists() and default_dir.is_dir():
        tenant_dirs.append(default_dir)

    # 遍历目录查找 encode_scope_id 格式的用户目录
    for user_dir in swe_root.iterdir():
        if not user_dir.is_dir():
            continue
        dir_name = user_dir.name
        if dir_name.startswith("default_"):
            continue
        if "." not in dir_name:
            continue
        try:
            from ...runtime.context import decode_scope_id

            _, decoded_source = decode_scope_id(dir_name)
            if decoded_source == source_id:
                tenant_dirs.append(user_dir)
        except ValueError:
            pass

    return tenant_dirs


def _read_workspace_manifest(manifest_path: Path) -> tuple[dict, str | None]:
    """读取 workspace manifest，返回 (manifest, error)."""
    if not manifest_path.exists():
        return {"skills": {}}, None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as e:
        return {}, str(e)


def _extract_skill_fields(
    skill_dir: Path,
    entry: dict,
    skill_name: str,
    user_id: str,
    source_id: str,
    force: bool,
) -> tuple[str, str]:
    """提取技能的 skill_id 和 cn_name.

    Args:
        skill_dir: 技能目录
        entry: skill.json 中的 entry 数据
        skill_name: 技能名
        user_id: 用户ID（数据库 tenant_id）
        source_id: 租户 source_id
        force: 是否强制重新生成

    Returns:
        (skill_id, cn_name)
    """
    from ...utils.skill_md import extract_skill_id, extract_cn_name_from_title

    metadata = entry.get("metadata", {})
    skill_source = entry.get("source", "customized")

    # 读取 SKILL.md 内容
    skill_md_path = skill_dir / "SKILL.md"
    md_content = ""
    if skill_md_path.exists():
        md_content = skill_md_path.read_text(encoding="utf-8")

    # 使用 extract_skill_id 函数生成 skill_id
    # 优先使用 metadata.skill_id，若无则自动生成
    if skill_source == "customized":
        skill_id = extract_skill_id(
            md_content,
            skill_source,
            skill_name,
            creator_id=user_id,
        )
    else:
        skill_id = extract_skill_id(
            md_content,
            skill_source,
            skill_name,
            creator_id="",
        )

    logger.debug(
        "生成 skill_id: skill_name=%s, user_id=%s, source=%s, skill_id=%s",
        skill_name,
        user_id,
        skill_source,
        skill_id,
    )

    # 提取 cn_name
    cn_name = metadata.get("cn_name", "")
    if not cn_name or force:
        if skill_md_path.exists():
            cn_name = extract_cn_name_from_title(md_content)
        if not cn_name:
            cn_name = skill_name

    return skill_id, cn_name


async def _upsert_skill_to_db(
    registry,
    skill_id: str,
    skill_name: str,
    cn_name: str,
    tenant_id: str,
    source_id: str,
    entry: dict,
    metadata: dict,
) -> str | None:
    """写入技能到数据库，返回错误信息或 None."""
    try:
        await registry.upsert_skill_by_name(
            skill_id=skill_id,
            skill_name=skill_name,
            cn_name=cn_name,
            tenant_id=tenant_id,
            tenant_name="",
            bbk_id="",
            source=entry.get("source", "customized"),
            source_id=source_id,
            enabled=entry.get("enabled", False),
            description=metadata.get("description", ""),
            version_text=metadata.get("version_text")
            or metadata.get("received_version")
            or "1.0.0",
        )
        return None
    except Exception as e:
        return str(e)


def _process_skill_entry(
    skill_name: str,
    skill_id: str,
    cn_name: str,
    entry: dict,
) -> dict:
    """更新 entry 中的 metadata 字段."""
    metadata = entry.get("metadata", {})
    metadata["skill_id"] = skill_id
    metadata["cn_name"] = cn_name
    entry["metadata"] = metadata
    return entry


@router.post(
    "/market/admin/skills/init-swe-skills",
)
async def init_swe_skills(
    request: Request,
    payload: _InitSweSkillsRequest,
):
    """初始化 swe_skills 表，将现有技能写入数据库.

    Args:
        payload.source_ids: 租户 source_id 列表
        payload.force: 是否强制重新初始化
        payload.dry_run: 试运行模式
    """
    from ...marketplace.skill_registry import SkillRegistry

    svc = request.app.state.marketplace
    swe_root = svc.swe_root
    registry = SkillRegistry(svc.db)

    results: _InitSweSkillsResult = {
        "dry_run": payload.dry_run,
        "source_ids": payload.source_ids,
        "user_ids": payload.user_ids,
        "total_users": 0,
        "total_skills": 0,
        "processed": 0,
        "inserted_db": 0,
        "skipped": 0,
        "errors": [],
        "details": [],
    }

    if not payload.source_ids:
        logger.warning("source_ids 为空，无数据需要初始化")
        return results

    logger.info(
        "开始初始化 swe_skills 表，dry_run=%s, source_ids=%s, user_ids=%s, force=%s",
        payload.dry_run,
        payload.source_ids,
        payload.user_ids or "(all)",
        payload.force,
    )

    for source_id in payload.source_ids:
        tenant_dirs = _find_tenant_dirs_for_source_id(
            swe_root,
            source_id,
            payload.user_ids,
        )
        results["total_users"] += len(tenant_dirs)

        for tenant_dir in tenant_dirs:
            await _process_tenant_skills(
                tenant_dir,
                source_id,
                registry,
                payload.force,
                payload.dry_run,
                results,
            )

    logger.info(
        "初始化完成: total_users=%d, total_skills=%d, processed=%d, inserted=%d, errors=%d",
        results["total_users"],
        results["total_skills"],
        results["processed"],
        results["inserted_db"],
        len(results["errors"]),
    )

    return results


async def _process_tenant_skills(
    tenant_dir: Path,
    source_id: str,
    registry,
    force: bool,
    dry_run: bool,
    results: _InitSweSkillsResult,
) -> None:
    """处理单个租户下的所有技能."""
    from ...runtime.context import decode_scope_id

    # 从目录名解码出 user_id（数据库 tenant_id）
    dir_name = tenant_dir.name
    user_id = dir_name  # 默认使用目录名

    # 如果是 default_xxx 格式，user_id 是 "default"
    if dir_name.startswith("default_"):
        user_id = "default"
    # 如果是 encode_scope_id 格式（xxx.xxx），解码获取 user_id
    elif "." in dir_name:
        try:
            decoded_user_id, decoded_source = decode_scope_id(dir_name)
            user_id = decoded_user_id
        except ValueError:
            pass

    workspace_base = tenant_dir / "workspaces"
    if not workspace_base.exists():
        return

    logger.info(
        "处理租户目录: dir_name=%s, user_id=%s, source_id=%s",
        dir_name,
        user_id,
        source_id,
    )

    for workspace_dir in workspace_base.iterdir():
        if not workspace_dir.is_dir():
            continue
        await _process_workspace_skills_async(
            workspace_dir,
            user_id,  # 使用解码后的 user_id 作为 tenant_id
            source_id,
            registry,
            force,
            dry_run,
            results,
        )


async def _process_workspace_skills_async(
    workspace_dir: Path,
    user_id: str,
    source_id: str,
    registry,
    force: bool,
    dry_run: bool,
    results: _InitSweSkillsResult,
) -> None:
    """处理单个 workspace 下的所有技能."""
    skills_dir = workspace_dir / "skills"
    manifest_path = workspace_dir / "skill.json"
    agent_id = workspace_dir.name

    if not skills_dir.exists():
        return

    logger.info(
        "读取 workspace manifest: user_id=%s, agent_id=%s, path=%s",
        user_id,
        agent_id,
        manifest_path,
    )

    manifest, error = _read_workspace_manifest(manifest_path)
    if error:
        results["errors"].append(
            {
                "tenant_id": user_id,
                "error": f"skill.json 解析失败: {error}",
            },
        )
        return

    skills_dict = manifest.get("skills", {})

    for skill_dir in skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        await _process_single_skill(
            skill_dir,
            user_id,
            source_id,
            skills_dict,
            registry,
            force,
            dry_run,
            results,
        )

    # 保存 manifest
    if not dry_run and skills_dict:
        manifest["skills"] = skills_dict
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


async def _process_single_skill(
    skill_dir: Path,
    user_id: str,
    source_id: str,
    skills_dict: dict,
    registry,
    force: bool,
    dry_run: bool,
    results: _InitSweSkillsResult,
) -> None:
    """处理单个技能.

    Args:
        skill_dir: 技能目录
        user_id: 用户ID（数据库 tenant_id）
        source_id: 租户 source_id
        skills_dict: skill.json 中的 skills dict
        registry: SkillRegistry
        force: 是否强制重新生成
        dry_run: 试运行模式
        results: 结果统计
    """
    skill_name = skill_dir.name
    results["total_skills"] += 1

    entry = skills_dict.get(skill_name, {})
    skill_id, cn_name = _extract_skill_fields(
        skill_dir,
        entry,
        skill_name,
        user_id,
        source_id,
        force,
    )
    results["processed"] += 1

    # 更新 entry
    skills_dict[skill_name] = _process_skill_entry(
        skill_name,
        skill_id,
        cn_name,
        entry,
    )

    # 写入数据库（tenant_id 使用 user_id）
    if not dry_run:
        metadata = entry.get("metadata", {})
        error = await _upsert_skill_to_db(
            registry,
            skill_id,
            skill_name,
            cn_name,
            user_id,  # 使用 user_id 作为数据库 tenant_id
            source_id,
            entry,
            metadata,
        )
        if error:
            results["errors"].append(
                {
                    "tenant_id": user_id,
                    "skill_name": skill_name,
                    "error": f"数据库写入失败: {error}",
                },
            )
        else:
            results["inserted_db"] += 1

    results["details"].append(
        {
            "tenant_id": user_id,
            "skill_name": skill_name,
            "skill_id": skill_id,
            "cn_name": cn_name,
            "source": entry.get("source", "customized"),
        },
    )

    logger.debug(
        "技能 %s (user_id=%s): skill_id=%s, cn_name=%s",
        skill_name,
        user_id,
        skill_id,
        cn_name,
    )


def _extract_skill_id_from_md(md_content: str) -> str:
    """从 SKILL.md frontmatter 提取 skill_id."""
    if not md_content.startswith("---"):
        return ""
    end_idx = md_content.find("---", 3)
    if end_idx == -1:
        return ""
    frontmatter = md_content[3:end_idx].strip()
    for line in frontmatter.split("\n"):
        if line.startswith("skill_id:"):
            skill_id = line.split(":", 1)[1].strip()
            return skill_id.strip('"').strip("'")
    return ""


def _extract_cn_name_from_md(md_content: str) -> str:
    """从 SKILL.md 提取中文展示名."""
    if not md_content:
        return ""

    # 尝试从 frontmatter metadata.cn_name 提取
    if md_content.startswith("---"):
        end_idx = md_content.find("---", 3)
        if end_idx != -1:
            frontmatter = md_content[3:end_idx].strip()
            for line in frontmatter.split("\n"):
                if line.startswith("cn_name:") or line.startswith(
                    "chinese_name:",
                ):
                    cn_name = line.split(":", 1)[1].strip()
                    return cn_name.strip('"').strip("'")

    # 尝试一级标题
    for line in md_content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("##"):
            title = stripped[1:].strip()
            if title:
                return title

    return ""


@router.get(
    "/market/skills/{item_id}/distributions",
)
async def get_skill_distributions(
    item_id: str,
    request: Request,
    x_source_id: Optional[str] = Header(default=None, alias="X-Source-Id"),
    x_manager: Optional[str] = Header(default=None, alias="X-Manager"),
):
    """查询技能分发记录（管理员）."""
    source_id = require_source_id(x_source_id)
    _require_manager(x_manager)
    svc = request.app.state.marketplace
    distributions = await svc.get_distributions(source_id, item_id, "skill")
    return distributions


class _UpdateSkillRequest(BaseModel):
    """更新技能中文名请求体."""

    skill_id: str
    chinese_name: str
    sync_to_users: bool = False
    target_user_ids: list[str] = Field(default_factory=list)


class _UpdateSkillResponse(BaseModel):
    """更新技能中文名响应体."""

    success: bool
    market_updated: bool
    synced_users: int
    skipped_users: int
    errors: list[dict]


@router.patch("/market/skills/{item_id}")
async def update_skill_cn_name(
    item_id: str,
    req: _UpdateSkillRequest,
    request: Request,
    x_source_id: Optional[str] = Header(default=None, alias="X-Source-Id"),
    x_manager: Optional[str] = Header(default=None, alias="X-Manager"),
):
    """更新市场技能中文名，可选同步用户空间."""
    source_id = require_source_id(x_source_id)
    _require_manager(x_manager)
    svc = request.app.state.marketplace

    # 从 MarketItem 获取 skill_name
    items = load_index(svc.marketplace_root, source_id)
    item = next(
        (i for i in items if i.item_id == item_id and i.item_type == "skill"),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    result = await svc.update_skill_cn_name(
        source_id=source_id,
        item_id=item_id,
        skill_id=req.skill_id,
        skill_name=item.name,
        chinese_name=req.chinese_name,
        sync_to_users=req.sync_to_users,
        target_user_ids=req.target_user_ids,
    )

    return _UpdateSkillResponse(**result)


@router.post(
    "/market/skills/recall",
)
async def recall_skill_by_name(
    request: Request,
    x_source_id: Optional[str] = Header(default=None, alias="X-Source-Id"),
    x_manager: Optional[str] = Header(default=None, alias="X-Manager"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user_name: Optional[str] = Header(default=None, alias="X-User-Name"),
) -> dict:
    """按技能名称撤回（管理员）."""
    from ...marketplace.schemas import RecallRequest

    source_id = require_source_id(x_source_id)
    _require_manager(x_manager)
    svc = request.app.state.marketplace

    # 解析请求体
    body = await request.json()
    target_user_ids = body.get("target_user_ids")
    skill_name = body.get("skill_name")
    req = RecallRequest(
        target_user_ids=target_user_ids,
        skill_name=skill_name,
    )

    try:
        result = await svc.recall_skill(
            source_id,
            None,
            operator_id=x_user_id or "",
            operator_name=decode_user_name(x_user_name) or "",
            req=req,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result.model_dump()


@router.post(
    "/market/skills/{item_id}/recall",
)
async def recall_skill(
    item_id: str,
    request: Request,
    x_source_id: Optional[str] = Header(default=None, alias="X-Source-Id"),
    x_manager: Optional[str] = Header(default=None, alias="X-Manager"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user_name: Optional[str] = Header(default=None, alias="X-User-Name"),
) -> dict:
    """撤回已分发的技能（管理员）."""
    from ...marketplace.schemas import RecallRequest

    source_id = require_source_id(x_source_id)
    _require_manager(x_manager)
    svc = request.app.state.marketplace

    # 解析请求体
    body = await request.json()
    target_user_ids = body.get("target_user_ids")
    force = body.get("force", False)
    req = RecallRequest(
        target_user_ids=target_user_ids,
        force=force,
    )

    try:
        result = await svc.recall_skill(
            source_id,
            item_id,
            operator_id=x_user_id or "",
            operator_name=decode_user_name(x_user_name) or "",
            req=req,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result.model_dump()


class _InitMarketSkillsRequest(BaseModel):
    """初始化市场技能请求参数."""

    source_ids: list[str] = Field(
        default_factory=list,
        description="来源ID列表，不传或为空时初始化所有来源",
    )
    dry_run: bool = Field(
        default=False,
        description="试运行模式，仅统计不实际写入",
    )


class _InitMarketSkillsResult(TypedDict):
    """初始化市场技能返回结果."""

    dry_run: bool
    source_ids: list[str]
    total_items: int
    processed: int
    updated: int
    skipped: int
    errors: list[dict]
    details: list[dict]


def _truncate_chinese_name(cn_name: str, max_length: int = 50) -> str:
    """截断中文名，防止过长."""
    if len(cn_name) > max_length:
        return cn_name[:max_length]
    return cn_name


def _extract_skill_metadata_from_md(
    skill_md_path: Path,
    item_id: str,
    item_name: str,
) -> tuple[str, str]:
    """从 SKILL.md 提取 skill_id 和 chinese_name.

    Args:
        skill_md_path: SKILL.md 文件路径
        item_id: 市场条目 ID
        item_name: 技能名称

    Returns:
        (skill_id, chinese_name)
    """
    from ...utils.skill_md import (
        extract_skill_id,
        extract_cn_name_from_title,
        parse_frontmatter,
    )

    skill_id = ""
    chinese_name = ""

    if not skill_md_path.exists():
        return skill_id, chinese_name

    try:
        md_content = skill_md_path.read_text(encoding="utf-8")

        # 提取 skill_id（市场技能 source 为 marketplace:{item_id}）
        skill_id = extract_skill_id(
            md_content,
            f"marketplace:{item_id}",
            item_name,
            creator_id="",
        )

        # 提取 chinese_name：优先 frontmatter，其次一级标题
        fm = parse_frontmatter(md_content)
        metadata = fm.get("metadata", {})
        if isinstance(metadata, dict):
            chinese_name = metadata.get("cn_name", "") or metadata.get(
                "chinese_name",
                "",
            )
        if not chinese_name:
            chinese_name = extract_cn_name_from_title(md_content)
    except OSError as e:
        logger.warning(
            "读取 SKILL.md 失败: item_id=%s, error=%s",
            item_id,
            e,
        )

    return skill_id, chinese_name


def _process_single_skill_item(
    item: MarketItem,
    marketplace_root: Path,
    source_id: str,
) -> tuple[str, str, bool]:
    """处理单个技能条目，提取 skill_id 和 chinese_name.

    Args:
        item: 市场条目
        marketplace_root: 市场根目录
        source_id: 来源 ID

    Returns:
        (skill_id, chinese_name, needs_update)
    """
    skill_dir = get_skill_dir(marketplace_root, source_id, item.item_id)
    skill_md_path = skill_dir / "SKILL.md"

    # 提取 skill_id 和 chinese_name
    skill_id, chinese_name = _extract_skill_metadata_from_md(
        skill_md_path,
        item.item_id,
        item.name,
    )

    # fallback: skill_id 使用 item_id
    if not skill_id:
        skill_id = item.item_id

    # fallback: chinese_name 使用 MarketItem.chinese_name 或 name
    if not chinese_name:
        chinese_name = item.chinese_name or item.name

    # 截断 chinese_name（最多50字）
    chinese_name = _truncate_chinese_name(chinese_name, 50)

    # 检查是否需要更新
    needs_update = False
    if not item.skill_id and skill_id:
        item.skill_id = skill_id
        needs_update = True
    if not item.chinese_name and chinese_name:
        item.chinese_name = chinese_name
        needs_update = True

    return skill_id, chinese_name, needs_update


def _process_source_id_skills(
    source_id: str,
    marketplace_root: Path,
    dry_run: bool,
    results: _InitMarketSkillsResult,
) -> None:
    """处理单个 source_id 下的所有技能.

    Args:
        source_id: 来源 ID
        marketplace_root: 市场根目录
        dry_run: 试运行模式
        results: 结果统计
    """
    logger.info("处理 source_id=%s", source_id)

    # 加载 index.json
    items = load_index(marketplace_root, source_id)
    logger.debug(
        "加载 index.json: source_id=%s, items=%d",
        source_id,
        len(items),
    )

    # 过滤 skill 类型
    skill_items = [item for item in items if item.item_type == "skill"]
    results["total_items"] += len(skill_items)
    logger.debug(
        "过滤 skill 类型: source_id=%s, skill_items=%d",
        source_id,
        len(skill_items),
    )

    updated_items = []
    for item in skill_items:
        skill_id, chinese_name, needs_update = _process_single_skill_item(
            item,
            marketplace_root,
            source_id,
        )

        results["processed"] += 1

        if needs_update:
            updated_items.append(item)
            results["updated"] += 1
            results["details"].append(
                {
                    "source_id": source_id,
                    "item_id": item.item_id,
                    "name": item.name,
                    "skill_id": skill_id,
                    "chinese_name": chinese_name,
                },
            )
            logger.info(
                "更新条目: source_id=%s, item_id=%s, name=%s, skill_id=%s, chinese_name=%s",
                source_id,
                item.item_id,
                item.name,
                skill_id,
                chinese_name,
            )
        else:
            results["skipped"] += 1
            logger.info(
                "跳过条目（无需更新）: source_id=%s, item_id=%s, name=%s",
                source_id,
                item.item_id,
                item.name,
            )

    # 保存更新后的 index.json（非 dry_run 模式）
    if updated_items and not dry_run:
        save_index(marketplace_root, source_id, items)
        logger.info(
            "保存 index.json: source_id=%s, updated=%d",
            source_id,
            len(updated_items),
        )
    elif updated_items and dry_run:
        logger.info(
            "试运行模式，不保存: source_id=%s, would_update=%d",
            source_id,
            len(updated_items),
        )


@router.post(
    "/market/admin/skills/init-market-skills",
)
async def init_market_skills(
    request: Request,
    payload: _InitMarketSkillsRequest,
):
    """初始化市场技能的 skill_id 和 chinese_name.

    遍历 index.json 中 item_type == "skill" 的条目，
    从 SKILL.md 提取 skill_id 和 chinese_name，
    补充缺失的字段并保存。

    Args:
        payload.source_ids: 来源ID列表，不传或为空时初始化所有来源
        payload.dry_run: 试运行模式，仅统计不实际写入
    """
    svc = request.app.state.marketplace
    marketplace_root = svc.marketplace_root

    results: _InitMarketSkillsResult = {
        "dry_run": payload.dry_run,
        "source_ids": [],
        "total_items": 0,
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "details": [],
    }

    # 确定 source_ids 列表
    if payload.source_ids:
        source_ids = payload.source_ids
    else:
        # 遍历 marketplace_root 下所有目录作为 source_ids
        source_ids = []
        for dir_path in marketplace_root.iterdir():
            if dir_path.is_dir():
                index_path = dir_path / "index.json"
                if index_path.exists():
                    source_ids.append(dir_path.name)

    results["source_ids"] = source_ids

    logger.info(
        "开始初始化市场技能: dry_run=%s, source_ids=%s",
        payload.dry_run,
        source_ids,
    )

    for source_id in source_ids:
        _process_source_id_skills(
            source_id,
            marketplace_root,
            payload.dry_run,
            results,
        )

    logger.info(
        "初始化完成: dry_run=%s, total_items=%d, processed=%d, updated=%d, skipped=%d, errors=%d",
        payload.dry_run,
        results["total_items"],
        results["processed"],
        results["updated"],
        results["skipped"],
        len(results["errors"]),
    )

    return results
