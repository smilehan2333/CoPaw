# -*- coding: utf-8 -*-
"""持续治理数据库读模型存储。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .models import (
    ArchiveItemRecord,
    CleanupAuditRecord,
    GovernanceRecord,
    ProtectedFileRecord,
    ReconcileHealthRecord,
)

logger = logging.getLogger(__name__)

_UNAVAILABLE_PREFIX = "continuous governance storage unavailable"


class ContinuousGovernanceStoreUnavailable(RuntimeError):
    """持续治理数据库读模型不可用。"""


class ContinuousGovernanceStore:
    """读写管理侧持续治理数据库模型。"""

    def __init__(self, db: Any | None = None):
        """初始化存储。"""
        self.db = db

    @property
    def is_available(self) -> bool:
        """返回数据库连接是否可用。"""
        return self.db is not None and bool(
            getattr(self.db, "is_connected", False),
        )

    def _require_db(self) -> Any:
        """校验数据库可用性。"""
        if not self.is_available:
            raise ContinuousGovernanceStoreUnavailable(
                f"{_UNAVAILABLE_PREFIX}: db is not connected",
            )
        return self.db

    async def _call_db(
        self,
        operation: str,
        db_call: Any,
        *args: Any,
    ) -> Any:
        """执行数据库调用并统一包装底层异常。"""
        try:
            return await db_call(*args)
        except ContinuousGovernanceStoreUnavailable:
            raise
        except Exception as exc:
            raise ContinuousGovernanceStoreUnavailable(
                f"{_UNAVAILABLE_PREFIX}: {operation} failed: {exc}",
            ) from exc

    async def upsert_governance_record(
        self,
        record: GovernanceRecord,
    ) -> None:
        """幂等写入持续治理记录。"""
        db = self._require_db()
        query = """
            INSERT INTO swe_continuous_governance_records (
                source_id, target_user_id, target_agent_id, record_id,
                target_user_name, bbk_id, occurred_at, trigger_type, status,
                model_used, input_tokens, output_tokens, files_optimized_json,
                total_size_saved, total_files_changed, duration_ms, summary,
                error_text, rollback_timestamp, rollback_files_json,
                raw_record_json
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                target_user_name = VALUES(target_user_name),
                bbk_id = VALUES(bbk_id),
                occurred_at = VALUES(occurred_at),
                trigger_type = VALUES(trigger_type),
                status = VALUES(status),
                model_used = VALUES(model_used),
                input_tokens = VALUES(input_tokens),
                output_tokens = VALUES(output_tokens),
                files_optimized_json = VALUES(files_optimized_json),
                total_size_saved = VALUES(total_size_saved),
                total_files_changed = VALUES(total_files_changed),
                duration_ms = VALUES(duration_ms),
                summary = VALUES(summary),
                error_text = VALUES(error_text),
                rollback_timestamp = VALUES(rollback_timestamp),
                rollback_files_json = VALUES(rollback_files_json),
                raw_record_json = VALUES(raw_record_json),
                updated_at = CURRENT_TIMESTAMP
        """
        await self._call_db(
            "upsert governance record",
            db.execute,
            query,
            (
                record.source_id,
                record.target_user_id,
                record.target_agent_id,
                record.record_id,
                record.target_user_name,
                record.bbk_id,
                record.timestamp,
                record.trigger,
                record.status,
                record.model_used,
                record.input_tokens,
                record.output_tokens,
                _dump_json(record.files_optimized),
                record.total_size_saved,
                record.total_files_changed,
                record.duration_ms,
                record.summary,
                record.error,
                record.rollback_timestamp,
                _dump_json(record.rollback_files),
                _dump_json(record.raw_record),
            ),
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
        """把原始治理记录更新为回滚状态。"""
        db = self._require_db()
        result = await self._call_db(
            "mark governance rollback",
            db.execute,
            """
                UPDATE swe_continuous_governance_records
                SET status = 'rollback',
                    rollback_timestamp = %s,
                    rollback_files_json = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE source_id = %s
                    AND target_user_id = %s
                    AND target_agent_id = %s
                    AND record_id = %s
            """,
            (
                rollback_timestamp,
                _dump_json(rollback_files),
                source_id,
                target_user_id,
                target_agent_id,
                record_id,
            ),
        )
        return bool(result)

    async def list_governance_records(
        self,
        source_id: str,
        *,
        target_user_ids: Optional[Iterable[str]] = None,
        target_agent_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        status: Optional[str] = None,
        trigger: Optional[str] = None,
    ) -> list[GovernanceRecord]:
        """按管理报表条件读取持续治理记录。"""
        db = self._require_db()
        where, params = _build_common_where(
            source_id,
            target_user_ids=target_user_ids,
            target_agent_id=target_agent_id,
            start_time=start_time,
            end_time=end_time,
            status=status,
            trigger=trigger,
        )
        rows = await self._call_db(
            "list governance records",
            db.fetch_all,
            f"""
                SELECT source_id, target_user_id, target_agent_id, record_id,
                    target_user_name, bbk_id, occurred_at, trigger_type,
                    status, model_used, input_tokens, output_tokens,
                    files_optimized_json, total_size_saved,
                    total_files_changed, duration_ms, summary, error_text,
                    rollback_timestamp, rollback_files_json, raw_record_json
                FROM swe_continuous_governance_records
                WHERE {where}
                ORDER BY occurred_at DESC, record_id DESC
            """,
            tuple(params),
        )
        return [_row_to_governance_record(row) for row in rows]

    async def upsert_archive_item(self, record: ArchiveItemRecord) -> None:
        """幂等写入归档文件状态。"""
        db = self._require_db()
        await self._call_db(
            "upsert archive item",
            db.execute,
            """
                INSERT INTO swe_file_governance_archive_items (
                    source_id, target_user_id, target_agent_id,
                    archive_item_id, original_path, archive_path, size_bytes,
                    mtime, archived_at, archived_by, archive_reason, expired,
                    raw_item_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    original_path = VALUES(original_path),
                    archive_path = VALUES(archive_path),
                    size_bytes = VALUES(size_bytes),
                    mtime = VALUES(mtime),
                    archived_at = VALUES(archived_at),
                    archived_by = VALUES(archived_by),
                    archive_reason = VALUES(archive_reason),
                    expired = VALUES(expired),
                    raw_item_json = VALUES(raw_item_json),
                    updated_at = CURRENT_TIMESTAMP
            """,
            (
                record.source_id,
                record.target_user_id,
                record.target_agent_id,
                record.archive_item_id,
                record.original_path,
                record.archive_path,
                record.size_bytes,
                record.mtime,
                record.archived_at,
                record.archived_by,
                record.archive_reason,
                int(record.expired),
                _dump_json(record.raw_item),
            ),
        )

    async def list_archive_items(
        self,
        source_id: str,
        *,
        target_user_ids: Optional[Iterable[str]] = None,
        target_agent_id: Optional[str] = None,
        expired: Optional[bool] = None,
    ) -> list[ArchiveItemRecord]:
        """读取归档文件状态。"""
        db = self._require_db()
        where, params = _build_file_state_where(
            source_id,
            target_user_ids=target_user_ids,
            target_agent_id=target_agent_id,
        )
        if expired is not None:
            where += " AND expired = %s"
            params.append(int(expired))
        rows = await self._call_db(
            "list archive items",
            db.fetch_all,
            f"""
                SELECT source_id, target_user_id, target_agent_id,
                    archive_item_id, original_path, archive_path, size_bytes,
                    mtime, archived_at, archived_by, archive_reason, expired,
                    raw_item_json
                FROM swe_file_governance_archive_items
                WHERE {where}
                ORDER BY archived_at DESC, archive_item_id DESC
            """,
            tuple(params),
        )
        return [_row_to_archive_item(row) for row in rows]

    async def delete_archive_item(
        self,
        *,
        source_id: str,
        target_user_id: str,
        target_agent_id: str,
        archive_item_id: str,
    ) -> bool:
        """删除归档文件状态。"""
        db = self._require_db()
        result = await self._call_db(
            "delete archive item",
            db.execute,
            """
                DELETE FROM swe_file_governance_archive_items
                WHERE source_id = %s
                    AND target_user_id = %s
                    AND target_agent_id = %s
                    AND archive_item_id = %s
            """,
            (
                source_id,
                target_user_id,
                target_agent_id,
                archive_item_id,
            ),
        )
        return bool(result)

    async def upsert_protected_file(
        self,
        record: ProtectedFileRecord,
    ) -> None:
        """幂等写入受保护文件状态。"""
        db = self._require_db()
        await self._call_db(
            "upsert protected file",
            db.execute,
            """
                INSERT INTO swe_file_governance_protected_files (
                    source_id, target_user_id, target_agent_id, path,
                    protected_at, protected_by, reason, exists_flag,
                    size_bytes, mtime
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    protected_at = VALUES(protected_at),
                    protected_by = VALUES(protected_by),
                    reason = VALUES(reason),
                    exists_flag = VALUES(exists_flag),
                    size_bytes = VALUES(size_bytes),
                    mtime = VALUES(mtime),
                    updated_at = CURRENT_TIMESTAMP
            """,
            (
                record.source_id,
                record.target_user_id,
                record.target_agent_id,
                record.path,
                record.protected_at,
                record.protected_by,
                record.reason,
                int(record.exists),
                record.size_bytes,
                record.mtime,
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
        db = self._require_db()
        result = await self._call_db(
            "delete protected file",
            db.execute,
            """
                DELETE FROM swe_file_governance_protected_files
                WHERE source_id = %s
                    AND target_user_id = %s
                    AND target_agent_id = %s
                    AND path = %s
            """,
            (source_id, target_user_id, target_agent_id, path),
        )
        return bool(result)

    async def list_protected_files(
        self,
        source_id: str,
        *,
        target_user_ids: Optional[Iterable[str]] = None,
        target_agent_id: Optional[str] = None,
    ) -> list[ProtectedFileRecord]:
        """读取受保护文件状态。"""
        db = self._require_db()
        where, params = _build_file_state_where(
            source_id,
            target_user_ids=target_user_ids,
            target_agent_id=target_agent_id,
        )
        rows = await self._call_db(
            "list protected files",
            db.fetch_all,
            f"""
                SELECT source_id, target_user_id, target_agent_id, path,
                    protected_at, protected_by, reason, exists_flag,
                    size_bytes, mtime
                FROM swe_file_governance_protected_files
                WHERE {where}
                ORDER BY protected_at DESC, path ASC
            """,
            tuple(params),
        )
        return [_row_to_protected_file(row) for row in rows]

    async def upsert_cleanup_audit(
        self,
        record: CleanupAuditRecord,
    ) -> None:
        """幂等写入管理员清理审计。"""
        db = self._require_db()
        await self._call_db(
            "upsert cleanup audit",
            db.execute,
            """
                INSERT INTO swe_file_governance_cleanup_audits (
                    event_id, occurred_at, operation, status, actor_user_id,
                    actor_role, source_id, source_name, target_user_id,
                    target_agent_id, scope, files_count, total_size_bytes,
                    reason, error_text, raw_audit_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    occurred_at = VALUES(occurred_at),
                    operation = VALUES(operation),
                    status = VALUES(status),
                    actor_user_id = VALUES(actor_user_id),
                    actor_role = VALUES(actor_role),
                    source_name = VALUES(source_name),
                    target_user_id = VALUES(target_user_id),
                    target_agent_id = VALUES(target_agent_id),
                    scope = VALUES(scope),
                    files_count = VALUES(files_count),
                    total_size_bytes = VALUES(total_size_bytes),
                    reason = VALUES(reason),
                    error_text = VALUES(error_text),
                    raw_audit_json = VALUES(raw_audit_json),
                    updated_at = CURRENT_TIMESTAMP
            """,
            (
                record.event_id,
                record.timestamp,
                record.operation,
                record.status,
                record.actor_user_id,
                record.actor_role,
                record.source_id,
                record.source_name,
                record.target_user_id,
                record.target_agent_id,
                record.scope,
                record.files_count,
                record.total_size_bytes,
                record.reason,
                record.error,
                _dump_json(record.raw_audit),
            ),
        )

    async def list_cleanup_audits(
        self,
        source_id: str,
        *,
        target_user_ids: Optional[Iterable[str]] = None,
        target_agent_id: Optional[str] = None,
    ) -> list[CleanupAuditRecord]:
        """读取管理员清理审计。"""
        db = self._require_db()
        where, params = _build_file_state_where(
            source_id,
            target_user_ids=target_user_ids,
            target_agent_id=target_agent_id,
        )
        rows = await self._call_db(
            "list cleanup audits",
            db.fetch_all,
            f"""
                SELECT event_id, occurred_at, operation, status,
                    actor_user_id, actor_role, source_id, source_name,
                    target_user_id, target_agent_id, scope, files_count,
                    total_size_bytes, reason, error_text, raw_audit_json
                FROM swe_file_governance_cleanup_audits
                WHERE {where}
                ORDER BY occurred_at DESC, event_id DESC
            """,
            tuple(params),
        )
        return [_row_to_cleanup_audit(row) for row in rows]

    async def upsert_reconcile_health(
        self,
        record: ReconcileHealthRecord,
    ) -> None:
        """幂等写入待补偿或待对账健康状态。"""
        db = self._require_db()
        await self._call_db(
            "upsert reconcile health",
            db.execute,
            """
                INSERT INTO swe_continuous_governance_reconcile_health (
                    source_id, target_user_id, target_agent_id, entity_type,
                    entity_id, status, reason, error_text, payload_json,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    reason = VALUES(reason),
                    error_text = VALUES(error_text),
                    payload_json = VALUES(payload_json),
                    updated_at = VALUES(updated_at)
            """,
            (
                record.source_id,
                record.target_user_id,
                record.target_agent_id,
                record.entity_type,
                record.entity_id,
                record.status,
                record.reason,
                record.error,
                _dump_json(record.payload),
                record.updated_at,
            ),
        )

    async def list_reconcile_health(
        self,
        source_id: str,
    ) -> list[ReconcileHealthRecord]:
        """读取当前 source 的待补偿或待对账健康状态。"""
        db = self._require_db()
        rows = await self._call_db(
            "list reconcile health",
            db.fetch_all,
            """
                SELECT source_id, target_user_id, target_agent_id,
                    entity_type, entity_id, status, reason, error_text,
                    payload_json, updated_at
                FROM swe_continuous_governance_reconcile_health
                WHERE source_id = %s
                    AND status IN ('pending', 'failed', 'reconcile_needed')
                ORDER BY updated_at DESC, entity_type ASC, entity_id ASC
            """,
            (source_id,),
        )
        return [_row_to_reconcile_health(row) for row in rows]


def _dump_json(value: Any) -> str:
    """稳定序列化 JSON 字段，避免中文内容被转义。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: Any, default: Any) -> Any:
    """解析数据库中的 JSON 字段。"""
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _build_common_where(
    source_id: str,
    *,
    target_user_ids: Optional[Iterable[str]],
    target_agent_id: Optional[str],
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    status: Optional[str],
    trigger: Optional[str],
) -> tuple[str, list[Any]]:
    """构造治理记录报表查询条件。"""
    where, params = _build_file_state_where(
        source_id,
        target_user_ids=target_user_ids,
        target_agent_id=target_agent_id,
    )
    if start_time is not None:
        where += " AND occurred_at >= %s"
        params.append(_time_filter_value(start_time))
    if end_time is not None:
        where += " AND occurred_at <= %s"
        params.append(_time_filter_value(end_time))
    if status:
        where += " AND status = %s"
        params.append(status)
    if trigger:
        where += " AND trigger_type = %s"
        params.append(trigger)
    return where, params


def _build_file_state_where(
    source_id: str,
    *,
    target_user_ids: Optional[Iterable[str]],
    target_agent_id: Optional[str],
) -> tuple[str, list[Any]]:
    """构造 source、用户和 agent 维度的查询条件。"""
    where = "source_id = %s"
    params: list[Any] = [source_id]
    users_filter_provided = target_user_ids is not None
    users = [user_id for user_id in (target_user_ids or []) if user_id]
    if users_filter_provided and not users:
        where += " AND 1 = 0"
        return where, params
    if users:
        placeholders = ", ".join(["%s"] * len(users))
        where += f" AND target_user_id IN ({placeholders})"
        params.extend(users)
    if target_agent_id:
        where += " AND target_agent_id = %s"
        params.append(target_agent_id)
    return where, params


def _row_to_governance_record(row: dict[str, Any]) -> GovernanceRecord:
    """把数据库行转换为治理记录。"""
    return GovernanceRecord(
        source_id=str(row.get("source_id") or ""),
        target_user_id=str(row.get("target_user_id") or ""),
        target_user_name=row.get("target_user_name"),
        bbk_id=row.get("bbk_id"),
        target_agent_id=str(row.get("target_agent_id") or "default"),
        record_id=str(row.get("record_id") or ""),
        timestamp=_string_time(row.get("occurred_at")),
        trigger=str(row.get("trigger_type") or ""),
        status=str(row.get("status") or ""),
        files_optimized=list(_load_json(row.get("files_optimized_json"), [])),
        total_size_saved=int(row.get("total_size_saved") or 0),
        total_files_changed=int(row.get("total_files_changed") or 0),
        duration_ms=int(row.get("duration_ms") or 0),
        model_used=str(row.get("model_used") or ""),
        input_tokens=int(row.get("input_tokens") or 0),
        output_tokens=int(row.get("output_tokens") or 0),
        summary=str(row.get("summary") or ""),
        error=row.get("error_text"),
        rollback_timestamp=_optional_string_time(
            row.get("rollback_timestamp"),
        ),
        rollback_files=list(_load_json(row.get("rollback_files_json"), [])),
        raw_record=dict(_load_json(row.get("raw_record_json"), {})),
    )


def _row_to_archive_item(row: dict[str, Any]) -> ArchiveItemRecord:
    """把数据库行转换为归档状态记录。"""
    return ArchiveItemRecord(
        source_id=str(row.get("source_id") or ""),
        target_user_id=str(row.get("target_user_id") or ""),
        target_agent_id=str(row.get("target_agent_id") or "default"),
        archive_item_id=str(row.get("archive_item_id") or ""),
        original_path=str(row.get("original_path") or ""),
        archive_path=str(row.get("archive_path") or ""),
        size_bytes=int(row.get("size_bytes") or 0),
        mtime=_string_time(row.get("mtime")),
        archived_at=_string_time(row.get("archived_at")),
        archived_by=str(row.get("archived_by") or ""),
        archive_reason=str(row.get("archive_reason") or ""),
        expired=bool(row.get("expired")),
        raw_item=dict(_load_json(row.get("raw_item_json"), {})),
    )


def _row_to_protected_file(row: dict[str, Any]) -> ProtectedFileRecord:
    """把数据库行转换为保护文件记录。"""
    return ProtectedFileRecord(
        source_id=str(row.get("source_id") or ""),
        target_user_id=str(row.get("target_user_id") or ""),
        target_agent_id=str(row.get("target_agent_id") or "default"),
        path=str(row.get("path") or ""),
        protected_at=_string_time(row.get("protected_at")),
        protected_by=str(row.get("protected_by") or ""),
        reason=str(row.get("reason") or ""),
        exists=bool(row.get("exists_flag")),
        size_bytes=row.get("size_bytes"),
        mtime=_optional_string_time(row.get("mtime")),
    )


def _row_to_cleanup_audit(row: dict[str, Any]) -> CleanupAuditRecord:
    """把数据库行转换为清理审计记录。"""
    return CleanupAuditRecord(
        event_id=str(row.get("event_id") or ""),
        timestamp=_string_time(row.get("occurred_at")),
        operation=str(row.get("operation") or ""),
        status=str(row.get("status") or ""),
        actor_user_id=str(row.get("actor_user_id") or ""),
        actor_role=str(row.get("actor_role") or ""),
        source_id=str(row.get("source_id") or ""),
        source_name=row.get("source_name"),
        target_user_id=str(row.get("target_user_id") or ""),
        target_agent_id=str(row.get("target_agent_id") or "default"),
        scope=str(row.get("scope") or ""),
        files_count=int(row.get("files_count") or 0),
        total_size_bytes=int(row.get("total_size_bytes") or 0),
        reason=str(row.get("reason") or ""),
        error=row.get("error_text"),
        raw_audit=dict(_load_json(row.get("raw_audit_json"), {})),
    )


def _row_to_reconcile_health(row: dict[str, Any]) -> ReconcileHealthRecord:
    """把数据库行转换为健康状态记录。"""
    return ReconcileHealthRecord(
        source_id=str(row.get("source_id") or ""),
        target_user_id=str(row.get("target_user_id") or ""),
        target_agent_id=str(row.get("target_agent_id") or "default"),
        entity_type=str(row.get("entity_type") or ""),
        entity_id=str(row.get("entity_id") or ""),
        status=str(row.get("status") or ""),
        reason=str(row.get("reason") or ""),
        error=row.get("error_text"),
        payload=dict(_load_json(row.get("payload_json"), {})),
        updated_at=row.get("updated_at"),
    )


def _string_time(value: Any) -> str:
    """把时间字段转换为接口可返回的字符串。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _time_filter_value(value: datetime) -> str:
    """把时间筛选条件转换为与 VARCHAR 时间列一致的 ISO 字符串。"""
    dt = value
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    text = dt.isoformat()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def _optional_string_time(value: Any) -> str | None:
    """转换可为空的时间字段。"""
    if value is None:
        return None
    return _string_time(value)
