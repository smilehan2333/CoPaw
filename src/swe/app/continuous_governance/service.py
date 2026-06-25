# -*- coding: utf-8 -*-
"""持续治理数据库读模型服务。"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .models import (
    ArchiveItemRecord,
    ArchiveReportData,
    ArchiveReportSummaryData,
    CleanupAuditRecord,
    GovernanceReportBbkBucket,
    GovernanceReportData,
    GovernanceReportRecordRow,
    GovernanceReportStatusBucket,
    GovernanceReportSummary,
    GovernanceReportTrendPoint,
    GovernanceReportUserRow,
    GovernanceRecord,
    GOVERNANCE_ID_MAX_LENGTH,
    GovernanceUserRecordsData,
    ProtectedFileRecord,
    ReconcileHealthRecord,
)

MAX_REPORT_PAGE_SIZE = 100
ARCHIVE_PURGE_DAYS = 10


def _health_entity_id(prefix: str, raw_value: str) -> str:
    """为 health 唯一键生成不超过读模型字段长度的实体标识。"""
    value = raw_value or "unknown"
    if len(value) <= GOVERNANCE_ID_MAX_LENGTH:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


class ContinuousGovernanceService:
    """面向路由层的持续治理报表服务。"""

    def __init__(self, store: Any):
        """初始化服务。"""
        self.store = store

    async def build_governance_report(
        self,
        *,
        source_id: str,
        tenants: list[dict[str, Any]],
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        bbk_id: Optional[str] = None,
        user_search: Optional[str] = None,
        status: Optional[str] = None,
        trigger: Optional[str] = None,
        agent_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> GovernanceReportData:
        """构造持续治理分析报表。"""
        safe_page, safe_page_size = _normalise_page(page, page_size)
        filtered_tenants = _filter_tenants(
            tenants,
            bbk_id=bbk_id,
            user_search=user_search,
        )
        target_user_ids = [
            str(row.get("tenant_id") or "") for row in filtered_tenants
        ]
        records = await self.store.list_governance_records(
            source_id,
            target_user_ids=target_user_ids,
            target_agent_id=agent_id,
            start_time=start_time,
            end_time=end_time,
            status=status,
            trigger=trigger,
        )
        health = await self.store.list_reconcile_health(source_id)
        records_by_user = _group_records_by_user(records)
        user_rows = [
            _build_user_row(
                tenant,
                records_by_user[str(tenant.get("tenant_id") or "")],
            )
            for tenant in filtered_tenants
        ]
        user_rows.sort(
            key=lambda row: (
                row.executions,
                row.last_execution or "",
                row.user_id,
            ),
            reverse=True,
        )
        visible_user_rows = [row for row in user_rows if row.executions > 0]
        start_idx = (safe_page - 1) * safe_page_size
        end_idx = start_idx + safe_page_size
        return GovernanceReportData(
            summary=_build_summary(user_rows, records),
            trends=_build_trends(records),
            status_distribution=_build_status_distribution(records),
            bbk_distribution=_build_bbk_distribution(user_rows),
            users=visible_user_rows[start_idx:end_idx],
            total=len(visible_user_rows),
            page=safe_page,
            page_size=safe_page_size,
            health=health,
        )

    async def list_user_records(
        self,
        *,
        source_id: str,
        tenants: list[dict[str, Any]],
        user_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        status: Optional[str] = None,
        trigger: Optional[str] = None,
        agent_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> GovernanceUserRecordsData | None:
        """查询单个用户的治理记录。"""
        if not any(
            str(row.get("tenant_id") or "") == user_id for row in tenants
        ):
            return None
        safe_page, safe_page_size = _normalise_page(page, page_size)
        records = await self.store.list_governance_records(
            source_id,
            target_user_ids=[user_id],
            target_agent_id=agent_id,
            start_time=start_time,
            end_time=end_time,
            status=status,
            trigger=trigger,
        )
        rows = [_record_to_report_row(record) for record in records]
        rows.sort(key=lambda row: (row.timestamp, row.id), reverse=True)
        start_idx = (safe_page - 1) * safe_page_size
        end_idx = start_idx + safe_page_size
        return GovernanceUserRecordsData(
            records=rows[start_idx:end_idx],
            total=len(rows),
            page=safe_page,
            page_size=safe_page_size,
        )

    async def build_archive_report(
        self,
        *,
        source_id: str,
        tenants: list[dict[str, Any]],
        target_user_id: Optional[str] = None,
        target_agent_id: Optional[str] = None,
        status: Optional[str] = None,
        trigger: Optional[str] = None,
    ) -> ArchiveReportData:
        """构造文件治理状态报告。"""
        del status, trigger
        target_user_ids = _target_user_ids(tenants, target_user_id)
        archive_items = await self.store.list_archive_items(
            source_id,
            target_user_ids=target_user_ids,
            target_agent_id=target_agent_id,
        )
        protected_files = await self.store.list_protected_files(
            source_id,
            target_user_ids=target_user_ids,
            target_agent_id=target_agent_id,
        )
        audits = await self.store.list_cleanup_audits(
            source_id,
            target_user_ids=target_user_ids,
            target_agent_id=target_agent_id,
        )
        health = await self.store.list_reconcile_health(source_id)
        pending_items = [
            item for item in archive_items if _archive_record_expired(item)
        ]
        return ArchiveReportData(
            summary=ArchiveReportSummaryData(
                archived_files=len(archive_items),
                archived_size_bytes=sum(
                    item.size_bytes for item in archive_items
                ),
                pending_purge_files=len(pending_items),
                pending_purge_size_bytes=sum(
                    item.size_bytes for item in pending_items
                ),
                protected_files=len(protected_files),
                protected_existing_files=sum(
                    1 for item in protected_files if item.exists
                ),
                protected_missing_files=sum(
                    1 for item in protected_files if not item.exists
                ),
                purge_operations=len(audits),
                purge_success_operations=sum(
                    1 for item in audits if item.status == "success"
                ),
                purge_failed_operations=sum(
                    1 for item in audits if item.status == "failed"
                ),
                purged_files=sum(item.files_count for item in audits),
                purged_size_bytes=sum(
                    item.total_size_bytes for item in audits
                ),
                last_purge_at=_latest_audit_time(audits),
            ),
            health=health,
        )

    async def upsert_workspace_governance_record(
        self,
        *,
        source_id: str,
        target_user_id: str,
        target_user_name: str | None,
        bbk_id: str | None,
        target_agent_id: str,
        record: dict[str, Any],
    ) -> None:
        """把 workspace dream log 记录写入数据库读模型。"""
        await self.store.upsert_governance_record(
            _workspace_record_to_model(
                source_id=source_id,
                target_user_id=target_user_id,
                target_user_name=target_user_name,
                bbk_id=bbk_id,
                target_agent_id=target_agent_id,
                record=record,
            ),
        )

    async def upsert_workspace_governance_record_with_health(
        self,
        *,
        source_id: str,
        target_user_id: str,
        target_user_name: str | None,
        bbk_id: str | None,
        target_agent_id: str,
        record: dict[str, Any],
    ) -> None:
        """写入治理记录，失败时登记待对账 health。"""
        record_id = str(record.get("id") or "")
        try:
            await self.upsert_workspace_governance_record(
                source_id=source_id,
                target_user_id=target_user_id,
                target_user_name=target_user_name,
                bbk_id=bbk_id,
                target_agent_id=target_agent_id,
                record=record,
            )
        except Exception as exc:
            await self.record_reconcile_health(
                source_id=source_id,
                target_user_id=target_user_id,
                target_agent_id=target_agent_id,
                entity_type="governance_record",
                entity_id=record_id or "unknown",
                reason="workspace write succeeded but db write failed",
                error=str(exc),
                payload={
                    "record": record,
                    "target_user_name": target_user_name,
                    "bbk_id": bbk_id,
                },
            )

    async def mark_governance_record_rollback(
        self,
        *,
        source_id: str,
        target_user_id: str,
        target_agent_id: str,
        record_id: str,
        rollback_timestamp: str,
        rollback_files: list[str],
    ) -> bool:
        """把原始治理记录更新为 rollback outcome。"""
        return await self.store.mark_governance_record_rollback(
            source_id=source_id,
            target_user_id=target_user_id,
            target_agent_id=target_agent_id,
            record_id=record_id,
            rollback_timestamp=rollback_timestamp,
            rollback_files=rollback_files,
        )

    async def upsert_archive_items(
        self,
        *,
        source_id: str,
        target_user_id: str,
        target_agent_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        """写入归档文件状态。"""
        for item in items:
            await self.store.upsert_archive_item(
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
                    expired=bool(item.get("expired")),
                    raw_item=dict(item),
                ),
            )

    async def delete_archive_items(
        self,
        *,
        source_id: str,
        target_user_id: str,
        target_agent_id: str,
        archive_item_ids: list[str],
    ) -> None:
        """删除归档文件状态。"""
        for archive_item_id in archive_item_ids:
            await self.store.delete_archive_item(
                source_id=source_id,
                target_user_id=target_user_id,
                target_agent_id=target_agent_id,
                archive_item_id=archive_item_id,
            )

    async def upsert_protected_file(
        self,
        *,
        source_id: str,
        target_user_id: str,
        target_agent_id: str,
        path: str,
        protected_at: str,
        protected_by: str,
        reason: str,
        exists: bool,
        size_bytes: int | None = None,
        mtime: str | None = None,
    ) -> None:
        """写入受保护文件状态。"""
        await self.store.upsert_protected_file(
            ProtectedFileRecord(
                source_id=source_id,
                target_user_id=target_user_id,
                target_agent_id=target_agent_id,
                path=path,
                protected_at=protected_at,
                protected_by=protected_by,
                reason=reason,
                exists=exists,
                size_bytes=size_bytes,
                mtime=mtime,
            ),
        )

    async def delete_protected_file(
        self,
        *,
        source_id: str,
        target_user_id: str,
        target_agent_id: str,
        path: str,
    ) -> bool:
        """删除受保护文件状态。"""
        return await self.store.delete_protected_file(
            source_id=source_id,
            target_user_id=target_user_id,
            target_agent_id=target_agent_id,
            path=path,
        )

    async def upsert_cleanup_audit(
        self,
        record: dict[str, Any],
    ) -> None:
        """写入清理审计。"""
        await self.store.upsert_cleanup_audit(
            CleanupAuditRecord(
                event_id=str(record.get("event_id") or ""),
                timestamp=str(record.get("timestamp") or ""),
                operation=str(record.get("operation") or ""),
                status=str(record.get("status") or ""),
                actor_user_id=str(record.get("actor_user_id") or ""),
                actor_role=str(record.get("actor_role") or ""),
                source_id=str(record.get("source_id") or ""),
                source_name=record.get("source_name"),
                target_user_id=str(record.get("target_user_id") or ""),
                target_agent_id=str(
                    record.get("target_agent_id") or "default",
                ),
                scope=str(record.get("scope") or ""),
                files_count=int(record.get("files_count") or 0),
                total_size_bytes=int(record.get("total_size_bytes") or 0),
                reason=str(record.get("reason") or ""),
                error=record.get("error"),
                raw_audit=dict(record),
            ),
        )

    async def record_reconcile_health(
        self,
        *,
        source_id: str,
        target_user_id: str,
        target_agent_id: str,
        entity_type: str,
        entity_id: str,
        reason: str,
        error: str | None,
        payload: dict[str, Any],
        status: str = "reconcile_needed",
    ) -> None:
        """登记待补偿或待对账状态。"""
        await self.store.upsert_reconcile_health(
            ReconcileHealthRecord(
                source_id=source_id,
                target_user_id=target_user_id,
                target_agent_id=target_agent_id,
                entity_type=entity_type,
                entity_id=_health_entity_id(entity_type, entity_id),
                status=status,
                reason=reason,
                error=error,
                payload=payload,
                updated_at=datetime.now(timezone.utc),
            ),
        )

    async def reconcile_health(
        self,
        *,
        source_id: str,
        entity_ids: set[str] | None = None,
    ) -> dict[str, int]:
        """显式重放待对账项，成功后把 health 标记为 resolved。"""
        rows = await self.store.list_reconcile_health(source_id)
        result = {"processed": 0, "resolved": 0, "failed": 0}
        for row in rows:
            if entity_ids is not None and row.entity_id not in entity_ids:
                continue
            result["processed"] += 1
            try:
                await self._replay_reconcile_health(row)
                await self._mark_reconcile_health(row, "resolved", None)
                result["resolved"] += 1
            except Exception as exc:
                await self._mark_reconcile_health(row, "failed", str(exc))
                result["failed"] += 1
        return result

    async def _replay_reconcile_health(
        self,
        row: ReconcileHealthRecord,
    ) -> None:
        """按 health payload 重放数据库读模型写入。"""
        payload = row.payload
        if row.entity_type == "governance_record":
            await self._replay_governance_health(row, payload)
            return
        if row.entity_type == "archive_items":
            await self.upsert_archive_items(
                source_id=row.source_id,
                target_user_id=row.target_user_id,
                target_agent_id=row.target_agent_id,
                items=_payload_list(payload, "items"),
            )
            return
        if row.entity_type == "cleanup_audit":
            await self._replay_cleanup_audit_health(row, payload)
            return
        if row.entity_type == "protected_file":
            await self._replay_protected_file_health(row, payload)
            return
        if row.entity_type == "archive_restore":
            await self._replay_archive_restore_health(row, payload)
            return
        raise ValueError(
            f"unsupported reconcile entity_type: {row.entity_type}",
        )

    async def _replay_governance_health(
        self,
        row: ReconcileHealthRecord,
        payload: dict[str, Any],
    ) -> None:
        """重放治理记录或回滚结果写入。"""
        record = payload.get("record")
        if isinstance(record, dict):
            await self.upsert_workspace_governance_record(
                source_id=row.source_id,
                target_user_id=row.target_user_id,
                target_user_name=payload.get("target_user_name"),
                bbk_id=payload.get("bbk_id"),
                target_agent_id=row.target_agent_id,
                record=record,
            )
            return

        record_id = str(payload.get("record_id") or row.entity_id)
        rollback_files = payload.get("rollback_files")
        if isinstance(rollback_files, list):
            updated = await self.mark_governance_record_rollback(
                source_id=row.source_id,
                target_user_id=row.target_user_id,
                target_agent_id=row.target_agent_id,
                record_id=record_id,
                rollback_timestamp=str(
                    payload.get("rollback_timestamp")
                    or _health_timestamp(row),
                ),
                rollback_files=[str(item) for item in rollback_files],
            )
            if not updated:
                raise ValueError(
                    "rollback reconcile target record was not found",
                )
            return
        raise ValueError("governance reconcile payload is missing record")

    async def _replay_cleanup_audit_health(
        self,
        row: ReconcileHealthRecord,
        payload: dict[str, Any],
    ) -> None:
        """重放清理审计及相关归档删除。"""
        archive_item_ids = [
            str(item) for item in payload.get("archive_item_ids") or []
        ]
        if archive_item_ids:
            await self.delete_archive_items(
                source_id=row.source_id,
                target_user_id=row.target_user_id,
                target_agent_id=row.target_agent_id,
                archive_item_ids=archive_item_ids,
            )
        audit = payload.get("audit")
        if not isinstance(audit, dict):
            raise ValueError(
                "cleanup audit reconcile payload is missing audit",
            )
        await self.upsert_cleanup_audit(audit)

    async def _replay_protected_file_health(
        self,
        row: ReconcileHealthRecord,
        payload: dict[str, Any],
    ) -> None:
        """重放保护文件变更。"""
        path = str(payload.get("path") or row.entity_id)
        if payload.get("operation") == "remove":
            await self.delete_protected_file(
                source_id=row.source_id,
                target_user_id=row.target_user_id,
                target_agent_id=row.target_agent_id,
                path=path,
            )
            return
        await self.upsert_protected_file(
            source_id=row.source_id,
            target_user_id=row.target_user_id,
            target_agent_id=row.target_agent_id,
            path=path,
            protected_at=str(
                payload.get("protected_at") or _health_timestamp(row),
            ),
            protected_by=str(payload.get("protected_by") or "reconcile"),
            reason=str(payload.get("reason") or "reconcile"),
            exists=bool(payload.get("exists", True)),
            size_bytes=payload.get("size_bytes"),
            mtime=payload.get("mtime"),
        )

    async def _replay_archive_restore_health(
        self,
        row: ReconcileHealthRecord,
        payload: dict[str, Any],
    ) -> None:
        """重放归档恢复后的读模型状态。"""
        archive_item_id = str(payload.get("archive_item_id") or row.entity_id)
        await self.delete_archive_items(
            source_id=row.source_id,
            target_user_id=row.target_user_id,
            target_agent_id=row.target_agent_id,
            archive_item_ids=[archive_item_id],
        )
        if not payload.get("protect_after_restore"):
            return
        await self.upsert_protected_file(
            source_id=row.source_id,
            target_user_id=row.target_user_id,
            target_agent_id=row.target_agent_id,
            path=str(payload.get("original_path") or ""),
            protected_at=str(
                payload.get("protected_at") or _health_timestamp(row),
            ),
            protected_by=str(payload.get("protected_by") or "reconcile"),
            reason="restored_from_archive",
            exists=bool(payload.get("exists", True)),
            size_bytes=payload.get("size_bytes"),
            mtime=payload.get("mtime"),
        )

    async def _mark_reconcile_health(
        self,
        row: ReconcileHealthRecord,
        status: str,
        error: str | None,
    ) -> None:
        """更新对账 health 的最终状态。"""
        await self.store.upsert_reconcile_health(
            ReconcileHealthRecord(
                source_id=row.source_id,
                target_user_id=row.target_user_id,
                target_agent_id=row.target_agent_id,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                status=status,
                reason=(
                    "reconcile replay resolved"
                    if status == "resolved"
                    else "reconcile replay failed"
                ),
                error=error,
                payload=row.payload,
                updated_at=datetime.now(timezone.utc),
            ),
        )


def _normalise_page(page: int, page_size: int) -> tuple[int, int]:
    """限制分页参数。"""
    return max(page, 1), min(max(page_size, 1), MAX_REPORT_PAGE_SIZE)


def _payload_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """从 health payload 读取列表字段，并拒绝错误结构。"""
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"reconcile payload is missing list: {key}")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"reconcile payload list is invalid: {key}")
    return value


def _health_timestamp(row: ReconcileHealthRecord) -> str:
    """用 health 更新时间作为无法还原原始操作时间时的兜底值。"""
    if row.updated_at is None:
        return datetime.now(timezone.utc).isoformat()
    return row.updated_at.isoformat()


def _archive_record_expired(
    item: ArchiveItemRecord,
    now: Optional[datetime] = None,
) -> bool:
    """按归档时间动态判断文件是否超过清理保留期。"""
    if not item.archived_at:
        return False
    try:
        archived_dt = datetime.fromisoformat(
            item.archived_at.replace("Z", "+00:00"),
        )
    except ValueError:
        return False
    if archived_dt.tzinfo is None:
        archived_dt = archived_dt.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return current - archived_dt.astimezone(timezone.utc) >= timedelta(
        days=ARCHIVE_PURGE_DAYS,
    )


def _filter_tenants(
    tenants: list[dict[str, Any]],
    *,
    bbk_id: Optional[str],
    user_search: Optional[str],
) -> list[dict[str, Any]]:
    """按机构和用户关键词过滤可管理用户。"""
    keyword = (user_search or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for tenant in tenants:
        tenant_id = str(tenant.get("tenant_id") or "")
        tenant_name = str(tenant.get("tenant_name") or "")
        if bbk_id and tenant.get("bbk_id") != bbk_id:
            continue
        if (
            keyword
            and keyword not in tenant_id.lower()
            and keyword not in tenant_name.lower()
        ):
            continue
        rows.append(tenant)
    return rows


def _target_user_ids(
    tenants: list[dict[str, Any]],
    target_user_id: Optional[str],
) -> list[str]:
    """得到文件治理状态报告的目标用户集合。"""
    if target_user_id:
        return [target_user_id]
    return [str(row.get("tenant_id") or "") for row in tenants]


def _group_records_by_user(
    records: list[GovernanceRecord],
) -> dict[str, list[GovernanceRecord]]:
    """按逻辑用户聚合治理记录。"""
    grouped: dict[str, list[GovernanceRecord]] = defaultdict(list)
    for record in records:
        grouped[record.target_user_id].append(record)
    for rows in grouped.values():
        rows.sort(key=lambda row: (row.timestamp, row.record_id), reverse=True)
    return grouped


def _build_user_row(
    tenant: dict[str, Any],
    records: list[GovernanceRecord],
) -> GovernanceReportUserRow:
    """构造用户明细行。"""
    success_count = sum(1 for record in records if record.status == "success")
    failed_count = sum(1 for record in records if record.status == "failed")
    executions = len(records)
    latest_error = next(
        (record.error for record in records if record.error),
        None,
    )
    return GovernanceReportUserRow(
        user_id=str(tenant.get("tenant_id") or ""),
        user_name=tenant.get("tenant_name"),
        bbk_id=tenant.get("bbk_id"),
        agents=sorted({record.target_agent_id for record in records}),
        executions=executions,
        success_rate=(
            round(success_count * 100 / executions, 2) if executions else 0
        ),
        failed_count=failed_count,
        total_files_changed=sum(
            record.total_files_changed for record in records
        ),
        total_size_saved=sum(record.total_size_saved for record in records),
        last_execution=max(
            (record.timestamp for record in records),
            default=None,
        ),
        latest_error=latest_error,
    )


def _build_summary(
    users: list[GovernanceReportUserRow],
    records: list[GovernanceRecord],
) -> GovernanceReportSummary:
    """构造持续治理汇总指标。"""
    total_executions = len(records)
    success_count = sum(1 for record in records if record.status == "success")
    failed_count = sum(1 for record in records if record.status == "failed")
    total_duration = sum(record.duration_ms for record in records)
    return GovernanceReportSummary(
        covered_users=len(users),
        governed_users=sum(1 for user in users if user.executions > 0),
        ungoverned_users=sum(1 for user in users if user.executions == 0),
        total_executions=total_executions,
        success_count=success_count,
        failed_count=failed_count,
        success_rate=(
            round(success_count * 100 / total_executions, 2)
            if total_executions
            else 0
        ),
        total_files_changed=sum(
            record.total_files_changed for record in records
        ),
        total_size_saved=sum(record.total_size_saved for record in records),
        avg_duration_ms=(
            total_duration // total_executions if total_executions else 0
        ),
        last_execution=max(
            (record.timestamp for record in records),
            default=None,
        ),
    )


def _build_trends(
    records: list[GovernanceRecord],
) -> list[GovernanceReportTrendPoint]:
    """按日期聚合趋势。"""
    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "executions": 0,
            "manual_count": 0,
            "cron_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "total_size_saved": 0,
        },
    )
    for record in records:
        record_dt = _parse_record_time(record.timestamp)
        if record_dt is None:
            continue
        bucket = buckets[record_dt.date().isoformat()]
        bucket["executions"] += 1
        if record.trigger == "cron":
            bucket["cron_count"] += 1
        else:
            bucket["manual_count"] += 1
        bucket["success_count"] += 1 if record.status == "success" else 0
        bucket["failed_count"] += 1 if record.status == "failed" else 0
        bucket["total_size_saved"] += record.total_size_saved
    return [
        GovernanceReportTrendPoint(date=date_key, **values)
        for date_key, values in sorted(buckets.items())
    ]


def _build_status_distribution(
    records: list[GovernanceRecord],
) -> list[GovernanceReportStatusBucket]:
    """聚合状态分布。"""
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        counts[record.status or "unknown"] += 1
    return [
        GovernanceReportStatusBucket(status=status, count=count)
        for status, count in sorted(counts.items())
    ]


def _build_bbk_distribution(
    users: list[GovernanceReportUserRow],
) -> list[GovernanceReportBbkBucket]:
    """聚合机构分布。"""
    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "user_count": 0,
            "governed_users": 0,
            "executions": 0,
            "success_count": 0,
        },
    )
    for user in users:
        if user.executions <= 0:
            continue
        bucket = buckets[user.bbk_id or "other"]
        bucket["user_count"] += 1
        bucket["governed_users"] += 1
        bucket["executions"] += user.executions
        bucket["success_count"] += round(
            user.executions * user.success_rate / 100,
        )
    return [
        GovernanceReportBbkBucket(
            bbk_id=bbk_id,
            user_count=values["user_count"],
            governed_users=values["governed_users"],
            executions=values["executions"],
            success_rate=(
                round(
                    values["success_count"] * 100 / values["executions"],
                    2,
                )
                if values["executions"]
                else 0
            ),
        )
        for bbk_id, values in sorted(
            buckets.items(),
            key=lambda item: (item[1]["executions"], item[0]),
            reverse=True,
        )
    ]


def _record_to_report_row(
    record: GovernanceRecord,
) -> GovernanceReportRecordRow:
    """把数据库治理记录转换为下钻行。"""
    return GovernanceReportRecordRow(
        id=record.record_id,
        timestamp=record.timestamp,
        trigger=record.trigger,
        status=record.status,
        agent_id=record.target_agent_id,
        files_optimized=record.files_optimized,
        total_size_saved=record.total_size_saved,
        total_files_changed=record.total_files_changed,
        duration_ms=record.duration_ms,
        model_used=record.model_used,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        summary=record.summary,
        error=record.error,
    )


def _workspace_record_to_model(
    *,
    source_id: str,
    target_user_id: str,
    target_user_name: str | None,
    bbk_id: str | None,
    target_agent_id: str,
    record: dict[str, Any],
) -> GovernanceRecord:
    """把 workspace dream log 记录转换为数据库读模型记录。"""
    return GovernanceRecord(
        source_id=source_id,
        target_user_id=target_user_id,
        target_user_name=target_user_name,
        bbk_id=bbk_id,
        target_agent_id=target_agent_id,
        record_id=str(record.get("id") or ""),
        timestamp=str(record.get("timestamp") or ""),
        trigger=str(record.get("trigger") or ""),
        status=str(record.get("status") or ""),
        files_optimized=list(record.get("files_optimized") or []),
        total_size_saved=int(record.get("total_size_saved") or 0),
        total_files_changed=int(record.get("total_files_changed") or 0),
        duration_ms=int(record.get("duration_ms") or 0),
        model_used=str(record.get("model_used") or ""),
        input_tokens=int(record.get("input_tokens") or 0),
        output_tokens=int(record.get("output_tokens") or 0),
        summary=str(record.get("summary") or ""),
        error=record.get("error"),
        rollback_timestamp=record.get("rollback_timestamp"),
        rollback_files=list(record.get("rollback_files") or []),
        raw_record=dict(record),
    )


def _parse_record_time(value: str) -> datetime | None:
    """解析治理记录时间。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_audit_time(audits: list[CleanupAuditRecord]) -> str | None:
    """返回最新清理审计时间。"""
    return max((audit.timestamp for audit in audits), default=None)
