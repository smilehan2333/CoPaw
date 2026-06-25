# -*- coding: utf-8 -*-
"""持续治理数据库读模型服务测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swe.app.continuous_governance.models import (
    ArchiveItemRecord,
    CleanupAuditRecord,
    GovernanceRecord,
    ProtectedFileRecord,
    ReconcileHealthRecord,
)
from swe.app.continuous_governance.service import ContinuousGovernanceService


class _FakeStore:
    """用内存数据验证 service 聚合语义。"""

    def __init__(self) -> None:
        self.records: list[GovernanceRecord] = []
        self.archive_items: list[ArchiveItemRecord] = []
        self.protected_files: list[ProtectedFileRecord] = []
        self.audits: list[CleanupAuditRecord] = []
        self.health: list[ReconcileHealthRecord] = []
        self.rollback_calls: list[dict] = []
        self.deleted_archive_items: list[tuple[str, str, str, str]] = []

    async def list_governance_records(self, source_id: str, **filters):
        """按 source 与记录筛选条件返回治理记录。"""
        rows = [row for row in self.records if row.source_id == source_id]
        target_user_ids = filters.get("target_user_ids")
        if target_user_ids is not None:
            rows = [
                row for row in rows if row.target_user_id in target_user_ids
            ]
        if filters.get("target_agent_id"):
            rows = [
                row
                for row in rows
                if row.target_agent_id == filters["target_agent_id"]
            ]
        if filters.get("status"):
            rows = [row for row in rows if row.status == filters["status"]]
        if filters.get("trigger"):
            rows = [row for row in rows if row.trigger == filters["trigger"]]
        return rows

    async def list_archive_items(self, source_id: str, **filters):
        """返回文件归档状态。"""
        return [
            row for row in self.archive_items if row.source_id == source_id
        ]

    async def list_protected_files(self, source_id: str, **filters):
        """返回文件保护状态。"""
        return [
            row for row in self.protected_files if row.source_id == source_id
        ]

    async def list_cleanup_audits(self, source_id: str, **filters):
        """返回管理员清理审计。"""
        return [row for row in self.audits if row.source_id == source_id]

    async def list_reconcile_health(self, source_id: str):
        """返回待对账健康状态。"""
        return [row for row in self.health if row.source_id == source_id]

    async def upsert_governance_record(self, record: GovernanceRecord):
        """记录写入的治理记录。"""
        self.records.append(record)

    async def mark_governance_record_rollback(self, **kwargs):
        """记录回滚更新调用。"""
        self.rollback_calls.append(kwargs)
        return True

    async def upsert_archive_item(self, record: ArchiveItemRecord):
        """记录写入的归档状态。"""
        self.archive_items.append(record)

    async def delete_archive_item(self, **kwargs):
        """记录删除的归档状态。"""
        self.deleted_archive_items.append(
            (
                kwargs["source_id"],
                kwargs["target_user_id"],
                kwargs["target_agent_id"],
                kwargs["archive_item_id"],
            ),
        )
        return True

    async def upsert_protected_file(self, record: ProtectedFileRecord):
        """记录写入的保护状态。"""
        self.protected_files.append(record)

    async def delete_protected_file(self, **kwargs):
        """记录删除的保护状态。"""
        self.protected_files = [
            row
            for row in self.protected_files
            if not (
                row.source_id == kwargs["source_id"]
                and row.target_user_id == kwargs["target_user_id"]
                and row.target_agent_id == kwargs["target_agent_id"]
                and row.path == kwargs["path"]
            )
        ]
        return True

    async def upsert_cleanup_audit(self, record: CleanupAuditRecord):
        """记录写入的清理审计。"""
        self.audits.append(record)

    async def upsert_reconcile_health(self, record: ReconcileHealthRecord):
        """记录写入的对账健康状态。"""
        self.health = [
            row
            for row in self.health
            if not (
                row.source_id == record.source_id
                and row.target_user_id == record.target_user_id
                and row.target_agent_id == record.target_agent_id
                and row.entity_type == record.entity_type
                and row.entity_id == record.entity_id
            )
        ]
        self.health.append(record)


class _FailingGovernanceStore(_FakeStore):
    """模拟主写入失败但 health 可写的存储。"""

    async def upsert_governance_record(self, record: GovernanceRecord):
        """治理记录写入失败。"""
        raise RuntimeError("db timeout")


class _MissingRollbackStore(_FakeStore):
    """模拟 rollback 对账找不到原始治理记录。"""

    async def mark_governance_record_rollback(self, **kwargs):
        """记录调用并返回空更新。"""
        self.rollback_calls.append(kwargs)
        return False


class _FailingArchiveStore(_FakeStore):
    """模拟对账重放时文件治理写入失败。"""

    async def upsert_archive_item(self, record: ArchiveItemRecord):
        """归档状态写入失败。"""
        raise RuntimeError("archive db timeout")


def _record(
    record_id: str,
    user_id: str,
    status: str,
    trigger: str = "manual",
) -> GovernanceRecord:
    """构造治理记录。"""
    return GovernanceRecord(
        source_id="source-a",
        target_user_id=user_id,
        target_user_name=user_id.title(),
        bbk_id="bbk-1",
        target_agent_id="default",
        record_id=record_id,
        timestamp=f"2026-05-2{len(record_id)}T09:00:00Z",
        trigger=trigger,
        status=status,
        files_optimized=["MEMORY.md"],
        total_size_saved=100 if status == "success" else 0,
        total_files_changed=1 if status == "success" else 0,
        duration_ms=1000,
        model_used="gpt-test",
        input_tokens=10,
        output_tokens=20,
        summary="ok",
        error="bad response" if status == "failed" else None,
    )


@pytest.mark.asyncio
async def test_report_counts_failed_and_rollback_as_governed() -> None:
    """有任意治理记录的覆盖用户都算已治理，成功率只统计 success。"""
    store = _FakeStore()
    store.records = [
        _record("r1", "alice", "success"),
        _record("r2", "bob", "failed"),
        _record("r3", "carol", "rollback", trigger="cron"),
    ]
    service = ContinuousGovernanceService(store)

    report = await service.build_governance_report(
        source_id="source-a",
        tenants=[
            {"tenant_id": "alice", "tenant_name": "Alice", "bbk_id": "bbk-1"},
            {"tenant_id": "bob", "tenant_name": "Bob", "bbk_id": "bbk-1"},
            {"tenant_id": "carol", "tenant_name": "Carol", "bbk_id": None},
            {"tenant_id": "dave", "tenant_name": "Dave", "bbk_id": "bbk-2"},
        ],
        page=1,
        page_size=20,
    )

    assert report.summary.covered_users == 4
    assert report.summary.governed_users == 3
    assert report.summary.ungoverned_users == 1
    assert report.summary.total_executions == 3
    assert report.summary.success_count == 1
    assert report.summary.failed_count == 1
    assert report.summary.success_rate == 33.33
    assert report.total == 3
    assert {row.user_id for row in report.users} == {"alice", "bob", "carol"}
    assert all(row.executions > 0 for row in report.users)
    assert [
        (bucket.bbk_id, bucket.user_count, bucket.executions)
        for bucket in report.bbk_distribution
    ] == [("bbk-1", 2, 2), ("other", 1, 1)]
    assert [
        (point.executions, point.manual_count, point.cron_count)
        for point in report.trends
    ] == [(3, 2, 1)]


@pytest.mark.asyncio
async def test_record_filters_do_not_change_file_state_report() -> None:
    """记录筛选只影响治理记录指标，不影响文件治理状态报告。"""
    store = _FakeStore()
    store.records = [_record("r1", "alice", "failed")]
    store.archive_items = [
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
            expired=True,
        ),
    ]
    store.protected_files = [
        ProtectedFileRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            path="notes.md",
            protected_at="2026-05-24T11:00:00Z",
            protected_by="admin",
            reason="manual",
            exists=True,
            size_bytes=42,
            mtime=None,
        ),
    ]
    service = ContinuousGovernanceService(store)

    report = await service.build_archive_report(
        source_id="source-a",
        tenants=[{"tenant_id": "alice"}],
        status="success",
        trigger="cron",
    )

    assert report.summary.archived_files == 1
    assert report.summary.pending_purge_files == 1
    assert report.summary.protected_files == 1


@pytest.mark.asyncio
async def test_archive_report_calculates_expired_from_archived_at() -> None:
    """文件治理报表应按 archived_at 动态判断待清理状态。"""
    store = _FakeStore()
    store.archive_items = [
        ArchiveItemRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            archive_item_id="archive-1",
            original_path="notes.md",
            archive_path="governance/archive/files/archive-1",
            size_bytes=42,
            mtime="2026-05-01T09:00:00Z",
            archived_at="2026-05-01T10:00:00Z",
            archived_by="admin",
            archive_reason="manual",
            expired=False,
        ),
    ]
    service = ContinuousGovernanceService(store)

    report = await service.build_archive_report(
        source_id="source-a",
        tenants=[{"tenant_id": "alice"}],
    )

    assert report.summary.archived_files == 1
    assert report.summary.pending_purge_files == 1
    assert report.summary.pending_purge_size_bytes == 42


@pytest.mark.asyncio
async def test_health_is_returned_separately_from_core_metrics() -> None:
    """待对账状态不能混入已提交成功指标。"""
    store = _FakeStore()
    store.records = [_record("r1", "alice", "success")]
    store.health = [
        ReconcileHealthRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            entity_type="governance_record",
            entity_id="r2",
            status="pending",
            reason="workspace saved but db write failed",
            error="timeout",
            payload={"record_id": "r2"},
            updated_at=datetime.now(timezone.utc),
        ),
    ]
    service = ContinuousGovernanceService(store)

    report = await service.build_governance_report(
        source_id="source-a",
        tenants=[{"tenant_id": "alice"}],
        page=1,
        page_size=20,
    )

    assert report.summary.total_executions == 1
    assert len(report.health) == 1
    assert report.health[0].status == "pending"


@pytest.mark.asyncio
async def test_upsert_workspace_governance_record_dual_writes_identity() -> (
    None
):
    """workspace 治理记录应转换为 source-scoped 数据库行。"""
    store = _FakeStore()
    service = ContinuousGovernanceService(store)

    await service.upsert_workspace_governance_record(
        source_id="source-a",
        target_user_id="alice",
        target_user_name="Alice",
        bbk_id="bbk-1",
        target_agent_id="default",
        record={
            "id": "record-1",
            "timestamp": "2026-05-24T09:00:00Z",
            "trigger": "manual",
            "status": "success",
            "files_optimized": ["MEMORY.md"],
            "total_size_saved": 42,
            "total_files_changed": 1,
            "duration_ms": 1000,
            "model_used": "gpt-test",
            "input_tokens": 10,
            "output_tokens": 20,
            "summary": "ok",
            "error": None,
        },
    )

    written = store.records[0]
    assert written.source_id == "source-a"
    assert written.target_user_id == "alice"
    assert written.record_id == "record-1"
    assert written.total_size_saved == 42
    assert written.raw_record["id"] == "record-1"


@pytest.mark.asyncio
async def test_dual_write_failure_records_reconcile_health() -> None:
    """workspace 已写但 DB 主写失败时应登记待对账 health。"""
    store = _FailingGovernanceStore()
    service = ContinuousGovernanceService(store)

    await service.upsert_workspace_governance_record_with_health(
        source_id="source-a",
        target_user_id="alice",
        target_user_name="Alice",
        bbk_id="bbk-1",
        target_agent_id="default",
        record={"id": "record-1", "timestamp": "2026-05-24T09:00:00Z"},
    )

    assert len(store.health) == 1
    assert store.health[0].entity_type == "governance_record"
    assert store.health[0].entity_id == "record-1"
    assert store.health[0].status == "reconcile_needed"
    assert store.health[0].payload["target_user_name"] == "Alice"
    assert store.health[0].payload["bbk_id"] == "bbk-1"


@pytest.mark.asyncio
async def test_dual_write_failure_hashes_overlong_health_entity_id() -> None:
    """health 唯一键不得因超长治理记录 id 再次写入失败。"""
    store = _FailingGovernanceStore()
    service = ContinuousGovernanceService(store)
    record_id = "r" * 129

    await service.upsert_workspace_governance_record_with_health(
        source_id="source-a",
        target_user_id="alice",
        target_user_name="Alice",
        bbk_id="bbk-1",
        target_agent_id="default",
        record={"id": record_id, "timestamp": "2026-05-24T09:00:00Z"},
    )

    assert len(store.health) == 1
    assert store.health[0].entity_type == "governance_record"
    assert store.health[0].entity_id.startswith("governance_record:")
    assert len(store.health[0].entity_id) <= 128
    assert store.health[0].payload["record"]["id"] == record_id


@pytest.mark.asyncio
async def test_reconcile_health_replays_payloads_and_marks_resolved() -> None:
    """显式对账应重放 health payload，并把成功项移出待处理列表。"""
    store = _FakeStore()
    store.health = [
        ReconcileHealthRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            entity_type="governance_record",
            entity_id="record-1",
            status="reconcile_needed",
            reason="db write failed",
            error="timeout",
            payload={
                "record": {
                    "id": "record-1",
                    "timestamp": "2026-05-24T09:00:00Z",
                    "status": "success",
                },
            },
            updated_at=datetime.now(timezone.utc),
        ),
        ReconcileHealthRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            entity_type="archive_items",
            entity_id="archive-1",
            status="reconcile_needed",
            reason="db write failed",
            error="timeout",
            payload={
                "items": [
                    {
                        "id": "archive-1",
                        "original_path": "notes.md",
                        "archive_path": "governance/archive/files/archive-1",
                        "size_bytes": 42,
                        "mtime": "2026-05-24T08:00:00Z",
                        "archived_at": "2026-05-24T09:00:00Z",
                    },
                ],
            },
            updated_at=datetime.now(timezone.utc),
        ),
    ]
    service = ContinuousGovernanceService(store)

    result = await service.reconcile_health(source_id="source-a")

    assert result == {"processed": 2, "resolved": 2, "failed": 0}
    assert store.records[0].record_id == "record-1"
    assert store.archive_items[0].archive_item_id == "archive-1"
    assert {row.status for row in store.health} == {"resolved"}


@pytest.mark.asyncio
async def test_reconcile_health_replays_rollback_timestamp() -> None:
    """rollback 对账回放应使用 payload 中的实际回滚时间。"""
    store = _FakeStore()
    store.health = [
        ReconcileHealthRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            entity_type="governance_record",
            entity_id="record-1",
            status="reconcile_needed",
            reason="db write failed",
            error="timeout",
            payload={
                "record_id": "record-1",
                "rollback_timestamp": "2026-05-25T09:00:00Z",
                "rollback_files": ["MEMORY.md"],
            },
            updated_at=datetime(2026, 5, 26, tzinfo=timezone.utc),
        ),
    ]
    service = ContinuousGovernanceService(store)

    result = await service.reconcile_health(source_id="source-a")

    assert result == {"processed": 1, "resolved": 1, "failed": 0}
    assert store.rollback_calls[0]["rollback_timestamp"] == (
        "2026-05-25T09:00:00Z"
    )


@pytest.mark.asyncio
async def test_reconcile_health_keeps_missing_rollback_failed() -> None:
    """rollback 对账空更新时不得标记为 resolved。"""
    store = _MissingRollbackStore()
    store.health = [
        ReconcileHealthRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            entity_type="governance_record",
            entity_id="record-missing",
            status="reconcile_needed",
            reason="db write failed",
            error="timeout",
            payload={
                "record_id": "record-missing",
                "rollback_timestamp": "2026-05-25T09:00:00Z",
                "rollback_files": ["MEMORY.md"],
            },
            updated_at=datetime(2026, 5, 26, tzinfo=timezone.utc),
        ),
    ]
    service = ContinuousGovernanceService(store)

    result = await service.reconcile_health(source_id="source-a")

    assert result == {"processed": 1, "resolved": 0, "failed": 1}
    assert store.health[0].status == "failed"
    assert "target record was not found" in (store.health[0].error or "")


@pytest.mark.asyncio
async def test_reconcile_health_replays_restore_protected_metadata() -> None:
    """恢复后保护对账回放应使用 payload 中的保护元数据。"""
    store = _FakeStore()
    store.health = [
        ReconcileHealthRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            entity_type="archive_restore",
            entity_id="archive-1",
            status="reconcile_needed",
            reason="db write failed",
            error="timeout",
            payload={
                "archive_item_id": "archive-1",
                "original_path": "restored.md",
                "protect_after_restore": True,
                "protected_at": "2026-05-25T09:00:00Z",
                "protected_by": "admin",
                "exists": True,
                "size_bytes": 3,
                "mtime": "2026-05-25T09:00:00Z",
            },
            updated_at=datetime(2026, 5, 26, tzinfo=timezone.utc),
        ),
    ]
    service = ContinuousGovernanceService(store)

    result = await service.reconcile_health(source_id="source-a")

    assert result == {"processed": 1, "resolved": 1, "failed": 0}
    assert store.deleted_archive_items[0] == (
        "source-a",
        "alice",
        "default",
        "archive-1",
    )
    protected = store.protected_files[0]
    assert protected.path == "restored.md"
    assert protected.protected_at == "2026-05-25T09:00:00Z"
    assert protected.protected_by == "admin"
    assert protected.exists is True
    assert protected.size_bytes == 3


@pytest.mark.asyncio
async def test_reconcile_health_marks_failed_when_replay_fails() -> None:
    """对账重放失败时应保留 health，并更新为 failed。"""
    store = _FailingArchiveStore()
    store.health = [
        ReconcileHealthRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            entity_type="archive_items",
            entity_id="archive-1",
            status="reconcile_needed",
            reason="db write failed",
            error="timeout",
            payload={"items": [{"id": "archive-1"}]},
            updated_at=datetime.now(timezone.utc),
        ),
    ]
    service = ContinuousGovernanceService(store)

    result = await service.reconcile_health(source_id="source-a")

    assert result == {"processed": 1, "resolved": 0, "failed": 1}
    assert store.health[0].status == "failed"
    assert "archive db timeout" in (store.health[0].error or "")


@pytest.mark.asyncio
async def test_file_governance_helpers_write_state_and_audit() -> None:
    """文件治理 action 应写入文件状态与清理审计读模型。"""
    store = _FakeStore()
    service = ContinuousGovernanceService(store)

    await service.upsert_archive_items(
        source_id="source-a",
        target_user_id="alice",
        target_agent_id="default",
        items=[
            {
                "id": "archive-1",
                "original_path": "notes.md",
                "archive_path": "governance/archive/files/archive-1",
                "size_bytes": 42,
                "mtime": "2026-05-24T09:00:00Z",
                "archived_at": "2026-05-24T10:00:00Z",
                "archived_by": "admin",
                "archive_reason": "manual",
            },
        ],
    )
    await service.upsert_cleanup_audit(
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
            "total_size_bytes": 42,
            "reason": "manual",
        },
    )

    assert store.archive_items[0].archive_item_id == "archive-1"
    assert store.audits[0].event_id == "audit-1"


@pytest.mark.asyncio
async def test_rollback_updates_original_database_record() -> None:
    """rollback 应更新原始治理记录。"""
    store = _FakeStore()
    service = ContinuousGovernanceService(store)

    await service.mark_governance_record_rollback(
        source_id="source-a",
        target_user_id="alice",
        target_agent_id="default",
        record_id="record-1",
        rollback_timestamp="2026-05-25T09:00:00Z",
        rollback_files=["MEMORY.md"],
    )

    assert store.rollback_calls[0]["record_id"] == "record-1"
    assert store.rollback_calls[0]["rollback_files"] == ["MEMORY.md"]
