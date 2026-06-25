# -*- coding: utf-8 -*-
"""技能就绪检查配置与结果模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RunStatus = Literal["running", "completed", "partial", "failed"]
AggregateStatus = Literal["normal", "abnormal"]
CheckStatus = Literal["pass", "fail", "skip"]
OwnerLookupStatus = Literal["idle", "running", "completed", "failed"]


class SkillReadinessCheckConfig(BaseModel):
    """单个就绪检查的配置项。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class SkillReadinessConfig(BaseModel):
    """技能就绪检查配置载荷。"""

    model_config = ConfigDict(extra="forbid")

    checks: list[SkillReadinessCheckConfig]

    def enabled_checks(self) -> list[SkillReadinessCheckConfig]:
        """返回启用的检查项，供启动前判定复用。"""
        return [check for check in self.checks if check.enabled]

    @property
    def is_startable(self) -> bool:
        """至少有一个启用检查项时才允许启动运行。"""
        return bool(self.enabled_checks())


class SkillReadinessConfigRecord(BaseModel):
    """技能就绪检查配置持久化记录。"""

    skill_id: str = Field(..., min_length=1, max_length=200)
    config: SkillReadinessConfig
    updated_at: datetime | None = None


class SkillReadinessOwner(BaseModel):
    """待检查用户的轻量身份信息。"""

    user_id: str = Field(..., min_length=1, max_length=128)
    user_name: str | None = Field(default=None, max_length=200)
    bbk_id: str | None = Field(default=None, max_length=128)
    skill_name: str | None = Field(default=None, max_length=200)
    market_version: str | None = Field(default=None, max_length=128)
    installed_version: str | None = Field(default=None, max_length=128)
    received_version: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    has_update: bool | None = None


class SkillReadinessRunProgress(BaseModel):
    """技能就绪检查运行进度。"""

    run_id: str = Field(..., min_length=1, max_length=64)
    source_id: str = Field(..., min_length=1, max_length=128)
    skill_id: str = Field(..., min_length=1, max_length=200)
    status: RunStatus
    total_users: int = Field(default=0, ge=0)
    completed_users: int = Field(default=0, ge=0)
    failed_users: int = Field(default=0, ge=0)
    failure_summary: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None


class SkillReadinessCheckResult(BaseModel):
    """单个用户的一项就绪检查结果。"""

    check_name: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=200)
    status: CheckStatus
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = Field(default=0, ge=0)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        """检查结果状态只允许 pass/fail/skip。"""
        if value not in {"pass", "fail", "skip"}:
            raise ValueError("check status must be one of pass/fail/skip")
        return value


class SkillReadinessUserResult(BaseModel):
    """单个用户的就绪检查聚合结果。"""

    user_id: str = Field(..., min_length=1, max_length=128)
    user_name: str | None = Field(default=None, max_length=200)
    bbk_id: str | None = Field(default=None, max_length=128)
    aggregate_status: AggregateStatus
    summary: str = ""
    duration_ms: int = Field(default=0, ge=0)
    checks: list[SkillReadinessCheckResult]


class SkillReadinessCheckSummary(BaseModel):
    """一次运行中单项检查的聚合计数。"""

    check_name: str
    display_name: str
    total: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    skip_count: int = Field(ge=0)


class SkillReadinessConfigCheckSummary(BaseModel):
    """前端展示用的检查配置摘要。"""

    name: str
    display_name: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class SkillReadinessOwnerSummary(BaseModel):
    """技能拥有用户聚合摘要。"""

    total_users: int = Field(default=0, ge=0)
    lookup_failed_users: int = Field(default=0, ge=0)
    failure_summary: str | None = None


class SkillReadinessOwnerSnapshot(BaseModel):
    """最近一次技能拥有用户查询快照。"""

    source_id: str = Field(..., min_length=1, max_length=128)
    skill_id: str = Field(..., min_length=1, max_length=200)
    status: OwnerLookupStatus = "idle"
    total_users: int = Field(default=0, ge=0)
    owner_users: int = Field(default=0, ge=0)
    failed_users: int = Field(default=0, ge=0)
    failure_summary: str | None = None
    owners: list[SkillReadinessOwner] = Field(default_factory=list)
    updated_at: datetime | None = None

    @property
    def owner_summary(self) -> SkillReadinessOwnerSummary:
        """返回 overview 直接展示的拥有用户摘要。"""
        return SkillReadinessOwnerSummary(
            total_users=self.owner_users,
            lookup_failed_users=self.failed_users,
            failure_summary=self.failure_summary,
        )


class SkillReadinessRunSummary(SkillReadinessRunProgress):
    """运行进度和检查项聚合摘要。"""

    check_summaries: list[SkillReadinessCheckSummary] = Field(
        default_factory=list,
    )


class SkillReadinessOverview(BaseModel):
    """技能可执行性总览响应。"""

    skill_id: str
    config_found: bool
    startable: bool
    config_message: str
    config_checks: list[SkillReadinessConfigCheckSummary] = Field(
        default_factory=list,
    )
    owner_summary: SkillReadinessOwnerSummary
    owners: list[SkillReadinessOwner] = Field(default_factory=list)
    owner_lookup_status: OwnerLookupStatus = "idle"
    owner_lookup_updated_at: datetime | None = None
    latest_run: SkillReadinessRunSummary | None = None


class SkillReadinessStartRunResponse(BaseModel):
    """启动可执行性检查后的响应。"""

    run: SkillReadinessRunProgress | None = None
    reused: bool = False
    owner_lookup_only: bool = False
    owner_lookup_scheduled: bool = False


class SkillReadinessResultsPage(BaseModel):
    """分页用户结果响应。"""

    run: SkillReadinessRunProgress
    items: list[SkillReadinessUserResult]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
