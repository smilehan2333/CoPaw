# -*- coding: utf-8 -*-
"""持续治理历史 workspace 文件回填。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ...config.context import (
    is_valid_identity_value,
    resolve_runtime_tenant_id,
)
from .models import ArchiveItemRecord, CleanupAuditRecord, ProtectedFileRecord
from .models import GOVERNANCE_ID_MAX_LENGTH
from .service import ContinuousGovernanceService

DREAM_LOGS_FILE = "dream_logs.json"
ARCHIVE_INDEX_FILE = "governance/archive/index.json"
PROTECTED_PATHS_FILE = "governance/archive/protected_paths.json"
ARCHIVE_ADMIN_AUDIT_FILE = "governance/archive_admin_audit.jsonl"
DEFAULT_AGENT_ID = "default"
ARCHIVE_RETENTION_DAYS = 10
TARGET_AGENT_ID_MAX_LENGTH = GOVERNANCE_ID_MAX_LENGTH


async def backfill_continuous_governance_source(
    store: Any,
    *,
    workspace_root: Path,
    source_id: str,
    tenants: list[dict[str, Any]],
) -> dict[str, int]:
    """回填指定 source 下可管理用户的历史持续治理数据。"""
    service = ContinuousGovernanceService(store)
    counts = {
        "governance_records": 0,
        "archive_items": 0,
        "protected_files": 0,
        "cleanup_audits": 0,
    }
    for tenant in tenants:
        target_user_id = str(tenant.get("tenant_id") or "")
        if not target_user_id:
            continue
        tenant_dir = workspace_root / (
            resolve_runtime_tenant_id(target_user_id, source_id)
            or target_user_id
        )
        for target_agent_id, workspace_dir in _iter_agent_workspaces(
            tenant_dir,
        ):
            counts["governance_records"] += await _backfill_dream_logs(
                service,
                workspace_dir=workspace_dir,
                source_id=source_id,
                target_user_id=target_user_id,
                target_user_name=tenant.get("tenant_name"),
                bbk_id=tenant.get("bbk_id"),
                target_agent_id=target_agent_id,
            )
            counts["archive_items"] += await _backfill_archive_index(
                store,
                workspace_dir=workspace_dir,
                source_id=source_id,
                target_user_id=target_user_id,
                target_agent_id=target_agent_id,
            )
            counts["protected_files"] += await _backfill_protected_paths(
                store,
                workspace_dir=workspace_dir,
                source_id=source_id,
                target_user_id=target_user_id,
                target_agent_id=target_agent_id,
            )
            counts["cleanup_audits"] += await _backfill_cleanup_audits(
                service,
                workspace_dir=workspace_dir,
                source_id=source_id,
            )
    counts["cleanup_audits"] += await _backfill_source_cleanup_audits(
        service,
        workspace_root=workspace_root,
        source_id=source_id,
    )
    return counts


def _iter_agent_workspaces(tenant_dir: Path) -> list[tuple[str, Path]]:
    """列出用户目录下的 agent workspace。"""
    workspaces_dir = tenant_dir / "workspaces"
    if not workspaces_dir.exists():
        return [(DEFAULT_AGENT_ID, workspaces_dir / DEFAULT_AGENT_ID)]
    return [
        (path.name, path)
        for path in sorted(workspaces_dir.iterdir())
        if path.is_dir() and _is_backfillable_agent_id(path.name)
    ]


def _is_backfillable_agent_id(agent_id: str) -> bool:
    """只回填可作为路径片段且能写入读模型字段的 agent 标识。"""
    return len(
        agent_id,
    ) <= TARGET_AGENT_ID_MAX_LENGTH and is_valid_identity_value(agent_id)


async def _backfill_dream_logs(
    service: ContinuousGovernanceService,
    *,
    workspace_dir: Path,
    source_id: str,
    target_user_id: str,
    target_user_name: str | None,
    bbk_id: str | None,
    target_agent_id: str,
) -> int:
    """导入 dream_logs.json。"""
    data = _load_json(workspace_dir / DREAM_LOGS_FILE, {})
    count = 0
    for record in data.get("records", []):
        if not isinstance(record, dict) or not record.get("id"):
            continue
        await service.upsert_workspace_governance_record(
            source_id=source_id,
            target_user_id=target_user_id,
            target_user_name=target_user_name,
            bbk_id=bbk_id,
            target_agent_id=target_agent_id,
            record=record,
        )
        count += 1
    return count


async def _backfill_archive_index(
    store: Any,
    *,
    workspace_dir: Path,
    source_id: str,
    target_user_id: str,
    target_agent_id: str,
) -> int:
    """导入归档索引。"""
    data = _load_json(workspace_dir / ARCHIVE_INDEX_FILE, {})
    count = 0
    for item in data.get("items", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        await store.upsert_archive_item(
            ArchiveItemRecord(
                source_id=source_id,
                target_user_id=target_user_id,
                target_agent_id=target_agent_id,
                archive_item_id=str(item.get("id") or ""),
                original_path=str(item.get("original_path") or ""),
                archive_path=str(item.get("archive_path") or ""),
                size_bytes=int(item.get("size_bytes") or 0),
                mtime=str(item.get("mtime") or ""),
                archived_at=str(item.get("archived_at") or ""),
                archived_by=str(item.get("archived_by") or ""),
                archive_reason=str(item.get("archive_reason") or ""),
                expired=_archive_item_expired(item),
                raw_item=dict(item),
            ),
        )
        count += 1
    return count


async def _backfill_protected_paths(
    store: Any,
    *,
    workspace_dir: Path,
    source_id: str,
    target_user_id: str,
    target_agent_id: str,
) -> int:
    """导入受保护文件列表。"""
    data = _load_json(workspace_dir / PROTECTED_PATHS_FILE, {})
    count = 0
    for item in data.get("paths", []):
        if not isinstance(item, dict) or not item.get("path"):
            continue
        path = str(item.get("path") or "")
        file_path = workspace_dir / Path(*path.split("/"))
        exists = file_path.exists()
        stat = file_path.stat() if exists else None
        await store.upsert_protected_file(
            ProtectedFileRecord(
                source_id=source_id,
                target_user_id=target_user_id,
                target_agent_id=target_agent_id,
                path=path,
                protected_at=str(item.get("protected_at") or ""),
                protected_by=str(item.get("protected_by") or ""),
                reason=str(item.get("reason") or ""),
                exists=exists,
                size_bytes=stat.st_size if stat else None,
            ),
        )
        count += 1
    return count


async def _backfill_cleanup_audits(
    service: ContinuousGovernanceService,
    *,
    workspace_dir: Path,
    source_id: str,
) -> int:
    """导入管理员清理审计 jsonl。"""
    audit_path = workspace_dir / ARCHIVE_ADMIN_AUDIT_FILE
    if not audit_path.exists():
        return 0
    count = 0
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("source_id") != source_id:
            continue
        await service.upsert_cleanup_audit(record)
        count += 1
    return count


async def _backfill_source_cleanup_audits(
    service: ContinuousGovernanceService,
    *,
    workspace_root: Path,
    source_id: str,
) -> int:
    """导入当前 source 下所有操作者 workspace 里的管理员审计。"""
    count = 0
    for scope_dir in (
        workspace_root.iterdir() if workspace_root.exists() else []
    ):
        if not scope_dir.is_dir() or "." not in scope_dir.name:
            continue
        for _, workspace_dir in _iter_agent_workspaces(scope_dir):
            count += await _backfill_cleanup_audits(
                service,
                workspace_dir=workspace_dir,
                source_id=source_id,
            )
    return count


def _load_json(path: Path, default: Any) -> Any:
    """读取 JSON 文件，缺失或损坏时返回默认值。"""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _archive_item_expired(
    item: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """判断归档条目是否已超过保留期。"""
    archived_at = str(item.get("archived_at") or "")
    if not archived_at:
        return False
    try:
        archived_dt = datetime.fromisoformat(
            archived_at.replace("Z", "+00:00"),
        )
    except ValueError:
        return False
    if archived_dt.tzinfo is None:
        archived_dt = archived_dt.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - archived_dt.astimezone(
        timezone.utc,
    ) >= timedelta(days=ARCHIVE_RETENTION_DAYS)
