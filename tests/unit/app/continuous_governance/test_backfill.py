# -*- coding: utf-8 -*-
"""持续治理历史数据回填测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swe.app.continuous_governance.backfill import (
    ARCHIVE_RETENTION_DAYS,
    TARGET_AGENT_ID_MAX_LENGTH,
    _is_backfillable_agent_id,
    backfill_continuous_governance_source,
)
from swe.app.continuous_governance.models import (
    ArchiveItemRecord,
    CleanupAuditRecord,
    GovernanceRecord,
    ProtectedFileRecord,
)
from swe.config.context import encode_scope_id


class _IdempotentStore:
    """用稳定业务键模拟数据库 upsert 幂等性。"""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, str], GovernanceRecord] = {}
        self.archive_items: dict[
            tuple[str, str, str, str],
            ArchiveItemRecord,
        ] = {}
        self.protected_files: dict[
            tuple[str, str, str, str],
            ProtectedFileRecord,
        ] = {}
        self.audits: dict[str, CleanupAuditRecord] = {}

    async def upsert_governance_record(self, record: GovernanceRecord):
        """按治理记录业务键幂等写入。"""
        self.records[
            (
                record.source_id,
                record.target_user_id,
                record.target_agent_id,
                record.record_id,
            )
        ] = record

    async def upsert_archive_item(self, record: ArchiveItemRecord):
        """按归档条目业务键幂等写入。"""
        self.archive_items[
            (
                record.source_id,
                record.target_user_id,
                record.target_agent_id,
                record.archive_item_id,
            )
        ] = record

    async def upsert_protected_file(self, record: ProtectedFileRecord):
        """按保护文件业务键幂等写入。"""
        self.protected_files[
            (
                record.source_id,
                record.target_user_id,
                record.target_agent_id,
                record.path,
            )
        ] = record

    async def upsert_cleanup_audit(self, record: CleanupAuditRecord):
        """按审计事件幂等写入。"""
        self.audits[record.event_id] = record


def _workspace(root: Path, tenant_id: str, source_id: str) -> Path:
    """创建测试 workspace。"""
    path = (
        root / encode_scope_id(tenant_id, source_id) / "workspaces" / "default"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.asyncio
async def test_backfill_imports_workspace_files_idempotently(tmp_path) -> None:
    """重复回填不会导入重复治理记录、文件状态或审计。"""
    workspace = _workspace(tmp_path, "alice", "source-a")
    (workspace / "dream_logs.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "record-1",
                        "timestamp": "2026-05-24T09:00:00Z",
                        "trigger": "manual",
                        "status": "success",
                        "files_optimized": ["MEMORY.md"],
                        "total_size_saved": 42,
                        "total_files_changed": 1,
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    archive_index = workspace / "governance" / "archive" / "index.json"
    archive_index.parent.mkdir(parents=True, exist_ok=True)
    archive_index.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {
                        "id": "archive-1",
                        "original_path": "old.md",
                        "archive_path": "governance/archive/files/archive-1",
                        "size_bytes": 10,
                        "mtime": "2026-05-24T09:00:00Z",
                        "archived_at": "2000-01-01T00:00:00Z",
                        "archived_by": "admin",
                        "archive_reason": "manual",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    protected = workspace / "governance" / "archive" / "protected_paths.json"
    protected.write_text(
        json.dumps(
            {
                "version": 1,
                "paths": [
                    {
                        "path": "old.md",
                        "protected_at": "2026-05-24T11:00:00Z",
                        "protected_by": "admin",
                        "reason": "manual",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    admin_workspace = _workspace(tmp_path, "manager", "source-a")
    audit = admin_workspace / "governance" / "archive_admin_audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(
        json.dumps(
            {
                "event_id": "audit-1",
                "timestamp": "2026-05-24T12:00:00Z",
                "operation": "purge_archive",
                "status": "success",
                "actor_user_id": "admin",
                "actor_role": "manager",
                "source_id": "source-a",
                "target_user_id": "alice",
                "target_agent_id": "default",
                "scope": "selected",
                "files_count": 1,
                "total_size_bytes": 10,
                "reason": "manual",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    store = _IdempotentStore()

    for _ in range(2):
        await backfill_continuous_governance_source(
            store,
            workspace_root=tmp_path,
            source_id="source-a",
            tenants=[
                {
                    "tenant_id": "alice",
                    "tenant_name": "Alice",
                    "bbk_id": "bbk-1",
                },
            ],
        )

    assert len(store.records) == 1
    assert len(store.archive_items) == 1
    assert ARCHIVE_RETENTION_DAYS == 10
    assert next(iter(store.archive_items.values())).expired is True
    assert len(store.protected_files) == 1
    assert len(store.audits) == 1
    assert next(iter(store.records.values())).target_user_name == "Alice"


@pytest.mark.asyncio
async def test_backfill_skips_agent_ids_that_are_not_safe_path_segments(
    tmp_path,
) -> None:
    """历史目录名不能作为安全路径片段时不导入，避免回填批次中断。"""
    workspace = _workspace(tmp_path, "alice", "source-a")
    (workspace / "dream_logs.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "record-default",
                        "timestamp": "2026-05-24T09:00:00Z",
                        "trigger": "manual",
                        "status": "success",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    invalid_agent_workspace = (
        tmp_path
        / encode_scope_id("alice", "source-a")
        / "workspaces"
        / "bad..agent"
    )
    invalid_agent_workspace.mkdir(parents=True)
    (invalid_agent_workspace / "dream_logs.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "record-overlong",
                        "timestamp": "2026-05-24T09:00:00Z",
                        "trigger": "manual",
                        "status": "success",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    store = _IdempotentStore()

    await backfill_continuous_governance_source(
        store,
        workspace_root=tmp_path,
        source_id="source-a",
        tenants=[{"tenant_id": "alice"}],
    )

    assert len(store.records) == 1
    assert next(iter(store.records.values())).record_id == "record-default"


def test_backfill_agent_id_length_matches_read_model() -> None:
    """agent 标识长度边界与数据库读模型字段保持一致。"""
    assert _is_backfillable_agent_id("a" * TARGET_AGENT_ID_MAX_LENGTH) is True
    assert (
        _is_backfillable_agent_id("a" * (TARGET_AGENT_ID_MAX_LENGTH + 1))
        is False
    )
