# -*- coding: utf-8 -*-
"""持续治理数据库读模型的数据结构。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

GOVERNANCE_ID_MAX_LENGTH = 128


class GovernanceRecord(BaseModel):
    """管理侧持续治理执行记录。"""

    source_id: str
    target_user_id: str
    target_user_name: Optional[str] = None
    bbk_id: Optional[str] = None
    target_agent_id: str = "default"
    record_id: str
    timestamp: str
    trigger: str
    status: str
    files_optimized: list[str] = Field(default_factory=list)
    total_size_saved: int = 0
    total_files_changed: int = 0
    duration_ms: int = 0
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    summary: str = ""
    error: Optional[str] = None
    rollback_timestamp: Optional[str] = None
    rollback_files: list[str] = Field(default_factory=list)
    raw_record: dict[str, Any] = Field(default_factory=dict)


class ArchiveItemRecord(BaseModel):
    """文件归档状态读模型记录。"""

    source_id: str
    target_user_id: str
    target_agent_id: str = "default"
    archive_item_id: str
    original_path: str
    archive_path: str
    size_bytes: int
    mtime: str
    archived_at: str
    archived_by: str
    archive_reason: str
    expired: bool = False
    raw_item: dict[str, Any] = Field(default_factory=dict)


class ProtectedFileRecord(BaseModel):
    """文件保护状态读模型记录。"""

    source_id: str
    target_user_id: str
    target_agent_id: str = "default"
    path: str
    protected_at: str
    protected_by: str
    reason: str
    exists: bool
    size_bytes: Optional[int] = None
    mtime: Optional[str] = None


class CleanupAuditRecord(BaseModel):
    """管理员文件清理审计读模型记录。"""

    event_id: str
    timestamp: str
    operation: str
    status: str
    actor_user_id: str
    actor_role: str
    source_id: str
    source_name: Optional[str] = None
    target_user_id: str
    target_agent_id: str = "default"
    scope: str
    files_count: int
    total_size_bytes: int
    reason: str
    error: Optional[str] = None
    raw_audit: dict[str, Any] = Field(default_factory=dict)


class ReconcileHealthRecord(BaseModel):
    """等待补偿或对账的持续治理健康状态。"""

    source_id: str
    target_user_id: str
    target_agent_id: str = "default"
    entity_type: str
    entity_id: str
    status: str
    reason: str
    error: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None


class GovernanceReportSummary(BaseModel):
    """持续治理分析汇总指标。"""

    covered_users: int
    governed_users: int
    ungoverned_users: int
    total_executions: int
    success_count: int
    failed_count: int
    success_rate: float
    total_files_changed: int
    total_size_saved: int
    avg_duration_ms: int
    last_execution: Optional[str] = None


class GovernanceReportTrendPoint(BaseModel):
    """持续治理趋势点。"""

    date: str
    executions: int
    manual_count: int = 0
    cron_count: int = 0
    success_count: int
    failed_count: int
    total_size_saved: int


class GovernanceReportStatusBucket(BaseModel):
    """持续治理状态分布桶。"""

    status: str
    count: int


class GovernanceReportBbkBucket(BaseModel):
    """持续治理机构分布桶。"""

    bbk_id: str
    user_count: int
    governed_users: int
    executions: int
    success_rate: float


class GovernanceReportUserRow(BaseModel):
    """持续治理用户明细行。"""

    user_id: str
    user_name: Optional[str] = None
    bbk_id: Optional[str] = None
    agents: list[str]
    executions: int
    success_rate: float
    failed_count: int
    total_files_changed: int
    total_size_saved: int
    last_execution: Optional[str] = None
    latest_error: Optional[str] = None


class GovernanceReportRecordRow(BaseModel):
    """持续治理用户下钻记录行。"""

    id: str
    timestamp: str
    trigger: str
    status: str
    agent_id: str
    files_optimized: list[str]
    total_size_saved: int
    total_files_changed: int
    duration_ms: int
    model_used: str
    input_tokens: int
    output_tokens: int
    summary: str
    error: Optional[str] = None


class GovernanceReportData(BaseModel):
    """持续治理分析服务返回值。"""

    summary: GovernanceReportSummary
    trends: list[GovernanceReportTrendPoint]
    status_distribution: list[GovernanceReportStatusBucket]
    bbk_distribution: list[GovernanceReportBbkBucket]
    users: list[GovernanceReportUserRow]
    total: int
    page: int
    page_size: int
    health: list[ReconcileHealthRecord] = Field(default_factory=list)


class GovernanceUserRecordsData(BaseModel):
    """持续治理用户下钻服务返回值。"""

    records: list[GovernanceReportRecordRow]
    total: int
    page: int
    page_size: int


class ArchiveReportSummaryData(BaseModel):
    """文件治理状态汇总指标。"""

    archived_files: int
    archived_size_bytes: int
    pending_purge_files: int
    pending_purge_size_bytes: int
    protected_files: int
    protected_existing_files: int
    protected_missing_files: int
    purge_operations: int
    purge_success_operations: int
    purge_failed_operations: int
    purged_files: int
    purged_size_bytes: int
    last_purge_at: Optional[str] = None


class ArchiveReportData(BaseModel):
    """文件治理状态报告服务返回值。"""

    summary: ArchiveReportSummaryData
    health: list[ReconcileHealthRecord] = Field(default_factory=list)
