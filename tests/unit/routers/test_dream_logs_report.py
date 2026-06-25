# -*- coding: utf-8 -*-
"""持续治理分析报表路由测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from swe.app.continuous_governance.models import (
    ArchiveItemRecord,
    CleanupAuditRecord,
    GovernanceRecord,
    ProtectedFileRecord,
    ReconcileHealthRecord,
)
from swe.app.continuous_governance.service import ContinuousGovernanceService
from swe.app.routers.dream_logs import router
from swe.config.context import encode_scope_id


class _FakeTenantSourceStore:
    """为报表测试提供当前 source 下的可管理用户清单。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[str] = []

    async def get_by_source(self, source_id: str) -> list[dict[str, Any]]:
        """只返回指定 source 的用户，模拟数据库隔离口径。"""
        self.calls.append(source_id)
        return [row for row in self.rows if row.get("source_id") == source_id]


class _FakeContinuousGovernanceStore:
    """为路由测试提供数据库读模型记录。"""

    def __init__(
        self,
        records: list[GovernanceRecord],
        archive_items: list[ArchiveItemRecord] | None = None,
        protected_files: list[ProtectedFileRecord] | None = None,
        audits: list[CleanupAuditRecord] | None = None,
        health: list[ReconcileHealthRecord] | None = None,
        available: bool = True,
    ) -> None:
        self.records = records
        self.archive_items = archive_items or []
        self.protected_files = protected_files or []
        self.audits = audits or []
        self.health = health or []
        self.is_available = available
        self.report_calls: list[dict[str, Any]] = []

    async def list_governance_records(self, source_id: str, **filters):
        """按 service 传入的筛选条件返回治理记录。"""
        self.report_calls.append({"source_id": source_id, **filters})
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

    async def list_reconcile_health(self, source_id: str):
        """报表健康状态在路由测试中保持为空。"""
        return [row for row in self.health if row.source_id == source_id]

    async def list_archive_items(self, source_id: str, **filters):
        """返回归档状态读模型。"""
        return _filter_file_rows(
            [row for row in self.archive_items if row.source_id == source_id],
            filters,
        )

    async def list_protected_files(self, source_id: str, **filters):
        """返回保护状态读模型。"""
        return _filter_file_rows(
            [
                row
                for row in self.protected_files
                if row.source_id == source_id
            ],
            filters,
        )

    async def list_cleanup_audits(self, source_id: str, **filters):
        """返回清理审计读模型。"""
        return _filter_file_rows(
            [row for row in self.audits if row.source_id == source_id],
            filters,
        )


def _filter_file_rows(rows, filters: dict[str, Any]):
    """按用户和 agent 过滤文件治理测试行。"""
    target_user_ids = filters.get("target_user_ids")
    if target_user_ids is not None:
        rows = [row for row in rows if row.target_user_id in target_user_ids]
    if filters.get("target_agent_id"):
        rows = [
            row
            for row in rows
            if row.target_agent_id == filters["target_agent_id"]
        ]
    return rows


def _dream_record(
    record_id: str,
    *,
    timestamp: str,
    status: str = "success",
    trigger: str = "manual",
    size_saved: int = 100,
    files_changed: int = 1,
    duration_ms: int = 1000,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "timestamp": timestamp,
        "trigger": trigger,
        "status": status,
        "files_optimized": ["MEMORY.md"],
        "file_stats": {
            "MEMORY.md": {
                "size_before": 1000,
                "size_after": 1000 - size_saved,
                "size_saved": size_saved,
                "lines_before": 40,
                "lines_after": 30,
                "lines_removed": 10,
                "backup_path": "backup/memory.md",
            },
        },
        "total_size_saved": size_saved,
        "total_files_changed": files_changed,
        "duration_ms": duration_ms,
        "model_used": "gpt-test",
        "input_tokens": 10,
        "output_tokens": 20,
        "summary": "ok",
        "error": error,
    }


def _governance_record(
    record_id: str,
    target_user_id: str,
    *,
    target_user_name: str | None = None,
    bbk_id: str | None = None,
    timestamp: str,
    status: str = "success",
    trigger: str = "manual",
    size_saved: int = 100,
    files_changed: int = 1,
    duration_ms: int = 1000,
    error: str | None = None,
    source_id: str = "source-a",
    agent_id: str = "default",
) -> GovernanceRecord:
    """构造数据库读模型治理记录。"""
    return GovernanceRecord(
        source_id=source_id,
        target_user_id=target_user_id,
        target_user_name=target_user_name,
        bbk_id=bbk_id,
        target_agent_id=agent_id,
        record_id=record_id,
        timestamp=timestamp,
        trigger=trigger,
        status=status,
        files_optimized=["MEMORY.md"],
        total_size_saved=size_saved,
        total_files_changed=files_changed,
        duration_ms=duration_ms,
        model_used="gpt-test",
        input_tokens=10,
        output_tokens=20,
        summary="ok",
        error=error,
    )


def _tenant_agent_dir(
    base_dir: Path,
    tenant_id: str,
    source_id: str,
    agent_id: str = "default",
) -> Path:
    workspace_dir = (
        base_dir
        / encode_scope_id(tenant_id, source_id)
        / "workspaces"
        / agent_id
    )
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir


def _write_dream_logs(
    base_dir: Path,
    tenant_id: str,
    source_id: str,
    records: list[dict[str, Any]],
    *,
    agent_id: str = "default",
) -> None:
    workspace_dir = _tenant_agent_dir(base_dir, tenant_id, source_id, agent_id)
    timestamps = [
        timestamp
        for record in records
        if isinstance((timestamp := record.get("timestamp")), str)
    ]
    stats = {
        "total_executions": len(records),
        "success_count": sum(
            1 for record in records if record["status"] == "success"
        ),
        "failed_count": sum(
            1 for record in records if record["status"] == "failed"
        ),
        "total_size_saved": sum(
            record.get("total_size_saved", 0) for record in records
        ),
        "total_files_changed": sum(
            record.get("total_files_changed", 0) for record in records
        ),
        "total_duration_ms": sum(
            record.get("duration_ms", 0) for record in records
        ),
        "last_execution": max(timestamps, default=None),
    }
    (workspace_dir / "dream_logs.json").write_text(
        json.dumps({"records": records, "stats": stats}),
        encoding="utf-8",
    )


def _write_damaged_dream_logs(
    base_dir: Path,
    tenant_id: str,
    source_id: str,
) -> None:
    workspace_dir = _tenant_agent_dir(base_dir, tenant_id, source_id)
    (workspace_dir / "dream_logs.json").write_text(
        "{not-valid-json",
        encoding="utf-8",
    )


def _client(
    tmp_path: Path,
    monkeypatch,
    rows: list[dict[str, Any]],
    records: list[GovernanceRecord] | None = None,
    archive_items: list[ArchiveItemRecord] | None = None,
    protected_files: list[ProtectedFileRecord] | None = None,
    audits: list[CleanupAuditRecord] | None = None,
    health: list[ReconcileHealthRecord] | None = None,
    available: bool = True,
) -> tuple[TestClient, _FakeTenantSourceStore, _FakeContinuousGovernanceStore]:
    store = _FakeTenantSourceStore(rows)
    governance_store = _FakeContinuousGovernanceStore(
        records or [],
        archive_items=archive_items,
        protected_files=protected_files,
        audits=audits,
        health=health,
        available=available,
    )
    monkeypatch.setattr(
        "swe.app.workspace.tenant_init_source_store"
        ".get_tenant_init_source_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "swe.app.routers.dream_logs._load_dream_logs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("report endpoints must not scan dream_logs.json"),
        ),
    )

    async def _fail_archive_scan(*_args, **_kwargs):
        raise AssertionError("archive report must not scan workspace files")

    monkeypatch.setattr(
        "swe.app.routers.dream_logs._source_archive_workspaces",
        _fail_archive_scan,
    )

    app = FastAPI()
    app.state.continuous_governance_service = ContinuousGovernanceService(
        governance_store,
    )

    @app.middleware("http")
    async def _attach_request_state(request: Request, call_next):
        source_id = request.headers.get("X-Source-Id", "source-a")
        scope_id = encode_scope_id("manager", source_id)
        request.state.source_id = source_id
        request.state.tenant_id = "manager"
        request.state.scope_id = scope_id
        request.state.workspace = SimpleNamespace(
            workspace_dir=tmp_path / scope_id,
        )
        request.state.workspace.workspace_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        return await call_next(request)

    app.include_router(router)
    return TestClient(app), store, governance_store


def test_report_requires_manager_or_admin(tmp_path, monkeypatch) -> None:
    client, _, _ = _client(tmp_path, monkeypatch, [])

    response = client.get(
        "/dream-logs/report",
        headers={"X-Source-Id": "source-a", "X-User-Role": "user"},
    )

    assert response.status_code == 403


def test_report_aggregates_current_source_and_counts_no_log_users(
    tmp_path,
    monkeypatch,
) -> None:
    rows = [
        {
            "tenant_id": "alice",
            "source_id": "source-a",
            "tenant_name": "Alice",
            "bbk_id": "bbk-1",
        },
        {
            "tenant_id": "bob",
            "source_id": "source-a",
            "tenant_name": "Bob",
            "bbk_id": "bbk-2",
        },
        {
            "tenant_id": "charlie",
            "source_id": "source-b",
            "tenant_name": "Charlie",
            "bbk_id": "bbk-3",
        },
    ]
    _write_dream_logs(
        tmp_path,
        "alice",
        "source-a",
        [
            _dream_record(
                "alice-success",
                timestamp="2026-05-24T09:00:00Z",
                size_saved=200,
            ),
            _dream_record(
                "alice-failed",
                timestamp="2026-05-25T09:00:00Z",
                status="failed",
                trigger="cron",
                size_saved=0,
                files_changed=0,
                error="model timeout",
            ),
        ],
    )
    _write_dream_logs(
        tmp_path,
        "charlie",
        "source-b",
        [
            _dream_record(
                "cross-source",
                timestamp="2026-05-26T09:00:00Z",
                size_saved=999,
            ),
        ],
    )
    records = [
        _governance_record(
            "alice-success",
            "alice",
            target_user_name="Alice",
            bbk_id="bbk-1",
            timestamp="2026-05-24T09:00:00Z",
            size_saved=200,
        ),
        _governance_record(
            "alice-failed",
            "alice",
            target_user_name="Alice",
            bbk_id="bbk-1",
            timestamp="2026-05-25T09:00:00Z",
            status="failed",
            trigger="cron",
            size_saved=0,
            files_changed=0,
            error="model timeout",
        ),
        _governance_record(
            "cross-source",
            "charlie",
            target_user_name="Charlie",
            bbk_id="bbk-3",
            timestamp="2026-05-26T09:00:00Z",
            size_saved=999,
            source_id="source-b",
        ),
    ]
    client, store, governance_store = _client(
        tmp_path,
        monkeypatch,
        rows,
        records,
    )

    response = client.get(
        "/dream-logs/report",
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert store.calls == ["source-a"]
    assert governance_store.report_calls[0]["source_id"] == "source-a"
    assert payload["summary"]["covered_users"] == 2
    assert payload["summary"]["governed_users"] == 1
    assert payload["summary"]["ungoverned_users"] == 1
    assert payload["summary"]["total_executions"] == 2
    assert payload["summary"]["success_count"] == 1
    assert payload["summary"]["failed_count"] == 1
    assert payload["summary"]["total_size_saved"] == 200
    assert payload["total"] == 1
    assert {item["user_id"] for item in payload["users"]} == {"alice"}
    assert "charlie" not in {item["user_id"] for item in payload["users"]}


def test_report_tolerates_damaged_logs_and_applies_filters(
    tmp_path,
    monkeypatch,
) -> None:
    rows = [
        {
            "tenant_id": "alice",
            "source_id": "source-a",
            "tenant_name": "Alice",
            "bbk_id": "bbk-1",
        },
        {
            "tenant_id": "bob",
            "source_id": "source-a",
            "tenant_name": "Bob",
            "bbk_id": "bbk-1",
        },
        {
            "tenant_id": "carol",
            "source_id": "source-a",
            "tenant_name": "Carol",
            "bbk_id": "bbk-2",
        },
    ]
    _write_dream_logs(
        tmp_path,
        "alice",
        "source-a",
        [
            _dream_record(
                "alice-success",
                timestamp="2026-05-24T09:00:00Z",
                status="success",
                trigger="manual",
            ),
        ],
    )
    _write_dream_logs(
        tmp_path,
        "bob",
        "source-a",
        [
            _dream_record(
                "bob-failed",
                timestamp="2026-05-25T09:00:00Z",
                status="failed",
                trigger="cron",
                size_saved=0,
                files_changed=0,
                error="bad response",
            ),
        ],
    )
    _write_damaged_dream_logs(tmp_path, "carol", "source-a")
    records = [
        _governance_record(
            "alice-success",
            "alice",
            target_user_name="Alice",
            bbk_id="bbk-1",
            timestamp="2026-05-24T09:00:00Z",
            status="success",
            trigger="manual",
        ),
        _governance_record(
            "bob-failed",
            "bob",
            target_user_name="Bob",
            bbk_id="bbk-1",
            timestamp="2026-05-25T09:00:00Z",
            status="failed",
            trigger="cron",
            size_saved=0,
            files_changed=0,
            error="bad response",
        ),
    ]
    client, _, _ = _client(tmp_path, monkeypatch, rows, records)

    response = client.get(
        "/dream-logs/report",
        params={
            "status": "failed",
            "trigger": "cron",
            "bbk_id": "bbk-1",
            "page": 1,
            "page_size": 2,
        },
        headers={"X-Source-Id": "source-a", "X-User-Role": "admin"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["covered_users"] == 2
    assert payload["summary"]["governed_users"] == 1
    assert payload["summary"]["total_executions"] == 1
    assert payload["summary"]["failed_count"] == 1
    assert payload["users"][0]["user_id"] == "bob"
    assert payload["users"][0]["latest_error"] == "bad response"


def test_report_user_records_are_read_only_and_source_scoped(
    tmp_path,
    monkeypatch,
) -> None:
    rows = [
        {
            "tenant_id": "alice",
            "source_id": "source-a",
            "tenant_name": "Alice",
            "bbk_id": "bbk-1",
        },
        {
            "tenant_id": "charlie",
            "source_id": "source-b",
            "tenant_name": "Charlie",
            "bbk_id": "bbk-3",
        },
    ]
    _write_dream_logs(
        tmp_path,
        "alice",
        "source-a",
        [
            _dream_record(
                "older",
                timestamp="2026-05-24T09:00:00Z",
            ),
            _dream_record(
                "newer",
                timestamp="2026-05-25T09:00:00Z",
                trigger="cron",
            ),
        ],
    )
    records = [
        _governance_record(
            "older",
            "alice",
            target_user_name="Alice",
            bbk_id="bbk-1",
            timestamp="2026-05-24T09:00:00Z",
        ),
        _governance_record(
            "newer",
            "alice",
            target_user_name="Alice",
            bbk_id="bbk-1",
            timestamp="2026-05-25T09:00:00Z",
            trigger="cron",
        ),
        _governance_record(
            "cross-source",
            "charlie",
            target_user_name="Charlie",
            bbk_id="bbk-3",
            timestamp="2026-05-25T09:00:00Z",
            source_id="source-b",
        ),
    ]
    client, _, _ = _client(tmp_path, monkeypatch, rows, records)

    response = client.get(
        "/dream-logs/report/users/alice/records",
        params={"page": 1, "page_size": 1, "agent_id": "default"},
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )
    cross_source = client.get(
        "/dream-logs/report/users/charlie/records",
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["records"][0]["id"] == "newer"
    assert payload["records"][0]["agent_id"] == "default"
    assert cross_source.status_code == 404


def test_archive_report_reads_database_state(tmp_path, monkeypatch) -> None:
    """文件治理状态报表读取数据库读模型，不扫描工作区索引。"""
    rows = [
        {
            "tenant_id": "alice",
            "source_id": "source-a",
            "tenant_name": "Alice",
            "bbk_id": "bbk-1",
        },
    ]
    archive_items = [
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
    protected_files = [
        ProtectedFileRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            path="notes.md",
            protected_at="2026-05-24T11:00:00Z",
            protected_by="admin",
            reason="manual",
            exists=False,
            size_bytes=None,
            mtime=None,
        ),
    ]
    audits = [
        CleanupAuditRecord(
            event_id="audit-1",
            timestamp="2026-05-24T12:00:00Z",
            operation="purge_archive",
            status="success",
            actor_user_id="admin",
            actor_role="manager",
            source_id="source-a",
            source_name="Source A",
            target_user_id="alice",
            target_agent_id="default",
            scope="selected",
            files_count=2,
            total_size_bytes=84,
            reason="manual",
        ),
    ]
    client, _, _ = _client(
        tmp_path,
        monkeypatch,
        rows,
        archive_items=archive_items,
        protected_files=protected_files,
        audits=audits,
    )

    response = client.get(
        "/dream-logs/archive/report",
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["archived_files"] == 1
    assert summary["pending_purge_files"] == 1
    assert summary["protected_files"] == 1
    assert summary["protected_missing_files"] == 1
    assert summary["purge_operations"] == 1
    assert summary["purged_files"] == 2
    assert summary["purged_size_bytes"] == 84


def test_archive_lists_read_database_state_and_user_filters(
    tmp_path,
    monkeypatch,
) -> None:
    """归档和保护列表应使用数据库读模型，并应用用户维度过滤。"""
    rows = [
        {
            "tenant_id": "alice",
            "tenant_name": "Alice",
            "source_id": "source-a",
        },
        {
            "tenant_id": "bob",
            "tenant_name": "Bob",
            "source_id": "source-a",
        },
    ]
    archive_items = [
        ArchiveItemRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            archive_item_id="archive-a",
            original_path="memory/alice.md",
            archive_path="governance/archive/files/archive-a",
            size_bytes=42,
            mtime="2026-05-24T09:00:00Z",
            archived_at="2026-05-24T10:00:00Z",
            archived_by="admin",
            archive_reason="manual",
            expired=True,
        ),
        ArchiveItemRecord(
            source_id="source-a",
            target_user_id="bob",
            target_agent_id="default",
            archive_item_id="archive-b",
            original_path="memory/bob.md",
            archive_path="governance/archive/files/archive-b",
            size_bytes=24,
            mtime="2026-05-24T09:00:00Z",
            archived_at="2026-05-24T10:00:00Z",
            archived_by="admin",
            archive_reason="manual",
            expired=False,
        ),
    ]
    protected_files = [
        ProtectedFileRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            path="memory/protected.md",
            protected_at="2026-05-24T11:00:00Z",
            protected_by="admin",
            reason="manual",
            exists=True,
            size_bytes=64,
            mtime="2026-05-24T11:00:00Z",
        ),
    ]
    client, _, _ = _client(
        tmp_path,
        monkeypatch,
        rows,
        archive_items=archive_items,
        protected_files=protected_files,
    )

    archive_response = client.get(
        "/dream-logs/archive/items",
        params={"user_search": "Alice", "status": "failed"},
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )
    protected_response = client.get(
        "/dream-logs/archive/protected-files",
        params={"user_search": "Alice", "trigger": "cron"},
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert archive_response.status_code == 200
    assert protected_response.status_code == 200
    archive_payload = archive_response.json()
    protected_payload = protected_response.json()
    assert archive_payload["total"] == 1
    assert archive_payload["items"][0]["id"] == "archive-a"
    assert protected_payload["total"] == 1
    assert protected_payload["items"][0]["path"] == "memory/protected.md"


def test_archive_report_applies_user_filter(tmp_path, monkeypatch) -> None:
    """文件治理状态报表支持按管理用户收窄。"""
    rows = [
        {"tenant_id": "alice", "source_id": "source-a"},
        {"tenant_id": "bob", "source_id": "source-a"},
    ]
    archive_items = [
        ArchiveItemRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            archive_item_id="archive-1",
            original_path="alice.md",
            archive_path="governance/archive/files/archive-1",
            size_bytes=42,
            mtime="2026-05-24T09:00:00Z",
            archived_at="2026-05-24T10:00:00Z",
            archived_by="admin",
            archive_reason="manual",
            expired=False,
        ),
        ArchiveItemRecord(
            source_id="source-a",
            target_user_id="bob",
            target_agent_id="default",
            archive_item_id="archive-2",
            original_path="bob.md",
            archive_path="governance/archive/files/archive-2",
            size_bytes=99,
            mtime="2026-05-24T09:00:00Z",
            archived_at="2026-05-24T10:00:00Z",
            archived_by="admin",
            archive_reason="manual",
            expired=False,
        ),
    ]
    client, _, _ = _client(
        tmp_path,
        monkeypatch,
        rows,
        archive_items=archive_items,
    )

    response = client.get(
        "/dream-logs/archive/report",
        params={"target_user_id": "alice"},
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["archived_files"] == 1
    assert summary["archived_size_bytes"] == 42


def test_archive_report_rejects_user_outside_current_source(
    tmp_path,
    monkeypatch,
) -> None:
    """文件治理状态报表的用户过滤必须受 Managed Source User Set 约束。"""
    rows = [{"tenant_id": "alice", "source_id": "source-a"}]
    client, _, _ = _client(tmp_path, monkeypatch, rows)

    response = client.get(
        "/dream-logs/archive/report",
        params={"target_user_id": "mallory"},
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 403


def test_archive_admin_audits_read_database_state(
    tmp_path,
    monkeypatch,
) -> None:
    """清理审计明细读取数据库读模型。"""
    rows = [{"tenant_id": "alice", "source_id": "source-a"}]
    audits = [
        CleanupAuditRecord(
            event_id="audit-1",
            timestamp="2026-05-24T12:00:00Z",
            operation="purge_archive",
            status="success",
            actor_user_id="admin",
            actor_role="manager",
            source_id="source-a",
            source_name="Source A",
            target_user_id="alice",
            target_agent_id="default",
            scope="selected",
            files_count=2,
            total_size_bytes=84,
            reason="manual",
        ),
    ]
    client, _, _ = _client(tmp_path, monkeypatch, rows, audits=audits)

    response = client.get(
        "/dream-logs/archive/admin-audits",
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_operations"] == 1
    assert payload["items"][0]["event_id"] == "audit-1"


def test_report_exposes_reconcile_health(tmp_path, monkeypatch) -> None:
    """待补偿健康状态需要单独透出，不能混入核心指标。"""
    rows = [{"tenant_id": "alice", "source_id": "source-a"}]
    health = [
        ReconcileHealthRecord(
            source_id="source-a",
            target_user_id="alice",
            target_agent_id="default",
            entity_type="governance_record",
            entity_id="record-2",
            status="pending",
            reason="workspace saved but db write failed",
            error="timeout",
            payload={"record_id": "record-2"},
        ),
    ]
    client, _, _ = _client(tmp_path, monkeypatch, rows, health=health)

    response = client.get(
        "/dream-logs/report",
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_executions"] == 0
    assert payload["health"][0]["status"] == "pending"
    assert payload["health"][0]["entity_id"] == "record-2"


def test_report_returns_503_when_database_read_model_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    """管理报表不能在数据库读模型不可用时退回文件扫描。"""
    rows = [{"tenant_id": "alice", "source_id": "source-a"}]
    client, _, _ = _client(
        tmp_path,
        monkeypatch,
        rows,
        available=False,
    )

    response = client.get(
        "/dream-logs/report",
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 503


def test_report_rejects_invalid_agent_filter(tmp_path, monkeypatch) -> None:
    """治理报表 agent 过滤条件也必须符合读模型标识约束。"""
    rows = [{"tenant_id": "alice", "source_id": "source-a"}]
    client, _, _ = _client(tmp_path, monkeypatch, rows)

    response = client.get(
        "/dream-logs/report",
        params={"agent_id": "../escape"},
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 400


def test_archive_items_reject_overlong_agent_filter(
    tmp_path,
    monkeypatch,
) -> None:
    """文件治理列表 agent 过滤条件不能超过读模型字段长度。"""
    rows = [{"tenant_id": "alice", "source_id": "source-a"}]
    client, _, _ = _client(tmp_path, monkeypatch, rows)

    response = client.get(
        "/dream-logs/archive/items",
        params={"target_agent_id": "a" * 129},
        headers={"X-Source-Id": "source-a", "X-User-Role": "manager"},
    )

    assert response.status_code == 400
