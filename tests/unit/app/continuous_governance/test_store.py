# -*- coding: utf-8 -*-
"""持续治理数据库读模型存储测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from swe.app.continuous_governance.models import (
    ArchiveItemRecord,
    CleanupAuditRecord,
    GovernanceRecord,
    ProtectedFileRecord,
    ReconcileHealthRecord,
)
from swe.app.continuous_governance.store import (
    ContinuousGovernanceStore,
    ContinuousGovernanceStoreUnavailable,
)


@pytest.fixture
def mock_db():
    """创建可断言 SQL 调用的数据库 mock。"""
    db = MagicMock()
    db.is_connected = True
    db.execute = AsyncMock(return_value=1)
    db.fetch_all = AsyncMock(return_value=[])
    db.fetch_one = AsyncMock(return_value=None)
    return db


@pytest.fixture
def store(mock_db):
    """创建持续治理存储。"""
    return ContinuousGovernanceStore(mock_db)


def _record() -> GovernanceRecord:
    """构造最小有效治理记录。"""
    return GovernanceRecord(
        source_id="source-a",
        target_user_id="alice",
        target_user_name="Alice",
        bbk_id="bbk-1",
        target_agent_id="default",
        record_id="record-1",
        timestamp="2026-05-24T09:00:00Z",
        trigger="manual",
        status="success",
        files_optimized=["MEMORY.md"],
        total_size_saved=200,
        total_files_changed=1,
        duration_ms=1000,
        model_used="gpt-test",
        input_tokens=10,
        output_tokens=20,
        summary="ok",
        error=None,
        raw_record={"id": "record-1"},
    )


@pytest.mark.asyncio
async def test_unavailable_store_raises_specific_error() -> None:
    """数据库不可用时不能静默返回空报表。"""
    store = ContinuousGovernanceStore(None)

    with pytest.raises(ContinuousGovernanceStoreUnavailable):
        await store.list_governance_records("source-a")


@pytest.mark.asyncio
async def test_upsert_governance_record_uses_source_user_agent_record_key(
    store,
    mock_db,
) -> None:
    """治理记录按 source、逻辑用户、agent 和记录 id 幂等写入。"""
    await store.upsert_governance_record(_record())

    query, params = mock_db.execute.await_args.args
    assert "swe_continuous_governance_records" in query
    assert "ON DUPLICATE KEY UPDATE" in query
    assert params[:4] == (
        "source-a",
        "alice",
        "default",
        "record-1",
    )
    assert json.loads(params[12]) == ["MEMORY.md"]
    assert json.loads(params[-1]) == {"id": "record-1"}


@pytest.mark.asyncio
async def test_mark_rollback_updates_original_record(store, mock_db) -> None:
    """回滚更新原治理记录，不生成新记录。"""
    await store.mark_governance_record_rollback(
        source_id="source-a",
        target_user_id="alice",
        target_agent_id="default",
        record_id="record-1",
        rollback_timestamp="2026-05-25T09:00:00Z",
        rollback_files=["MEMORY.md"],
    )

    query, params = mock_db.execute.await_args.args
    assert query.lstrip().startswith("UPDATE")
    assert "status = 'rollback'" in query
    assert json.loads(params[1]) == ["MEMORY.md"]
    assert params[-4:] == ("source-a", "alice", "default", "record-1")


@pytest.mark.asyncio
async def test_time_filters_are_bound_as_iso_strings(store, mock_db) -> None:
    """VARCHAR 时间列必须使用 ISO 字符串参数，避免空格和 T 的字典序问题。"""
    start_time = datetime(2026, 5, 24, tzinfo=timezone.utc)
    end_time = datetime(2026, 5, 24, 23, 59, 59, tzinfo=timezone.utc)

    await store.list_governance_records(
        "source-a",
        start_time=start_time,
        end_time=end_time,
    )

    _, params = mock_db.fetch_all.await_args.args
    assert params[1] == "2026-05-24T00:00:00Z"
    assert params[2] == "2026-05-24T23:59:59Z"


@pytest.mark.asyncio
async def test_archive_and_protected_state_are_idempotent(
    store,
    mock_db,
) -> None:
    """文件治理状态使用稳定业务键做 upsert。"""
    await store.upsert_archive_item(
        ArchiveItemRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            archive_item_id="archive-1",
            original_path="notes.md",
            archive_path="governance/archive/files/archive-1",
            size_bytes=42,
            mtime="2026-05-24T09:00:00Z",
            archived_at="2026-05-24T10:00:00Z",
            archived_by="admin",
            archive_reason="manual",
            expired=False,
            raw_item={"id": "archive-1"},
        ),
    )
    await store.upsert_protected_file(
        ProtectedFileRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            path="notes.md",
            protected_at="2026-05-24T11:00:00Z",
            protected_by="admin",
            reason="restored_from_archive",
            exists=True,
            size_bytes=42,
            mtime="2026-05-24T09:00:00Z",
        ),
    )

    archive_query = mock_db.execute.await_args_list[0].args[0]
    protected_query = mock_db.execute.await_args_list[1].args[0]
    assert "swe_file_governance_archive_items" in archive_query
    assert "ON DUPLICATE KEY UPDATE" in archive_query
    assert "swe_file_governance_protected_files" in protected_query
    assert "ON DUPLICATE KEY UPDATE" in protected_query


@pytest.mark.asyncio
async def test_cleanup_audit_and_health_are_written(store, mock_db) -> None:
    """清理审计和对账健康状态需要稳定落库。"""
    await store.upsert_cleanup_audit(
        CleanupAuditRecord(
            event_id="audit-1",
            timestamp="2026-05-24T11:00:00Z",
            operation="purge_archive",
            status="success",
            actor_user_id="admin",
            actor_role="manager",
            source_id="source-a",
            source_name="Source A",
            target_user_id="alice",
            target_agent_id="default",
            scope="selected",
            files_count=1,
            total_size_bytes=42,
            reason="manual",
            error=None,
            raw_audit={"event_id": "audit-1"},
        ),
    )
    await store.upsert_reconcile_health(
        ReconcileHealthRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            entity_type="governance_record",
            entity_id="record-1",
            status="pending",
            reason="db write failed",
            error="timeout",
            payload={"record_id": "record-1"},
            updated_at=datetime.now(timezone.utc),
        ),
    )

    audit_query = mock_db.execute.await_args_list[0].args[0]
    health_query = mock_db.execute.await_args_list[1].args[0]
    assert "swe_file_governance_cleanup_audits" in audit_query
    assert "source_id = VALUES(source_id)" not in audit_query
    assert "swe_continuous_governance_reconcile_health" in health_query
    assert "ON DUPLICATE KEY UPDATE" in health_query
