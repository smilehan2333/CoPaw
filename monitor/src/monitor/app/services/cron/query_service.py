# -*- coding: utf-8 -*-
"""Query service for cron job and execution data.

Provides methods to query job definitions and execution history
for the frontend overview page.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Any, Dict
from zoneinfo import ZoneInfo

from ...database import DatabaseConnection, get_db_connection
from ...models.cron import (
    CronOverviewBranchExecutionItem,
    CronOverviewBranchReadItem,
    CronOverviewDistributionItem,
    CronOverviewMetricItem,
    CronOverviewResponse,
    CronOverviewStatsResponse,
    CronBranchRankingResponse,
    CronBranchRankingItem,
    CronBranchErrorResponse,
    CronBranchErrorRankItem,
    CronErrorReasonItem,
    BranchSkillItem,
    BranchSkillResponse,
    BranchManagerSummaryItem,
    BranchManagerSummaryResponse,
    BranchSkillManagerItem,
    BranchSkillManagerResponse,
    BranchSkillManagerCustomerItem,
    BranchSkillManagerCustomerResponse,
    ManagerSkillItem,
    ManagerSkillResponse,
    ManagerCustomerItem,
    ManagerCustomerResponse,
    CronBranchTaskRankingItem,
    CronBranchTaskRankingResponse,
    CronJobModel,
    CronJobQueryParams,
    ExecutionModel,
    ExecutionQueryParams,
    PaginatedResponse,
    SubscriptionDetailItem,
    SubscriptionOverviewItem,
    UnreadCountResponse,
)
from ....utils.bbk import get_bbk_name_by_id

# 东八区时区（北京时间）
BEIJING_TZ = ZoneInfo("Asia/Shanghai")

# 注意：数据库存储的时间已经是东八区时间（北京时间），无需再转换
# monitor_sync_client.py 在写入时已将 UTC 转为东八区，直接读取即可

logger = logging.getLogger(__name__)


# 任务定义表的时间字段（无需转换，直接读取）
JOB_TIME_FIELDS = ["created_at", "updated_at", "deleted_at"]

# 执行历史表的时间字段（无需转换，直接读取）
EXECUTION_TIME_FIELDS = [
    "scheduled_time",
    "actual_time",
    "end_time",
    "notification_due_at",
    "notification_sent_at",
    "notification_locked_at",
    "created_at",
]


def convert_row_times_direct(row: dict, time_fields: List[str]) -> dict:
    """直接读取时间字段，不做时区转换。

    数据库存储的已经是东八区时间，无需转换。

    Args:
        row: 数据库返回的行字典
        time_fields: 时间字段名列表

    Returns:
        原始行字典（时间字段不变）
    """
    return row


class QueryService:
    """Service for querying cron data."""

    # 分行综合排行仅展示的 10 项技能（同时匹配英文标识和中文名称）
    _ALLOWED_BRANCH_SKILLS: set[str] = {
        "insurance_mkt",
        "保险营销客户分析技能",
        "deposit_scale_growth_skill",
        "存款规模增长与产品配置技能",
        "fund_redeem_monitor",
        "基金赎回实时监控技能",
        "lc_breaking",
        "单一持仓理财/定期客户破冰方案",
        "global-market-report",
        "全球市场复盘报告",
        "存款到期客户经营方案技能",
        "高AUM理财低收益客户调仓技能",
        "基金亏损客户关怀陪伴文案",
        "智能推荐保险计划书",
        "黄金持仓客户陪伴技能",
    }

    def __init__(self) -> None:
        """Initialize query service."""
        pass

    def _build_job_where_clause(
        self,
        params: CronJobQueryParams,
    ) -> tuple[str, list]:
        """构建任务查询的 WHERE 子句。

        Args:
            params: 查询参数

        Returns:
            (where_clause, sql_params) 元组
        """
        conditions = ["deleted_at IS NULL"]
        sql_params: list = []

        if params.tenant_id:
            conditions.append("tenant_id = %s")
            sql_params.append(params.tenant_id)
        if params.bbk_id:
            conditions.append("bbk_id = %s")
            sql_params.append(params.bbk_id)
        if params.source_id:
            conditions.append("source_id = %s")
            sql_params.append(params.source_id)
        if params.creator_user_id:
            conditions.append("creator_user_id = %s")
            sql_params.append(params.creator_user_id)
        if params.job_origin:
            conditions.append("job_origin = %s")
            sql_params.append(params.job_origin)
        if params.status:
            conditions.append("status = %s")
            sql_params.append(params.status)
        if params.enabled is not None:
            conditions.append("enabled = %s")
            sql_params.append(params.enabled)

        return " AND ".join(conditions), sql_params

    async def _fetch_job_execution_counts(
        self,
        db: DatabaseConnection,
        job_ids: list[str],
    ) -> dict[str, int]:
        """查询任务的执行次数。

        Args:
            db: 数据库连接
            job_ids: 任务ID列表

        Returns:
            job_id -> count 的映射字典
        """
        if not job_ids:
            return {}
        placeholders = ",".join("%s" for _ in job_ids)
        sql = f"""
            SELECT job_id, COUNT(*) as count
            FROM swe_cron_executions
            WHERE job_id IN ({placeholders})
            GROUP BY job_id
        """
        rows = await db.fetch_all(sql, tuple(job_ids))
        return {row.get("job_id"): row.get("count", 0) for row in rows}

    def _determine_execution_status(
        self,
        status: str,
        async_status: str | None,
    ) -> str:
        """根据执行状态和异步状态确定综合状态。

        Args:
            status: 执行状态
            async_status: 异步状态

        Returns:
            综合状态字符串
        """
        if status == "success":
            if async_status == "success":
                return "success"
            if async_status == "error":
                return "error"
            return "running"
        if status in ("error", "timeout"):
            return "error"
        if status in ("cancelled", "skipped"):
            return status
        return status

    async def _fetch_job_today_status(
        self,
        db: DatabaseConnection,
        job_ids: list[str],
    ) -> dict[str, str]:
        """查询任务今日最新执行状态。

        Args:
            db: 数据库连接
            job_ids: 任务ID列表

        Returns:
            job_id -> status 的映射字典
        """
        if not job_ids:
            return {}
        placeholders = ",".join("%s" for _ in job_ids)
        today_start = (
            datetime.now(BEIJING_TZ)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .replace(tzinfo=None)
        )
        sql = f"""
            SELECT job_id, status, async_status
            FROM swe_cron_executions
            WHERE job_id IN ({placeholders})
            AND actual_time >= %s
            ORDER BY actual_time DESC
        """
        rows = await db.fetch_all(sql, tuple(job_ids) + (today_start,))
        status_map: dict[str, str] = {}
        for row in rows:
            job_id = row.get("job_id")
            if job_id not in status_map:
                status_map[job_id] = self._determine_execution_status(
                    row.get("status"),
                    row.get("async_status"),
                )
        return status_map

    async def list_jobs(
        self,
        params: CronJobQueryParams,
    ) -> PaginatedResponse[CronJobModel]:
        """List cron jobs with pagination and filters.

        Args:
            params: Query parameters

        Returns:
            Paginated response with job list
        """
        db = get_db_connection()
        where_clause, sql_params = self._build_job_where_clause(params)

        # Count total
        count_sql = (
            f"SELECT COUNT(*) as count FROM swe_cron_jobs WHERE {where_clause}"
        )
        count_result = await db.fetch_one(count_sql, tuple(sql_params))
        total = count_result.get("count", 0) if count_result else 0

        # Query with pagination
        offset = (params.page - 1) * params.page_size
        query_sql = f"""
            SELECT * FROM swe_cron_jobs
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        query_params = tuple(sql_params) + (params.page_size, offset)
        rows = await db.fetch_all(query_sql, query_params)

        items = [
            CronJobModel.model_validate(
                convert_row_times_direct(row, JOB_TIME_FIELDS),
            )
            for row in rows
        ]

        # Query execution count and today's status for each job
        if items:
            job_ids = [job.id for job in items]
            count_map = await self._fetch_job_execution_counts(db, job_ids)
            status_map = await self._fetch_job_today_status(db, job_ids)
            for job in items:
                job.execution_count = count_map.get(job.id, 0)
                job.today_status = status_map.get(job.id)

        return PaginatedResponse(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

    async def get_job(
        self,
        job_id: str,
        source_id: Optional[str] = None,
    ) -> Optional[CronJobModel]:
        """Get a single job by ID.

        Args:
            job_id: Job ID
            source_id: Source ID filter

        Returns:
            CronJobModel or None if not found
        """
        db = get_db_connection()
        conditions = ["id = %s", "deleted_at IS NULL"]
        sql_params: List = [job_id]

        if source_id:
            conditions.append("source_id = %s")
            sql_params.append(source_id)

        row = await db.fetch_one(
            f"SELECT * FROM swe_cron_jobs WHERE {' AND '.join(conditions)}",
            tuple(sql_params),
        )

        if not row:
            return None

        # 直接读取，不做时区转换（数据库已是东八区时间）
        return CronJobModel.model_validate(
            convert_row_times_direct(row, JOB_TIME_FIELDS),
        )

    async def list_executions(
        self,
        params: ExecutionQueryParams,
    ) -> PaginatedResponse[ExecutionModel]:
        """List execution history with pagination and filters.

        Args:
            params: Query parameters

        Returns:
            Paginated response with execution list
        """
        db = get_db_connection()

        # Build WHERE clause
        conditions: List[str] = []
        sql_params: List = []

        if params.job_id:
            conditions.append("e.job_id = %s")
            sql_params.append(params.job_id)

        if params.tenant_id:
            conditions.append("e.tenant_id = %s")
            sql_params.append(params.tenant_id)

        if params.bbk_id:
            conditions.append("j.bbk_id = %s")
            sql_params.append(params.bbk_id)

        # source_id 需要通过 JOIN jobs 表筛选
        if params.source_id:
            conditions.append("j.source_id = %s")
            sql_params.append(params.source_id)

        if params.status:
            if params.status == "failed":
                # 综合失败状态：status='error' OR (status='success' AND async_status='error')
                conditions.append(
                    "(e.status = 'error' OR (e.status = 'success' AND e.async_status = 'error'))",
                )
            else:
                conditions.append("e.status = %s")
                sql_params.append(params.status)
            conditions.append("j.status != 'deleted'")

        if params.start_time:
            conditions.append("e.actual_time >= %s")
            sql_params.append(params.start_time)

        if params.end_time:
            conditions.append("e.actual_time <= %s")
            sql_params.append(params.end_time)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        logger.warning(
            "[cron executions debug] built filters: bbk_id=%s source_id=%s where=%s params=%s",
            params.bbk_id,
            params.source_id,
            where_clause,
            sql_params,
        )

        # Count total - 需要 JOIN jobs 表来支持 source_id 筛选
        count_sql = f"""
            SELECT COUNT(*) as count
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {where_clause}
        """
        count_result = await db.fetch_one(count_sql, tuple(sql_params))
        total = count_result.get("count", 0) if count_result else 0
        logger.warning(
            "[cron executions debug] count result: bbk_id=%s total=%s",
            params.bbk_id,
            total,
        )

        # Query with pagination - JOIN with jobs table to get tenant metadata.
        offset = (params.page - 1) * params.page_size
        query_sql = f"""
            SELECT e.*, j.tenant_name, j.bbk_id AS bbk_id
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {where_clause}
            ORDER BY e.actual_time DESC
            LIMIT %s OFFSET %s
        """
        query_params = tuple(sql_params) + (params.page_size, offset)

        rows = await db.fetch_all(query_sql, query_params)
        logger.warning(
            "[cron executions debug] rows sample: requested_bbk_id=%s returned=%s sample=%s",
            params.bbk_id,
            len(rows),
            [
                {
                    "id": row.get("id"),
                    "job_id": row.get("job_id"),
                    "job_bbk_id": row.get("bbk_id"),
                    "bbk_id": row.get("bbk_id"),
                    "tenant_id": row.get("tenant_id"),
                    "status": row.get("status"),
                }
                for row in rows[:5]
            ],
        )

        # 直接读取，不做时区转换（数据库已是东八区时间）
        items = [
            ExecutionModel.model_validate(
                convert_row_times_direct(row, EXECUTION_TIME_FIELDS),
            )
            for row in rows
        ]

        return PaginatedResponse(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

    async def get_execution(
        self,
        execution_id: int,
        source_id: Optional[str] = None,
    ) -> Optional[ExecutionModel]:
        """Get a single execution by ID.

        Args:
            execution_id: Execution ID
            source_id: Source ID filter

        Returns:
            ExecutionModel or None if not found
        """
        db = get_db_connection()
        conditions = ["e.id = %s"]
        sql_params: List = [execution_id]

        if source_id:
            conditions.append("j.source_id = %s")
            sql_params.append(source_id)

        row = await db.fetch_one(
            f"""
            SELECT e.*
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {' AND '.join(conditions)}
            """,
            tuple(sql_params),
        )

        if not row:
            return None

        # 直接读取，不做时区转换（数据库已是东八区时间）
        return ExecutionModel.model_validate(
            convert_row_times_direct(row, EXECUTION_TIME_FIELDS),
        )

    async def get_executions_for_export(
        self,
        job_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        source_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 10000,
    ) -> List[ExecutionModel]:
        """Get executions for export without pagination.

        Args:
            job_id: Job ID filter
            tenant_id: Tenant ID filter
            source_id: Source ID filter (来源标识)
            status: Status filter
            start_time: Start time filter
            end_time: End time filter
            limit: Max records to return

        Returns:
            List of ExecutionModel
        """
        db = get_db_connection()

        # Build WHERE clause - 需要 JOIN jobs 表来支持 source_id 筛选
        conditions: List[str] = []
        sql_params: List = []

        if job_id:
            conditions.append("e.job_id = %s")
            sql_params.append(job_id)

        if tenant_id:
            conditions.append("e.tenant_id = %s")
            sql_params.append(tenant_id)

        # source_id 需要通过 JOIN jobs 表筛选
        if source_id:
            conditions.append("j.source_id = %s")
            sql_params.append(source_id)

        if status:
            conditions.append("e.status = %s")
            sql_params.append(status)

        if start_time:
            conditions.append("e.actual_time >= %s")
            sql_params.append(start_time)

        if end_time:
            conditions.append("e.actual_time <= %s")
            sql_params.append(end_time)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 需要 JOIN jobs 表来支持 source_id 筛选
        query_sql = f"""
            SELECT e.*
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {where_clause}
            ORDER BY e.actual_time DESC
            LIMIT %s
        """
        query_params = tuple(sql_params) + (limit,)

        rows = await db.fetch_all(query_sql, query_params)

        # 直接读取，不做时区转换（数据库已是东八区时间）
        return [
            ExecutionModel.model_validate(
                convert_row_times_direct(row, EXECUTION_TIME_FIELDS),
            )
            for row in rows
        ]

    async def get_jobs_for_export(
        self,
        tenant_id: Optional[str] = None,
        bbk_id: Optional[str] = None,
        source_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        status: Optional[str] = None,
        limit: int = 10000,
    ) -> List[CronJobModel]:
        """Get jobs for export without pagination.

        Args:
            tenant_id: Tenant ID filter
            bbk_id: BBK ID filter (分行号)
            source_id: Source ID filter (来源标识)
            enabled: Enabled filter (是否启用)
            status: Status filter
            limit: Max records to return

        Returns:
            List of CronJobModel
        """
        db = get_db_connection()

        # Build WHERE clause
        conditions = ["deleted_at IS NULL"]
        sql_params: List = []

        if tenant_id:
            conditions.append("tenant_id = %s")
            sql_params.append(tenant_id)

        if bbk_id:
            conditions.append("bbk_id = %s")
            sql_params.append(bbk_id)

        if source_id:
            conditions.append("source_id = %s")
            sql_params.append(source_id)

        if enabled is not None:
            conditions.append("enabled = %s")
            sql_params.append(enabled)

        if status:
            conditions.append("status = %s")
            sql_params.append(status)

        where_clause = " AND ".join(conditions)

        query_sql = f"""
            SELECT * FROM swe_cron_jobs
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
        """
        query_params = tuple(sql_params) + (limit,)

        rows = await db.fetch_all(query_sql, query_params)

        # 直接读取，不做时区转换（数据库已是东八区时间）
        items = [
            CronJobModel.model_validate(
                convert_row_times_direct(row, JOB_TIME_FIELDS),
            )
            for row in rows
        ]
        # Query execution count for each job
        if items:
            job_ids = [job.id for job in items]
            placeholders = ",".join("%s" for _ in job_ids)
            count_sql = f"""
                SELECT job_id, COUNT(*) as count
                FROM swe_cron_executions
                WHERE job_id IN ({placeholders})
                GROUP BY job_id
            """
            count_rows = await db.fetch_all(count_sql, tuple(job_ids))
            count_map = {
                row.get("job_id"): row.get("count", 0) for row in count_rows
            }
            for job in items:
                job.execution_count = count_map.get(job.id, 0)

        return items

    async def get_filter_options(
        self,
        source_id: Optional[str] = None,
    ) -> dict:
        """获取所有筛选项的下拉选项列表。

        从任务表和执行表中聚合获取可选值，用于前端下拉框。

        Args:
            source_id: Source ID filter

        Returns:
            包含各筛选项列表的字典
        """
        db = get_db_connection()
        source_condition = ""
        source_params: Tuple = ()
        if source_id:
            source_condition = " AND source_id = %s"
            source_params = (source_id,)

        # 获取用户列表（按 tenant_id 分组去重，避免同一用户多条记录）
        users_sql = f"""
            SELECT tenant_id, MAX(tenant_name) as tenant_name
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
                AND tenant_id IS NOT NULL
                AND tenant_id != ''
                {source_condition}
            GROUP BY tenant_id
            ORDER BY tenant_name, tenant_id
        """
        users_rows = await db.fetch_all(users_sql, source_params)
        users = [
            {
                "value": row["tenant_id"],
                "label": f"{row['tenant_name'] or ''}/{row['tenant_id']}",
            }
            for row in users_rows
        ]

        # 获取分行列表（bbk_id）
        bbk_sql = f"""
            SELECT DISTINCT bbk_id
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
                AND bbk_id IS NOT NULL
                AND bbk_id != ''
                {source_condition}
            ORDER BY bbk_id
        """
        bbk_rows = await db.fetch_all(bbk_sql, source_params)
        bbk_ids = [
            {"value": row["bbk_id"], "label": row["bbk_id"]}
            for row in bbk_rows
        ]

        # 获取渠道列表（channel）
        channel_sql = f"""
            SELECT DISTINCT channel
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
                AND channel IS NOT NULL
                AND channel != ''
                {source_condition}
            ORDER BY channel
        """
        channel_rows = await db.fetch_all(channel_sql, source_params)
        channels = [
            {"value": row["channel"], "label": row["channel"]}
            for row in channel_rows
        ]

        # 获取来源/平台列表（source_id）
        source_sql = f"""
            SELECT DISTINCT source_id
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
                AND source_id IS NOT NULL
                AND source_id != ''
                {source_condition}
            ORDER BY source_id
        """
        source_rows = await db.fetch_all(source_sql, source_params)
        source_ids = [
            {"value": row["source_id"], "label": row["source_id"]}
            for row in source_rows
        ]

        # 获取任务名称列表（name）
        job_names_sql = f"""
            SELECT DISTINCT name
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
                AND name IS NOT NULL
                AND name != ''
                {source_condition}
            ORDER BY name
        """
        job_names_rows = await db.fetch_all(job_names_sql, source_params)
        job_names = [
            {"value": row["name"], "label": row["name"]}
            for row in job_names_rows
        ]

        # 获取任务ID列表（用于执行记录筛选）
        job_ids_sql = f"""
            SELECT DISTINCT id, name
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
                {source_condition}
            ORDER BY name
        """
        job_ids_rows = await db.fetch_all(job_ids_sql, source_params)
        job_ids = [
            {"value": row["id"], "label": row["name"] or row["id"]}
            for row in job_ids_rows
        ]

        return {
            "users": users,
            "bbk_ids": bbk_ids,
            "channels": channels,
            "source_ids": source_ids,
            "job_names": job_names,
            "job_ids": job_ids,
        }

    async def get_overview(
        self,
        *,
        tenant_id: Optional[str] = None,
        bbk_id: Optional[str] = None,
        source_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> CronOverviewResponse:
        """Return page-shaped aggregate data for the cron overview."""
        db = get_db_connection()
        start_time, end_time = self._resolve_today_range(start_time, end_time)
        job_where, job_params, exec_where, exec_params = (
            self._build_overview_clauses(
                tenant_id=tenant_id,
                bbk_id=bbk_id,
                source_id=source_id,
                start_time=start_time,
                end_time=end_time,
            )
        )
        job_summary = await self._fetch_overview_job_summary(
            db,
            job_where,
            job_params,
        )
        prev_job_summary = await self._fetch_previous_job_summary(
            db,
            tenant_id=tenant_id,
            bbk_id=bbk_id,
            source_id=source_id,
            start_time=start_time,
        )
        exec_summary = await self._fetch_overview_execution_summary(
            db,
            exec_where,
            exec_params,
        )
        prev_exec_summary = await self._fetch_previous_execution_summary(
            db,
            tenant_id=tenant_id,
            bbk_id=bbk_id,
            source_id=source_id,
            start_time=start_time,
            end_time=end_time,
        )

        return CronOverviewResponse(
            start_time=start_time,
            end_time=end_time,
            metrics=self._build_overview_metrics(
                job_summary,
                prev_job_summary,
                exec_summary,
                prev_exec_summary,
            ),
            task_status=self._build_task_status_distribution(job_summary),
            execution_result=await self._fetch_execution_result_distribution(
                db,
                exec_where,
                exec_params,
            ),
            read_status=await self._fetch_read_status_distribution(
                db,
                exec_where,
                exec_params,
            ),
            failure_reasons=await self._fetch_failure_reason_distribution(
                db,
                exec_where,
                exec_params,
            ),
            branch_tasks=await self._fetch_branch_task_distribution(
                db,
                job_where,
                job_params,
            ),
            branch_execution=await self._fetch_branch_execution_distribution(
                db,
                exec_where,
                exec_params,
            ),
            branch_read=await self._fetch_branch_read_distribution(
                db,
                exec_where,
                exec_params,
            ),
        )

    def _build_overview_clauses(
        self,
        *,
        tenant_id: Optional[str],
        bbk_id: Optional[str],
        source_id: Optional[str],
        start_time: datetime,
        end_time: datetime,
    ) -> Tuple[str, List, str, List]:
        job_conditions, job_params = self._build_overview_job_conditions(
            tenant_id=tenant_id,
            bbk_id=bbk_id,
            source_id=source_id,
        )
        exec_conditions, exec_params = (
            self._build_overview_execution_conditions(
                tenant_id=tenant_id,
                bbk_id=bbk_id,
                source_id=source_id,
                start_time=start_time,
                end_time=end_time,
            )
        )
        return (
            " AND ".join(job_conditions),
            job_params,
            " AND ".join(exec_conditions),
            exec_params,
        )

    async def _fetch_overview_job_summary(
        self,
        db: Any,
        job_where: str,
        job_params: List,
    ) -> Dict[str, Any]:
        row = await db.fetch_one(
            f"""
            SELECT
                COUNT(*) AS total_tasks,
                SUM(CASE WHEN job_origin = 'subscription' THEN 1 ELSE 0 END)
                    AS subscription_tasks,
                SUM(CASE WHEN job_origin != 'subscription' THEN 1 ELSE 0 END)
                    AS manual_tasks,
                SUM(
                    CASE
                        WHEN enabled = 1 AND status = 'active'
                        THEN 1 ELSE 0
                    END
                ) AS active_tasks,
                SUM(
                    CASE
                        WHEN status = 'paused'
                            AND pause_reason ='auto_unread_threshold'
                        THEN 1 ELSE 0
                    END
                ) AS auto_paused_tasks,
                SUM(
                    CASE
                        WHEN status = 'paused'
                            AND pause_reason ='manual'
                        THEN 1 ELSE 0
                    END
                ) AS paused_tasks
            FROM swe_cron_jobs j
            WHERE {job_where}
            """,
            tuple(job_params),
        )
        return row or {}

    async def _fetch_previous_job_summary(
        self,
        db: Any,
        *,
        tenant_id: Optional[str],
        bbk_id: Optional[str],
        source_id: Optional[str],
        start_time: datetime,
    ) -> Dict[str, Any]:
        conditions = [
            "j.created_at < %s",
            "(j.deleted_at IS NULL OR j.deleted_at >= %s)",
            "j.status != 'deleted'",
        ]
        sql_params: List = [start_time, start_time]

        if tenant_id:
            conditions.append("j.tenant_id = %s")
            sql_params.append(tenant_id)

        if bbk_id:
            conditions.append("j.bbk_id = %s")
            sql_params.append(bbk_id)

        if source_id:
            conditions.append("j.source_id = %s")
            sql_params.append(source_id)

        row = await db.fetch_one(
            f"""
            SELECT COUNT(*) AS total_tasks
            FROM swe_cron_jobs j
            WHERE {' AND '.join(conditions)}
            """,
            tuple(sql_params),
        )
        return row or {}

    async def _fetch_overview_execution_summary(
        self,
        db: Any,
        exec_where: str,
        exec_params: List,
    ) -> Dict[str, Any]:
        row = await db.fetch_one(
            f"""
            SELECT
                COUNT(*) AS execution_count,
                SUM(CASE WHEN e.status = 'success' THEN 1 ELSE 0 END)
                    AS success_count,
                SUM(
                    CASE
                        WHEN e.status = 'error'
                        THEN 1 ELSE 0
                    END
                ) AS failure_count,
                COALESCE(
                    AVG(CASE WHEN e.status = 'success' THEN e.duration_ms END),
                    0
                ) AS avg_duration_ms
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {exec_where}
            """,
            tuple(exec_params),
        )
        return row or {}

    async def _fetch_previous_execution_summary(
        self,
        db: Any,
        *,
        tenant_id: Optional[str],
        bbk_id: Optional[str],
        source_id: Optional[str],
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        prev_start, prev_end = self._resolve_previous_period(
            start_time,
            end_time,
        )
        prev_conditions, prev_params = (
            self._build_overview_execution_conditions(
                tenant_id=tenant_id,
                bbk_id=bbk_id,
                source_id=source_id,
                start_time=prev_start,
                end_time=prev_end,
            )
        )
        return await self._fetch_overview_execution_summary(
            db,
            " AND ".join(prev_conditions),
            prev_params,
        )

    def _resolve_previous_period(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> Tuple[datetime, datetime]:
        period_days = (end_time - start_time).days
        if period_days == 0:
            return start_time - timedelta(days=1), end_time - timedelta(days=1)
        return (
            start_time - timedelta(days=period_days),
            start_time - timedelta(seconds=1),
        )

    def _build_overview_metrics(
        self,
        job_summary: Dict[str, Any],
        prev_job_summary: Dict[str, Any],
        exec_summary: Dict[str, Any],
        prev_exec_summary: Dict[str, Any],
    ) -> List[CronOverviewMetricItem]:
        total_tasks = int(job_summary.get("total_tasks") or 0)
        prev_total_tasks = int(prev_job_summary.get("total_tasks") or 0)
        execution_count = int(exec_summary.get("execution_count") or 0)
        success_rate = self._calculate_success_rate(exec_summary)
        avg_duration_ms = float(exec_summary.get("avg_duration_ms") or 0)
        prev_success_rate = self._calculate_success_rate(prev_exec_summary)

        total_compare, total_trend = self._calc_total_delta(
            total_tasks,
            prev_total_tasks,
        )
        runs_compare, runs_trend = self._calc_compare(
            execution_count,
            int(prev_exec_summary.get("execution_count") or 0),
        )
        success_rate_compare, success_rate_trend = self._calc_compare(
            success_rate,
            prev_success_rate,
        )
        avg_cost_compare, avg_cost_trend = self._calc_compare(
            avg_duration_ms,
            float(prev_exec_summary.get("avg_duration_ms") or 0),
        )

        return [
            CronOverviewMetricItem(
                key="total",
                value=total_tasks,
                compare=total_compare,
                trend=total_trend,
            ),
            CronOverviewMetricItem(
                key="subscribed",
                value=int(job_summary.get("subscription_tasks") or 0),
            ),
            CronOverviewMetricItem(
                key="created",
                value=int(job_summary.get("manual_tasks") or 0),
            ),
            CronOverviewMetricItem(
                key="runs",
                value=execution_count,
                compare=runs_compare,
                trend=runs_trend,
            ),
            CronOverviewMetricItem(
                key="success_rate",
                value=success_rate,
                compare=success_rate_compare,
                trend=success_rate_trend,
            ),
            CronOverviewMetricItem(
                key="avg_cost",
                value=avg_duration_ms,
                compare=avg_cost_compare,
                trend=avg_cost_trend,
            ),
        ]

    def _calculate_success_rate(self, summary: Dict[str, Any]) -> float:
        success_count = int(summary.get("success_count") or 0)
        failure_count = int(summary.get("failure_count") or 0)
        total_count = success_count + failure_count
        return success_count / total_count * 100 if total_count else 0.0

    def _calc_total_delta(
        self,
        current: int,
        prev: int,
    ) -> Tuple[str, Optional[str]]:
        delta = current - prev
        if delta > 0:
            return f"{delta}", "up"
        if delta < 0:
            return f"{abs(delta)}", "down"
        return "", None

    def _calc_compare(
        self,
        current: float,
        prev: float,
    ) -> Tuple[str, Optional[str]]:
        if prev == 0:
            return "", None
        change = ((current - prev) / prev) * 100
        if change > 0:
            return f"+{change:.1f}%", "up"
        if change < 0:
            return f"{change:.1f}%", "down"
        return "0.0%", "up"

    def _build_task_status_distribution(
        self,
        job_summary: Dict[str, Any],
    ) -> List[CronOverviewDistributionItem]:
        return self._build_distribution(
            [
                ("生效中", int(job_summary.get("active_tasks") or 0)),
                (
                    "未读自动暂停",
                    int(job_summary.get("auto_paused_tasks") or 0),
                ),
                ("手动暂停", int(job_summary.get("paused_tasks") or 0)),
            ],
            {
                "生效中": "#2361EA",
                "未读自动暂停": "#F97212",
                "手动暂停": "#783AF1",
            },
        )

    async def _fetch_execution_result_distribution(
        self,
        db: Any,
        exec_where: str,
        exec_params: List,
    ) -> List[CronOverviewDistributionItem]:
        rows = await db.fetch_all(
            f"""
            SELECT
                CASE
                    WHEN e.status = 'success' THEN '成功'
                    WHEN e.status = 'error' THEN '失败'
                    WHEN e.status = 'cancelled' THEN '已取消/跳过'
                    ELSE e.status
                END AS name,
                COUNT(*) AS value
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {exec_where}
            GROUP BY e.status
            ORDER BY value DESC
            """,
            tuple(exec_params),
        )
        return self._build_distribution(
            self._distribution_pairs(rows),
            {
                "成功": "#13A146",
                "失败": "#f33f3d",
                "已取消/跳过": "#9b9db4",
            },
        )

    async def _fetch_read_status_distribution(
        self,
        db: Any,
        exec_where: str,
        exec_params: List,
    ) -> List[CronOverviewDistributionItem]:
        rows = await db.fetch_all(
            f"""
            SELECT
                CASE WHEN e.is_read = 1 THEN '已读' ELSE '未读' END AS name,
                COUNT(*) AS value
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {exec_where} AND e.status = 'success'
            GROUP BY e.is_read
            ORDER BY value DESC
            """,
            tuple(exec_params),
        )
        return self._build_distribution(
            self._distribution_pairs(rows),
            {"已读": "#2361EA", "未读": "#F97212"},
        )

    async def _fetch_failure_reason_distribution(
        self,
        db: Any,
        exec_where: str,
        exec_params: List,
    ) -> List[CronOverviewDistributionItem]:
        rows = await db.fetch_all(
            f"""
            SELECT
                CASE
                    WHEN e.error_message LIKE '%%channel not found%%'
                        THEN '渠道不存在'
                    WHEN e.error_message LIKE '%%cron auth user_info is expired%%'
                        THEN 'token过期'
                    WHEN e.error_message LIKE '%%Illegal Argument%%'
                        THEN '密文长度错误'
                    WHEN LOWER(e.error_message) LIKE '%%validation error for agentrequest%%'
                        THEN '智能体请求校验失败'
                    WHEN e.error_message LIKE '%%Agent execution did not complete%%'
                        THEN '模型错误'
                    ELSE '其他'
                END AS name,
                COUNT(*) AS value
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {exec_where}
              AND e.status = 'error'
              AND j.status != 'deleted'
            GROUP BY 1
            ORDER BY value DESC, name ASC
            LIMIT 10
            """,
            tuple(exec_params),
        )
        return self._build_distribution(
            self._distribution_pairs(rows),
            {
                "渠道不存在": "#ef4444",
                "token过期": "#f97316",
                "密文长度错误": "#eab308",
                "智能体请求校验失败": "#8b5cf6",
                "其他": "#64748b",
            },
        )

    async def _fetch_branch_task_distribution(
        self,
        db: Any,
        job_where: str,
        job_params: List,
    ) -> List[CronOverviewDistributionItem]:
        rows = await db.fetch_all(
            f"""
            SELECT COALESCE(NULLIF(j.bbk_id, ''), 'unknown') AS name,
                   COUNT(*) AS value
            FROM swe_cron_jobs j
            WHERE {job_where}
                AND j.status IN ('active', 'paused')
            GROUP BY j.bbk_id
            ORDER BY value DESC, name ASC
            """,
            tuple(job_params),
        )
        return self._build_distribution(
            [
                (
                    self._format_branch_name(row.get("name") or "unknown"),
                    int(row.get("value") or 0),
                )
                for row in rows
            ],
            {"unknown": "#94a3b8"},
        )

    async def _fetch_branch_execution_distribution(
        self,
        db: Any,
        exec_where: str,
        exec_params: List,
    ) -> List[CronOverviewBranchExecutionItem]:
        rows = await db.fetch_all(
            f"""
            SELECT
                COALESCE(NULLIF(j.bbk_id, ''), 'unknown') AS name,
                SUM(CASE WHEN e.status = 'success' THEN 1 ELSE 0 END)
                    AS success,
                SUM(
                    CASE
                        WHEN e.status = 'error'
                        THEN 1 ELSE 0
                    END
                ) AS failed,
                SUM(CASE WHEN e.status = 'skipped' THEN 1 ELSE 0 END)
                    AS skipped
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {exec_where}
            GROUP BY j.bbk_id
            ORDER BY (success + failed + skipped) DESC, name ASC
            """,
            tuple(exec_params),
        )
        return [
            CronOverviewBranchExecutionItem(
                name=self._format_branch_name(row.get("name") or "unknown"),
                success=int(row.get("success") or 0),
                failed=int(row.get("failed") or 0),
                skipped=int(row.get("skipped") or 0),
            )
            for row in rows
        ]

    async def _fetch_branch_read_distribution(
        self,
        db: Any,
        exec_where: str,
        exec_params: List,
    ) -> List[CronOverviewBranchReadItem]:
        rows = await db.fetch_all(
            f"""
            SELECT
                COALESCE(NULLIF(j.bbk_id, ''), 'unknown') AS name,
                SUM(CASE WHEN e.is_read = 1 THEN 1 ELSE 0 END) AS read_count,
                SUM(CASE WHEN e.is_read = 0 THEN 1 ELSE 0 END) AS unread_count
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {exec_where} AND e.status = 'success'
            GROUP BY j.bbk_id
            ORDER BY (read_count + unread_count) DESC, name ASC
            """,
            tuple(exec_params),
        )
        return [
            CronOverviewBranchReadItem(
                name=self._format_branch_name(row.get("name") or "unknown"),
                read=int(row.get("read_count") or 0),
                unread=int(row.get("unread_count") or 0),
            )
            for row in rows
        ]

    def _format_branch_name(self, bbk_id: Any) -> str:
        normalized_bbk_id = str(bbk_id or "").strip()
        if normalized_bbk_id == "unknown":
            return "unknown"
        return get_bbk_name_by_id(normalized_bbk_id) or normalized_bbk_id

    def _distribution_pairs(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[Tuple[str, int]]:
        return [
            (row.get("name") or "unknown", int(row.get("value") or 0))
            for row in rows
        ]

    async def get_subscription_overview(
        self,
        *,
        keyword: Optional[str] = None,
        tenant_id: Optional[str] = None,
        bbk_id: Optional[str] = None,
        source_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> PaginatedResponse[SubscriptionOverviewItem]:
        """按订阅任务分组统计当天概览数据。"""
        db = get_db_connection()
        start_time, end_time = self._resolve_today_range(start_time, end_time)
        conditions, sql_params = self._build_subscription_conditions(
            keyword=keyword,
            tenant_id=tenant_id,
            bbk_id=bbk_id,
            source_id=source_id,
        )
        where_clause = " AND ".join(conditions)
        group_key = (
            "COALESCE(NULLIF(j.subscription_key, ''), CONCAT('job:', j.id))"
        )

        count_sql = f"""
            SELECT COUNT(*) as count
            FROM (
                SELECT {group_key} AS subscription_group
                FROM swe_cron_jobs j
                WHERE {where_clause}
                GROUP BY subscription_group
            ) grouped
        """
        count_result = await db.fetch_one(count_sql, tuple(sql_params))
        total = count_result.get("count", 0) if count_result else 0

        offset = (page - 1) * page_size
        latest_execution_sql = """
            SELECT e.*
            FROM swe_cron_executions e
            INNER JOIN (
                SELECT job_id, MAX(actual_time) AS latest_actual_time
                FROM swe_cron_executions
                WHERE actual_time >= %s AND actual_time <= %s
                GROUP BY job_id
            ) latest
                ON latest.job_id = e.job_id
                AND latest.latest_actual_time = e.actual_time
        """
        query_sql = f"""
            SELECT
                {group_key} AS subscription_key,
                MAX(j.name) AS task_name,
                COUNT(*) AS total_task_count,
                COUNT(DISTINCT NULLIF(j.creator_user_id, '')) AS subscriber_count,
                SUM(CASE WHEN le.status = 'running' THEN 1 ELSE 0 END)
                    AS running_task_count,
                SUM(
                    CASE
                        WHEN le.job_id IS NULL
                            AND j.enabled = 1
                            AND j.status = 'active'
                        THEN 1 ELSE 0
                    END
                ) AS pending_task_count,
                SUM(CASE WHEN le.status = 'success' THEN 1 ELSE 0 END)
                    AS executed_task_count,
                SUM(
                    CASE
                        WHEN le.status IN ('error', 'timeout', 'cancelled')
                        THEN 1 ELSE 0
                    END
                ) AS failed_task_count,
                COALESCE(
                    AVG(CASE WHEN le.status = 'success' THEN le.duration_ms END),
                    0
                ) AS avg_duration_ms,
                SUM(CASE WHEN le.status = 'success' THEN 1 ELSE 0 END)
                    AS success_count,
                SUM(
                    CASE
                        WHEN le.status IN ('success', 'error', 'timeout', 'cancelled')
                        THEN 1 ELSE 0
                    END
                ) AS completed_count
            FROM swe_cron_jobs j
            LEFT JOIN ({latest_execution_sql}) le ON le.job_id = j.id
            WHERE {where_clause}
            GROUP BY subscription_key
            ORDER BY total_task_count DESC, task_name ASC
            LIMIT %s OFFSET %s
        """
        rows = await db.fetch_all(
            query_sql,
            (start_time, end_time, *sql_params, page_size, offset),
        )

        items = []
        for row in rows:
            completed_count = int(row.get("completed_count") or 0)
            success_count = int(row.get("success_count") or 0)
            success_rate = (
                success_count / completed_count if completed_count else 0.0
            )
            items.append(
                SubscriptionOverviewItem(
                    subscription_key=row.get("subscription_key") or "",
                    task_name=row.get("task_name") or "",
                    subscriber_count=int(row.get("subscriber_count") or 0),
                    total_task_count=int(row.get("total_task_count") or 0),
                    running_task_count=int(row.get("running_task_count") or 0),
                    pending_task_count=int(row.get("pending_task_count") or 0),
                    executed_task_count=int(
                        row.get("executed_task_count") or 0,
                    ),
                    failed_task_count=int(row.get("failed_task_count") or 0),
                    avg_duration_ms=float(row.get("avg_duration_ms") or 0),
                    success_rate=success_rate,
                ),
            )

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_subscription_details(
        self,
        subscription_key: str,
        *,
        tenant_id: Optional[str] = None,
        bbk_id: Optional[str] = None,
        source_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> PaginatedResponse[SubscriptionDetailItem]:
        """查询订阅任务详情弹窗数据。"""
        db = get_db_connection()
        start_time, end_time = self._resolve_today_range(start_time, end_time)
        conditions, sql_params = self._build_subscription_conditions(
            tenant_id=tenant_id,
            bbk_id=bbk_id,
            source_id=source_id,
        )
        conditions.append("j.subscription_key = %s")
        sql_params.append(subscription_key)
        where_clause = " AND ".join(conditions)

        count_sql = f"""
            SELECT COUNT(*) as count
            FROM swe_cron_jobs j
            WHERE {where_clause}
        """
        count_result = await db.fetch_one(count_sql, tuple(sql_params))
        total = count_result.get("count", 0) if count_result else 0

        offset = (page - 1) * page_size
        latest_execution_sql = """
            SELECT e.*
            FROM swe_cron_executions e
            INNER JOIN (
                SELECT job_id, MAX(actual_time) AS latest_actual_time
                FROM swe_cron_executions
                WHERE actual_time >= %s AND actual_time <= %s
                GROUP BY job_id
            ) latest
                ON latest.job_id = e.job_id
                AND latest.latest_actual_time = e.actual_time
        """
        query_sql = f"""
            SELECT
                j.id AS job_id,
                j.creator_user_id AS subscriber_id,
                j.tenant_name AS subscriber_name,
                j.bbk_id,
                j.enabled,
                CASE WHEN le.job_id IS NULL THEN 'pending' ELSE 'executed' END
                    AS execution_status,
                le.actual_time AS execution_time
            FROM swe_cron_jobs j
            LEFT JOIN ({latest_execution_sql}) le ON le.job_id = j.id
            WHERE {where_clause}
            ORDER BY j.created_at DESC
            LIMIT %s OFFSET %s
        """
        rows = await db.fetch_all(
            query_sql,
            (start_time, end_time, *sql_params, page_size, offset),
        )
        items = [
            SubscriptionDetailItem(
                job_id=row.get("job_id") or "",
                subscriber_id=row.get("subscriber_id") or "",
                subscriber_name=row.get("subscriber_name") or "",
                bbk_id=row.get("bbk_id") or "",
                enabled=bool(row.get("enabled")),
                execution_status=row.get("execution_status") or "pending",
                execution_time=row.get("execution_time"),
            )
            for row in rows
        ]

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def _resolve_today_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> Tuple[datetime, datetime]:
        """未传时间范围时默认使用北京时间当天。"""
        if start_time and end_time:
            return start_time, end_time
        today_start = datetime.now(BEIJING_TZ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        today_end = today_start.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
        return today_start - timedelta(hours=8), today_end - timedelta(hours=8)

    def _build_distribution(
        self,
        pairs: List[Tuple[str, int]],
        color_map: Optional[Dict[str, str]] = None,
    ) -> List[CronOverviewDistributionItem]:
        """Build chart items with percentages."""
        total = sum(value for _, value in pairs)
        items = []
        for name, value in pairs:
            percent = (value / total * 100) if total else 0.0
            color = color_map.get(name) if color_map else None
            items.append(
                CronOverviewDistributionItem(
                    name=name,
                    value=value,
                    percent=round(percent, 2),
                    color=color,
                ),
            )
        return items

    def _build_overview_job_conditions(
        self,
        *,
        tenant_id: Optional[str] = None,
        bbk_id: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Tuple[List[str], List]:
        """Build filters for swe_cron_jobs overview queries."""
        conditions = ["j.deleted_at IS NULL", "j.status != 'deleted'"]
        sql_params: List = []
        if tenant_id:
            conditions.append("j.tenant_id = %s")
            sql_params.append(tenant_id)
        if bbk_id:
            conditions.append("j.bbk_id = %s")
            sql_params.append(bbk_id)
        if source_id:
            conditions.append("j.source_id = %s")
            sql_params.append(source_id)
        return conditions, sql_params

    def _build_overview_execution_conditions(
        self,
        *,
        tenant_id: Optional[str] = None,
        bbk_id: Optional[str] = None,
        source_id: Optional[str] = None,
        start_time: datetime,
        end_time: datetime,
    ) -> Tuple[List[str], List]:
        """Build filters for swe_cron_executions overview queries."""
        conditions = [
            "e.actual_time >= %s",
            "e.actual_time <= %s",
            "j.status != 'deleted'",
        ]
        sql_params: List = [start_time, end_time]
        if tenant_id:
            conditions.append("e.tenant_id = %s")
            sql_params.append(tenant_id)
        if bbk_id:
            conditions.append("j.bbk_id = %s")
            sql_params.append(bbk_id)
        if source_id:
            conditions.append("j.source_id = %s")
            sql_params.append(source_id)
        return conditions, sql_params

    def _build_subscription_conditions(
        self,
        *,
        keyword: Optional[str] = None,
        tenant_id: Optional[str] = None,
        bbk_id: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Tuple[List[str], List]:
        """构建订阅任务查询条件。"""
        conditions = ["j.deleted_at IS NULL", "j.job_origin = 'subscription'"]
        sql_params: List = []
        if keyword:
            conditions.append(
                "j.name LIKE %s",
            )
            keyword_like = f"%{keyword}%"
            sql_params.append(keyword_like)
        if tenant_id:
            conditions.append("j.tenant_id = %s")
            sql_params.append(tenant_id)
        if bbk_id:
            conditions.append("j.bbk_id = %s")
            sql_params.append(bbk_id)
        if source_id:
            conditions.append("j.source_id = %s")
            sql_params.append(source_id)
        return conditions, sql_params

    async def mark_job_as_read(
        self,
        job_id: str,
        source_id: Optional[str] = None,
    ) -> int:
        """标记任务的最新一次未读执行为已读。

        只将指定任务的最后一次成功执行的未读记录标记为已读。

        Args:
            job_id: 任务ID
            source_id: Source ID filter

        Returns:
            更新的记录数量（0 或 1）
        """
        db = get_db_connection()
        now = datetime.now(BEIJING_TZ).replace(tzinfo=None)

        update_sql = """
            UPDATE swe_cron_executions e
            JOIN (
                SELECT id FROM swe_cron_executions
                WHERE job_id = %s
                AND status = 'success'
                AND is_read = FALSE
                ORDER BY actual_time DESC
                LIMIT 1
            ) AS latest ON e.id = latest.id
            SET e.is_read = TRUE, e.read_at = %s
        """
        logger.info(f"[mark_executions_read] 开始标记已读, job_id={job_id}")
        logger.debug(f"[mark_executions_read] SQL: {update_sql}")

        result = await db.execute(update_sql, (job_id, now))
        rowcount = getattr(result, "rowcount", 0) if result else 0
        logger.info(
            f"[mark_executions_read] UPDATE执行完成, job_id={job_id}, updated={rowcount}",
        )
        return rowcount

    async def get_unread_count(
        self,
        tenant_id: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> UnreadCountResponse:
        """获取未读任务数量统计。

        按任务分组统计未读的成功执行记录数量，
        用于前端展示未读提醒。

        Args:
            tenant_id: 租户ID筛选（可选）
            source_id: Source ID filter

        Returns:
            包含各任务未读数量的字典
        """
        db = get_db_connection()

        conditions = ["e.status = 'success'", "e.is_read = FALSE"]
        sql_params: List = []

        if tenant_id:
            conditions.append("e.tenant_id = %s")
            sql_params.append(tenant_id)

        if source_id:
            conditions.append("j.source_id = %s")
            sql_params.append(source_id)

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT e.job_id, e.job_name, COUNT(*) as unread_count
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE {where_clause}
            GROUP BY e.job_id, e.job_name
            ORDER BY unread_count DESC
        """
        rows = await db.fetch_all(
            sql,
            tuple(sql_params) if sql_params else None,
        )

        return UnreadCountResponse(
            items=[
                {
                    "job_id": row["job_id"],
                    "job_name": row["job_name"] or row["job_id"],
                    "unread_count": row["unread_count"],
                }
                for row in rows
            ],
            total_unread=sum(row["unread_count"] for row in rows),
        )

    @staticmethod
    def _row_int(row: Optional[Dict[str, Any]], key: str) -> int:
        """Read an integer aggregate from a DB row."""
        if not row:
            return 0
        return int(row.get(key) or 0)

    @staticmethod
    def _percent(numerator: int, denominator: int) -> float:
        """Calculate a rounded percentage with zero protection."""
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator * 100, 2)

    async def _fetch_overview_task_count(
        self,
        db: Any,
        bbk_filter_sql: str,
        bbk_filter_params: List[Any],
        source_filter_sql: str,
        source_filter_params: List[Any],
    ) -> int:
        task_count_sql = f"""
            SELECT COUNT(*) AS count
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
              AND status != 'deleted'
              {bbk_filter_sql.replace('j.bbk_id', 'bbk_id')}
              {source_filter_sql.replace('j.source_id', 'source_id')}
        """
        params = bbk_filter_params + source_filter_params
        row = await db.fetch_one(
            task_count_sql,
            tuple(params) if params else None,
        )
        return self._row_int(row, "count")

    async def _fetch_overview_branch_tenant_counts(
        self,
        db: Any,
        bbk_filter_sql: str,
        bbk_filter_params: List[Any],
        source_filter_sql: str,
        source_filter_params: List[Any],
    ) -> Tuple[int, int]:
        branch_tenant_sql = f"""
            SELECT
                COUNT(DISTINCT bbk_id) AS branch_count,
                COUNT(DISTINCT tenant_id) AS tenant_count
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
              AND status != 'deleted'
              {bbk_filter_sql.replace('j.bbk_id', 'bbk_id')}
              {source_filter_sql.replace('j.source_id', 'source_id')}
        """
        params = bbk_filter_params + source_filter_params
        row = await db.fetch_one(
            branch_tenant_sql,
            tuple(params) if params else None,
        )
        return self._row_int(row, "branch_count"), self._row_int(
            row,
            "tenant_count",
        )

    async def _fetch_overview_execution_counts(
        self,
        db: Any,
        start_time: datetime,
        end_time: datetime,
        bbk_filter_sql: str,
        bbk_filter_params: List[Any],
        source_filter_sql: str,
        source_filter_params: List[Any],
    ) -> Dict[str, int]:
        # 综合状态判断：
        # 成功：status='success' AND async_status='success'
        # 运行中：status='success' AND (async_status IS NULL OR async_status='')
        # 失败：status='error' OR (status='success' AND async_status='error')
        exec_sql = f"""
            SELECT
                COUNT(*) AS total_executions,
                COUNT(DISTINCT e.job_id) AS executed_job_count,
                SUM(
                    CASE WHEN e.status = 'success' AND e.async_status = 'success'
                    THEN 1 ELSE 0 END
                ) AS success_count,
                SUM(
                    CASE WHEN e.status = 'success'
                         AND (e.async_status IS NULL OR e.async_status = '')
                    THEN 1 ELSE 0 END
                ) AS running_count,
                SUM(
                    CASE WHEN e.status = 'error'
                         OR (e.status = 'success' AND e.async_status = 'error')
                    THEN 1 ELSE 0 END
                ) AS error_count
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE e.actual_time >= %s AND e.actual_time <= %s
              AND j.deleted_at IS NULL
              AND j.status != 'deleted'
              {bbk_filter_sql}
              {source_filter_sql}
        """
        params = (
            [start_time, end_time] + bbk_filter_params + source_filter_params
        )
        row = await db.fetch_one(exec_sql, tuple(params))
        return {
            "total_executions": self._row_int(row, "total_executions"),
            "executed_job_count": self._row_int(row, "executed_job_count"),
            "success_count": self._row_int(row, "success_count"),
            "running_count": self._row_int(row, "running_count"),
            "error_count": self._row_int(row, "error_count"),
        }

    async def _fetch_overview_read_tasks(
        self,
        db: Any,
        start_time: datetime,
        end_time: datetime,
        bbk_filter_sql: str,
        bbk_filter_params: List[Any],
        source_filter_sql: str,
        source_filter_params: List[Any],
    ) -> int:
        read_tasks_sql = f"""
            SELECT COUNT(DISTINCT e.job_id) AS read_tasks
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE e.actual_time >= %s AND e.actual_time <= %s
              AND e.is_read = 1
              AND j.deleted_at IS NULL
              AND j.status != 'deleted'
              {bbk_filter_sql}
              {source_filter_sql}
        """
        params = (
            [start_time, end_time] + bbk_filter_params + source_filter_params
        )
        row = await db.fetch_one(read_tasks_sql, tuple(params))
        return self._row_int(row, "read_tasks")

    async def get_overview_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        bbk_ids: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> CronOverviewStatsResponse:
        """获取定时任务概览统计。

        Args:
            start_date: 开始日期 (YYYY-MM-DD格式字符串)
            end_date: 结束日期 (YYYY-MM-DD格式字符串)
            bbk_ids: 分行号筛选（逗号分隔）
            source_id: 来源标识

        Returns:
            概览统计数据
        """
        db = get_db_connection()

        # 解析时间范围
        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        # 构建 bbk 过滤条件
        bbk_filter_sql, bbk_filter_params = self._build_bbk_filter(bbk_ids)

        # 构建 source 过滤条件
        source_filter_sql, source_filter_params = self._build_source_filter(
            source_id,
        )

        total_tasks = await self._fetch_overview_task_count(
            db,
            bbk_filter_sql,
            bbk_filter_params,
            source_filter_sql,
            source_filter_params,
        )
        branch_count, tenant_count = (
            await self._fetch_overview_branch_tenant_counts(
                db,
                bbk_filter_sql,
                bbk_filter_params,
                source_filter_sql,
                source_filter_params,
            )
        )
        execution_counts = await self._fetch_overview_execution_counts(
            db,
            start_time,
            end_time,
            bbk_filter_sql,
            bbk_filter_params,
            source_filter_sql,
            source_filter_params,
        )
        read_tasks = await self._fetch_overview_read_tasks(
            db,
            start_time,
            end_time,
            bbk_filter_sql,
            bbk_filter_params,
            source_filter_sql,
            source_filter_params,
        )

        total_executions = execution_counts["total_executions"]
        executed_job_count = execution_counts["executed_job_count"]
        success_count = execution_counts["success_count"]
        running_count = execution_counts["running_count"]
        error_count = execution_counts["error_count"]
        success_rate = self._percent(success_count, total_executions)
        read_rate = self._percent(read_tasks, executed_job_count)
        error_rate = self._percent(error_count, total_executions)

        return CronOverviewStatsResponse(
            start_date=start_str,
            end_date=end_str,
            total_tasks=total_tasks,
            total_executions=total_executions,
            branch_count=branch_count,
            tenant_count=tenant_count,
            success_rate=success_rate,
            success_count=success_count,
            running_count=running_count,
            read_tasks=read_tasks,
            read_rate=read_rate,
            error_count=error_count,
            error_rate=error_rate,
        )

    async def _fetch_branch_behavior_ids(
        self,
        db: Any,
        start_time: datetime,
        end_time: datetime,
        bbk_filter_sql: str,
        bbk_filter_params: List[Any],
        source_filter_sql: str,
        source_filter_params: List[Any],
    ) -> List[str]:
        """获取分行ID列表（任务视角，不使用白名单过滤）。"""
        branch_list_sql = f"""
            SELECT DISTINCT j.bbk_id
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE e.actual_time >= %s AND e.actual_time <= %s
              AND j.deleted_at IS NULL
              AND j.status != 'deleted'
              AND j.bbk_id IS NOT NULL
              AND j.bbk_id != ''
              {bbk_filter_sql}
              {source_filter_sql}
        """
        params = (
            [start_time, end_time] + bbk_filter_params + source_filter_params
        )
        rows = await db.fetch_all(branch_list_sql, tuple(params))
        return [row.get("bbk_id") for row in rows if row.get("bbk_id")]

    async def _fetch_branch_skill_behavior_ids(
        self,
        db: Any,
        start_time: datetime,
        end_time: datetime,
        bbk_filter_sql: str,
        bbk_filter_params: List[Any],
        source_filter_sql: str,
        source_filter_params: List[Any],
    ) -> List[str]:
        """获取使用白名单技能的分行ID列表（技能视角）。

        关联 traces 表，筛选 skills_used 包含白名单技能的执行记录。
        """
        # 构建白名单技能过滤条件
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        allowed_placeholders = ", ".join(["%s"] * len(allowed_skills))

        branch_list_sql = f"""
            SELECT DISTINCT j.bbk_id
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id = j.id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE e.actual_time >= %s AND e.actual_time <= %s
              AND j.deleted_at IS NULL
              AND j.status != 'deleted'
              AND j.bbk_id IS NOT NULL
              AND j.bbk_id != ''
              AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) IN ({allowed_placeholders})
              {bbk_filter_sql}
              {source_filter_sql}
        """
        params = (
            [start_time, end_time]
            + allowed_skills
            + bbk_filter_params
            + source_filter_params
        )
        rows = await db.fetch_all(branch_list_sql, tuple(params))
        return [row.get("bbk_id") for row in rows if row.get("bbk_id")]

    async def _fetch_branch_total_tasks(
        self,
        db: Any,
        bbk_id: str,
        source_id: Optional[str],
    ) -> int:
        """统计分行任务数量（任务视角，不使用白名单过滤）。"""
        source_where = " AND source_id = %s" if source_id else ""
        task_count_sql = f"""
            SELECT COUNT(*) AS count
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
              AND status != 'deleted'
              AND bbk_id = %s
              {source_where}
        """
        params = (bbk_id, source_id) if source_id else (bbk_id,)
        row = await db.fetch_one(task_count_sql, params)
        return self._row_int(row, "count")

    async def _fetch_branch_skill_total_tasks(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> int:
        """统计分行使用白名单技能的任务数量（技能视角）。

        通过执行记录关联 traces 表，筛选 skills_used 包含白名单技能的任务。
        """
        source_where = " AND j.source_id = %s" if source_id else ""
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        allowed_placeholders = ", ".join(["%s"] * len(allowed_skills))

        task_count_sql = f"""
            SELECT COUNT(DISTINCT j.id) AS count
            FROM swe_cron_jobs j
            JOIN swe_cron_executions e ON e.job_id = j.id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE j.deleted_at IS NULL
              AND j.status != 'deleted'
              AND j.bbk_id = %s
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) IN ({allowed_placeholders})
              {source_where}
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        row = await db.fetch_one(task_count_sql, tuple(params))
        return self._row_int(row, "count")

    async def _fetch_branch_job_ids(
        self,
        db: Any,
        bbk_id: str,
        source_id: Optional[str],
    ) -> list[str]:
        """获取指定分行的所有 job_id（任务视角，不使用白名单过滤）。"""
        source_where = " AND source_id = %s" if source_id else ""
        job_ids_sql = f"""
            SELECT id
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
              AND status != 'deleted'
              AND bbk_id = %s
              {source_where}
        """
        params = (bbk_id, source_id) if source_id else (bbk_id,)
        rows = await db.fetch_all(job_ids_sql, params)
        return [row["id"] for row in rows]

    async def _fetch_branch_skill_job_ids(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> list[str]:
        """获取指定分行使用白名单技能的所有 job_id（技能视角）。

        通过执行记录关联 traces 表，筛选 skills_used 包含白名单技能的任务。
        """
        source_where = " AND j.source_id = %s" if source_id else ""
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        allowed_placeholders = ", ".join(["%s"] * len(allowed_skills))

        job_ids_sql = f"""
            SELECT DISTINCT j.id
            FROM swe_cron_jobs j
            JOIN swe_cron_executions e ON e.job_id = j.id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE j.deleted_at IS NULL
              AND j.status != 'deleted'
              AND j.bbk_id = %s
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) IN ({allowed_placeholders})
              {source_where}
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(job_ids_sql, tuple(params))
        return [row["id"] for row in rows]

    async def _fetch_branch_execution_stats(
        self,
        db: Any,
        start_time: datetime,
        end_time: datetime,
        job_ids: list[str],
    ) -> dict:
        """直接从 swe_cron_executions 统计执行指标，不 JOIN swe_cron_jobs。"""
        if not job_ids:
            return {
                "total_executions": 0,
                "success_count": 0,
                "read_tasks": 0,
                "error_count": 0,
            }
        placeholders = ", ".join(["%s"] * len(job_ids))
        stats_sql = f"""
            SELECT
                COUNT(*) AS total_executions,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN is_read = 1 THEN 1 ELSE 0 END) AS read_tasks,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count
            FROM swe_cron_executions
            WHERE actual_time >= %s AND actual_time <= %s
              AND job_id IN ({placeholders})
        """
        params = [start_time, end_time] + job_ids
        row = await db.fetch_one(stats_sql, tuple(params))
        return {
            "total_executions": self._row_int(row, "total_executions"),
            "success_count": self._row_int(row, "success_count"),
            "read_tasks": self._row_int(row, "read_tasks"),
            "error_count": self._row_int(row, "error_count"),
        }

    async def _fetch_branch_manager_count(
        self,
        db: Any,
        bbk_id: str,
        source_id: Optional[str],
    ) -> int:
        source_where = " AND source_id = %s" if source_id else ""
        manager_sql = f"""
            SELECT COUNT(DISTINCT tenant_id) AS manager_count
            FROM swe_cron_jobs
            WHERE deleted_at IS NULL
              AND status != 'deleted'
              AND bbk_id = %s
              {source_where}
        """
        params = (bbk_id, source_id) if source_id else (bbk_id,)
        row = await db.fetch_one(manager_sql, params)
        return self._row_int(row, "manager_count")

    async def _fetch_branch_click_counts(
        self,
        db: Any,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> dict:
        """查询各分行点击统计（查看方案/去洞察/去电访）。

        从 swe_html_preview_click_events 按 bbk_id + button_type 聚合，
        同时返回去重任务数 (COUNT(DISTINCT cron_task_id)) 和点击数 (COUNT(*))。
        """
        source_where = " AND source_id = %s" if source_id else ""
        click_sql = f"""
            SELECT
                bbk_id,
                button_type,
                COUNT(DISTINCT cron_task_id) AS task_count,
                COUNT(*) AS total_clicks
            FROM swe_html_preview_click_events
            WHERE clicked_at >= %s AND clicked_at <= %s
              AND cron_task_id IS NOT NULL
              AND bbk_id IS NOT NULL
              AND bbk_id != ''
              {source_where}
            GROUP BY bbk_id, button_type
        """
        params: list = [start_time, end_time]
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(click_sql, tuple(params))

        result: dict[str, dict[str, dict[str, int]]] = {}
        for row in rows:
            bbk = row["bbk_id"]
            btn = row["button_type"] or "other"
            if bbk not in result:
                result[bbk] = {}
            result[bbk][btn] = {
                "task_count": row["task_count"] or 0,
                "total_clicks": row["total_clicks"] or 0,
            }
        return result

    async def _fetch_branch_skill_count(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> int:
        """统计分行白名单内技能去重数量。

        从 swe_tracing_traces.skills_used 字段展开JSON数组，
        过滤白名单内的技能后去重计数。
        """
        source_where = " AND j.source_id = %s" if source_id else ""
        # 构建白名单SQL条件
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        allowed_placeholders = ", ".join(["%s"] * len(allowed_skills))

        sql = f"""
            SELECT COUNT(DISTINCT skill_name) AS skill_count
            FROM (
                SELECT JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) AS skill_name
                FROM swe_cron_executions e
                JOIN swe_cron_jobs j ON e.job_id = j.id
                JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
                CROSS JOIN (
                    SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                    UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                    UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
                ) idx
                WHERE j.bbk_id = %s
                  AND e.actual_time >= %s AND e.actual_time <= %s
                  AND t.skills_used IS NOT NULL
                  AND t.session_id LIKE 'cron-task%%'
                  AND JSON_LENGTH(t.skills_used) > idx.i
                  {source_where}
            ) expanded
            WHERE skill_name IN ({allowed_placeholders})
        """
        params: list = [bbk_id, start_time, end_time]
        if source_id:
            params.append(source_id)
        params.extend(allowed_skills)
        row = await db.fetch_one(sql, tuple(params))
        return self._row_int(row, "skill_count")

    async def _fetch_branch_manager_click_counts(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> dict[str, int]:
        """统计分行客户经理点击行为（任务视角，不使用白名单过滤）。

        按button_type去重user_id。
        """
        source_where = " AND source_id = %s" if source_id else ""
        sql = f"""
            SELECT button_type, COUNT(DISTINCT user_id) AS manager_count
            FROM swe_html_preview_click_events
            WHERE bbk_id = %s
              AND clicked_at >= %s AND clicked_at <= %s
              AND button_type IN ('plan', 'insight', 'phone')
              {source_where}
            GROUP BY button_type
        """
        params: list = [bbk_id, start_time, end_time]
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(sql, tuple(params))
        result: dict[str, int] = {}
        for row in rows:
            btn = row["button_type"] or "other"
            result[btn] = self._row_int(row, "manager_count")
        return result

    async def _fetch_branch_skill_manager_click_counts(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> dict[str, int]:
        """统计分行使用白名单技能的客户经理点击行为（技能视角）。

        通过点击事件关联执行记录和 traces 表，筛选 skills_used 包含白名单技能的点击。
        """
        source_where = " AND c.source_id = %s" if source_id else ""
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        allowed_placeholders = ", ".join(["%s"] * len(allowed_skills))

        sql = f"""
            SELECT c.button_type, COUNT(DISTINCT c.user_id) AS manager_count
            FROM swe_html_preview_click_events c
            JOIN swe_cron_executions e ON c.cron_task_id = e.job_id
                AND c.clicked_at >= e.actual_time
                AND c.clicked_at <= COALESCE(e.end_time, e.actual_time + INTERVAL 1 DAY)
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE c.bbk_id = %s
              AND c.clicked_at >= %s AND c.clicked_at <= %s
              AND c.button_type IN ('plan', 'insight', 'phone')
              AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) IN ({allowed_placeholders})
              {source_where}
            GROUP BY c.button_type
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(sql, tuple(params))
        result: dict[str, int] = {}
        for row in rows:
            btn = row["button_type"] or "other"
            result[btn] = self._row_int(row, "manager_count")
        return result

    async def _fetch_branch_customer_click_counts(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> dict[str, int]:
        """统计分行客户点击行为（任务视角，不使用白名单过滤）。

        按button_type去重customer_id。
        """
        source_where = " AND source_id = %s" if source_id else ""
        sql = f"""
            SELECT button_type, COUNT(DISTINCT customer_id) AS customer_count
            FROM swe_html_preview_click_events
            WHERE bbk_id = %s
              AND clicked_at >= %s AND clicked_at <= %s
              AND button_type IN ('plan', 'insight', 'phone')
              AND customer_id IS NOT NULL
              {source_where}
            GROUP BY button_type
        """
        params: list = [bbk_id, start_time, end_time]
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(sql, tuple(params))
        result: dict[str, int] = {}
        for row in rows:
            btn = row["button_type"] or "other"
            result[btn] = self._row_int(row, "customer_count")
        return result

    async def _fetch_branch_skill_customer_click_counts(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> dict[str, int]:
        """统计分行使用白名单技能的客户点击行为（技能视角）。

        通过点击事件关联执行记录和 traces 表，筛选 skills_used 包含白名单技能的点击。
        """
        source_where = " AND c.source_id = %s" if source_id else ""
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        allowed_placeholders = ", ".join(["%s"] * len(allowed_skills))

        sql = f"""
            SELECT c.button_type, COUNT(DISTINCT c.customer_id) AS customer_count
            FROM swe_html_preview_click_events c
            JOIN swe_cron_executions e ON c.cron_task_id = e.job_id
                AND c.clicked_at >= e.actual_time
                AND c.clicked_at <= COALESCE(e.end_time, e.actual_time + INTERVAL 1 DAY)
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE c.bbk_id = %s
              AND c.clicked_at >= %s AND c.clicked_at <= %s
              AND c.button_type IN ('plan', 'insight', 'phone')
              AND c.customer_id IS NOT NULL
              AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) IN ({allowed_placeholders})
              {source_where}
            GROUP BY c.button_type
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(sql, tuple(params))
        result: dict[str, int] = {}
        for row in rows:
            btn = row["button_type"] or "other"
            result[btn] = self._row_int(row, "customer_count")
        return result

    async def _fetch_branch_recommended_customers(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> int:
        """统计分行推荐的客户数（任务视角，不使用白名单过滤）。

        从subtasks表custuid去重。
        """
        source_where = " AND j.source_id = %s" if source_id else ""
        sql = f"""
            SELECT COUNT(DISTINCT s.custuid) AS customer_count
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id = j.id
            JOIN swe_cron_subtasks s ON e.trace_id = s.trace_id
            WHERE j.bbk_id = %s
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND s.custuid IS NOT NULL
              {source_where}
        """
        params: list = [bbk_id, start_time, end_time]
        if source_id:
            params.append(source_id)
        row = await db.fetch_one(sql, tuple(params))
        return self._row_int(row, "customer_count")

    async def _fetch_branch_skill_recommended_customers(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> int:
        """统计分行使用白名单技能的推荐客户数（技能视角）。

        通过执行记录关联 traces 表，筛选 skills_used 包含白名单技能的推荐客户。
        """
        source_where = " AND j.source_id = %s" if source_id else ""
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        allowed_placeholders = ", ".join(["%s"] * len(allowed_skills))

        sql = f"""
            SELECT COUNT(DISTINCT s.custuid) AS customer_count
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id = j.id
            JOIN swe_cron_subtasks s ON e.trace_id = s.trace_id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE j.bbk_id = %s
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND s.custuid IS NOT NULL
              AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) IN ({allowed_placeholders})
              {source_where}
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        row = await db.fetch_one(sql, tuple(params))
        return self._row_int(row, "customer_count")

    async def _fetch_branch_involved_managers(
        self,
        db: Any,
        bbk_id: str,
        source_id: Optional[str],
    ) -> int:
        """统计分行涉及客户经理数（任务视角，不使用白名单过滤）。

        生效中任务的tenant_id去重。
        """
        source_where = " AND source_id = %s" if source_id else ""
        sql = f"""
            SELECT COUNT(DISTINCT tenant_id) AS manager_count
            FROM swe_cron_jobs
            WHERE bbk_id = %s
              AND status = 'active'
              AND enabled = 1
              AND deleted_at IS NULL
              {source_where}
        """
        params = (bbk_id, source_id) if source_id else (bbk_id,)
        row = await db.fetch_one(sql, params)
        return self._row_int(row, "manager_count")

    async def _fetch_branch_skill_involved_managers(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> int:
        """统计分行使用白名单技能的涉及客户经理数（技能视角）。

        通过执行记录关联 traces 表，筛选 skills_used 包含白名单技能的 tenant_id。
        统计时间范围内执行过白名单技能任务的客户经理数。
        """
        source_where = " AND j.source_id = %s" if source_id else ""
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        allowed_placeholders = ", ".join(["%s"] * len(allowed_skills))

        sql = f"""
            SELECT COUNT(DISTINCT j.tenant_id) AS manager_count
            FROM swe_cron_jobs j
            JOIN swe_cron_executions e ON e.job_id = j.id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE j.bbk_id = %s
              AND j.deleted_at IS NULL
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) IN ({allowed_placeholders})
              {source_where}
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        row = await db.fetch_one(sql, tuple(params))
        return self._row_int(row, "manager_count")

    async def _fetch_branch_result_view_managers(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> int:
        """统计分行查看结果的客户经理数（任务视角，不使用白名单过滤）。

        is_read=1的tenant_id去重。
        """
        source_where = " AND j.source_id = %s" if source_id else ""
        sql = f"""
            SELECT COUNT(DISTINCT j.tenant_id) AS manager_count
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE j.bbk_id = %s
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND e.is_read = 1
              {source_where}
        """
        params: list = [bbk_id, start_time, end_time]
        if source_id:
            params.append(source_id)
        row = await db.fetch_one(sql, tuple(params))
        return self._row_int(row, "manager_count")

    async def _fetch_branch_skill_result_view_managers(
        self,
        db: Any,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> int:
        """统计分行使用白名单技能的查看结果客户经理数（技能视角）。

        通过执行记录关联 traces 表，筛选 skills_used 包含白名单技能且 is_read=1 的 tenant_id。
        """
        source_where = " AND j.source_id = %s" if source_id else ""
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        allowed_placeholders = ", ".join(["%s"] * len(allowed_skills))

        sql = f"""
            SELECT COUNT(DISTINCT j.tenant_id) AS manager_count
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id = j.id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE j.bbk_id = %s
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND e.is_read = 1
              AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) IN ({allowed_placeholders})
              {source_where}
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        row = await db.fetch_one(sql, tuple(params))
        return self._row_int(row, "manager_count")

    def _build_branch_task_ranking_item(
        self,
        bbk_id: str,
        manager_count: int,
        total_tasks: int,
        success_count: int,
        total_executions: int,
        read_tasks: int,
        plan_count: int = 0,
        insight_count: int = 0,
        phone_count: int = 0,
        plan_clicks: int = 0,
        insight_clicks: int = 0,
        phone_clicks: int = 0,
        error_count: int = 0,
    ) -> CronBranchTaskRankingItem:
        return CronBranchTaskRankingItem(
            bbk_id=bbk_id,
            bbk_name=get_bbk_name_by_id(bbk_id) or bbk_id,
            manager_count=manager_count,
            total_tasks=total_tasks,
            success_count=success_count,
            success_rate=self._percent(success_count, total_executions),
            read_tasks=read_tasks,
            plan_count=plan_count,
            insight_count=insight_count,
            phone_count=phone_count,
            plan_clicks=plan_clicks,
            insight_clicks=insight_clicks,
            phone_clicks=phone_clicks,
            error_count=error_count,
        )

    def _build_branch_ranking_item(
        self,
        bbk_id: str,
        skill_count: int,
        total_tasks: int,
        success_count: int,
        read_tasks: int,
        involved_managers: int,
        result_view_managers: int,
        plan_managers: int,
        insight_managers: int,
        phone_managers: int,
        recommended_customers: int,
        viewed_customers: int,
        insight_customers: int,
        phone_customers: int,
    ) -> CronBranchRankingItem:
        return CronBranchRankingItem(
            bbk_id=bbk_id,
            bbk_name=get_bbk_name_by_id(bbk_id) or bbk_id,
            skill_count=skill_count,
            total_tasks=total_tasks,
            success_count=success_count,
            read_tasks=read_tasks,
            involved_managers=involved_managers,
            result_view_managers=result_view_managers,
            plan_managers=plan_managers,
            insight_managers=insight_managers,
            phone_managers=phone_managers,
            recommended_customers=recommended_customers,
            viewed_customers=viewed_customers,
            insight_customers=insight_customers,
            phone_customers=phone_customers,
        )

    async def get_branch_behavior(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        bbk_ids: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> CronBranchRankingResponse:
        """获取分行综合排行。

        Args:
            start_date: 开始日期 (YYYY-MM-DD格式字符串)
            end_date: 结束日期 (YYYY-MM-DD格式字符串)
            bbk_ids: 分行号筛选（逗号分隔）
            source_id: 来源标识

        Returns:
            分行综合排行数据
        """
        db = get_db_connection()

        # 解析时间范围
        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        # 构建 bbk 过滤条件
        bbk_filter_sql, bbk_filter_params = self._build_bbk_filter(bbk_ids)

        # 构建 source 过滤条件
        source_filter_sql, source_filter_params = self._build_source_filter(
            source_id,
        )

        branch_ids = await self._fetch_branch_skill_behavior_ids(
            db,
            start_time,
            end_time,
            bbk_filter_sql,
            bbk_filter_params,
            source_filter_sql,
            source_filter_params,
        )

        items = []
        for bbk_id in branch_ids:
            total_tasks = await self._fetch_branch_skill_total_tasks(
                db,
                bbk_id,
                start_time,
                end_time,
                source_id,
            )
            job_ids = await self._fetch_branch_skill_job_ids(
                db,
                bbk_id,
                start_time,
                end_time,
                source_id,
            )
            stats = await self._fetch_branch_execution_stats(
                db,
                start_time,
                end_time,
                job_ids,
            )
            # 新增指标查询
            skill_count = await self._fetch_branch_skill_count(
                db,
                bbk_id,
                start_time,
                end_time,
                source_id,
            )
            involved_managers = (
                await self._fetch_branch_skill_involved_managers(
                    db,
                    bbk_id,
                    start_time,
                    end_time,
                    source_id,
                )
            )
            result_view_managers = (
                await self._fetch_branch_skill_result_view_managers(
                    db,
                    bbk_id,
                    start_time,
                    end_time,
                    source_id,
                )
            )
            manager_click_counts = (
                await self._fetch_branch_skill_manager_click_counts(
                    db,
                    bbk_id,
                    start_time,
                    end_time,
                    source_id,
                )
            )
            customer_click_counts = (
                await self._fetch_branch_skill_customer_click_counts(
                    db,
                    bbk_id,
                    start_time,
                    end_time,
                    source_id,
                )
            )
            recommended_customers = (
                await self._fetch_branch_skill_recommended_customers(
                    db,
                    bbk_id,
                    start_time,
                    end_time,
                    source_id,
                )
            )
            items.append(
                self._build_branch_ranking_item(
                    bbk_id,
                    skill_count,
                    total_tasks,
                    stats["success_count"],
                    stats["read_tasks"],
                    involved_managers,
                    result_view_managers,
                    manager_click_counts.get("plan", 0),
                    manager_click_counts.get("insight", 0),
                    manager_click_counts.get("phone", 0),
                    recommended_customers,
                    customer_click_counts.get("plan", 0),
                    customer_click_counts.get("insight", 0),
                    customer_click_counts.get("phone", 0),
                ),
            )

        items.sort(key=lambda item: item.success_count, reverse=True)

        return CronBranchRankingResponse(
            start_date=start_str,
            end_date=end_str,
            items=items,
        )

    async def get_branch_task_behavior(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        bbk_ids: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> CronBranchTaskRankingResponse:
        """获取分行任务视角综合排行。

        Args:
            start_date: 开始日期 (YYYY-MM-DD格式字符串)
            end_date: 结束日期 (YYYY-MM-DD格式字符串)
            bbk_ids: 分行号筛选（逗号分隔）
            source_id: 来源标识

        Returns:
            分行任务视角排行数据
        """
        db = get_db_connection()

        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        bbk_filter_sql, bbk_filter_params = self._build_bbk_filter(bbk_ids)
        source_filter_sql, source_filter_params = self._build_source_filter(
            source_id,
        )

        branch_ids = await self._fetch_branch_behavior_ids(
            db,
            start_time,
            end_time,
            bbk_filter_sql,
            bbk_filter_params,
            source_filter_sql,
            source_filter_params,
        )

        # 一次查询获取所有分行的点击统计
        click_counts = await self._fetch_branch_click_counts(
            db,
            start_time,
            end_time,
            source_id,
        )

        items = []
        for bbk_id in branch_ids:
            total_tasks = await self._fetch_branch_total_tasks(
                db,
                bbk_id,
                source_id,
            )
            manager_count = await self._fetch_branch_manager_count(
                db,
                bbk_id,
                source_id,
            )
            job_ids = await self._fetch_branch_job_ids(
                db,
                bbk_id,
                source_id,
            )
            stats = await self._fetch_branch_execution_stats(
                db,
                start_time,
                end_time,
                job_ids,
            )
            branch_clicks = click_counts.get(bbk_id, {})
            plan_clicks_data = branch_clicks.get("plan", {})
            insight_clicks_data = branch_clicks.get("insight", {})
            phone_clicks_data = branch_clicks.get("phone", {})
            items.append(
                self._build_branch_task_ranking_item(
                    bbk_id,
                    manager_count,
                    total_tasks,
                    stats["success_count"],
                    stats["total_executions"],
                    stats["read_tasks"],
                    plan_count=plan_clicks_data.get("task_count", 0),
                    insight_count=insight_clicks_data.get("task_count", 0),
                    phone_count=phone_clicks_data.get("task_count", 0),
                    plan_clicks=plan_clicks_data.get("total_clicks", 0),
                    insight_clicks=insight_clicks_data.get("total_clicks", 0),
                    phone_clicks=phone_clicks_data.get("total_clicks", 0),
                    error_count=stats["error_count"],
                ),
            )

        items.sort(key=lambda item: item.success_count, reverse=True)

        return CronBranchTaskRankingResponse(
            start_date=start_str,
            end_date=end_str,
            items=items,
        )

    async def get_branch_error(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        bbk_ids: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> CronBranchErrorResponse:
        """获取分行层异常执行数据。

        Args:
            start_date: 开始日期 (YYYY-MM-DD格式字符串)
            end_date: 结束日期 (YYYY-MM-DD格式字符串)
            bbk_ids: 分行号筛选（逗号分隔）
            source_id: 来源标识

        Returns:
            分行异常执行数据
        """
        db = get_db_connection()

        # 解析时间范围
        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        # 构建 bbk 过滤条件
        bbk_filter_sql, bbk_filter_params = self._build_bbk_filter(bbk_ids)

        # 构建 source 过滤条件
        source_filter_sql, source_filter_params = self._build_source_filter(
            source_id,
        )

        # 1. 受影响的分行数量和客户经理数量（综合判断失败状态）
        # 失败：status='error' OR (status='success' AND async_status='error')
        affected_sql = f"""
            SELECT
                COUNT(DISTINCT j.bbk_id) AS affected_branch_count,
                COUNT(DISTINCT j.creator_user_id) AS affected_manager_count
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE e.actual_time >= %s AND e.actual_time <= %s
              AND (
                e.status = 'error'
                OR (e.status = 'success' AND e.async_status = 'error')
              )
              AND j.deleted_at IS NULL
              AND j.status != 'deleted'
              {bbk_filter_sql}
              {source_filter_sql}
        """
        affected_params = (
            [start_time, end_time] + bbk_filter_params + source_filter_params
        )
        affected_row = await db.fetch_one(affected_sql, tuple(affected_params))
        affected_branch_count = int(
            (
                affected_row.get("affected_branch_count", 0)
                if affected_row
                else 0
            ),
        )
        affected_manager_count = int(
            (
                affected_row.get("affected_manager_count", 0)
                if affected_row
                else 0
            ),
        )

        # 2. 报错原因分布（复用现有逻辑）
        error_reasons = await self._fetch_cron_error_reasons(
            db,
            start_time,
            end_time,
            bbk_filter_sql,
            bbk_filter_params,
            source_filter_sql,
            source_filter_params,
        )

        # 3. 分行异常排行（按报错次数由高到低，综合判断失败状态）
        branch_rank_sql = f"""
            SELECT
                j.bbk_id,
                COUNT(*) AS error_count,
                SUM(
                    CASE WHEN e.status = 'error'
                         OR (e.status = 'success' AND e.async_status = 'error')
                    THEN 1 ELSE 0 END
                ) AS branch_error_count,
                COUNT(
                    DISTINCT CASE
                        WHEN e.status = 'error'
                        OR (e.status = 'success' AND e.async_status = 'error')
                        THEN j.creator_user_id
                        ELSE NULL
                    END
                ) AS affected_managers
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE e.actual_time >= %s AND e.actual_time <= %s
              AND j.deleted_at IS NULL
              AND j.status != 'deleted'
              {bbk_filter_sql}
              {source_filter_sql}
            GROUP BY j.bbk_id
            HAVING branch_error_count > 0
            ORDER BY branch_error_count DESC
        """
        branch_rank_params = (
            [start_time, end_time] + bbk_filter_params + source_filter_params
        )
        branch_rank_rows = await db.fetch_all(
            branch_rank_sql,
            tuple(branch_rank_params),
        )

        branch_error_rank = []
        for row in branch_rank_rows:
            bbk_id = row.get("bbk_id") or ""
            if not bbk_id:
                continue
            bbk_name = get_bbk_name_by_id(bbk_id) or bbk_id
            total_executions = int(row.get("error_count", 0))
            error_count = int(row.get("branch_error_count", 0))
            affected_managers = int(row.get("affected_managers", 0))
            error_rate = (
                (error_count / total_executions * 100)
                if total_executions > 0
                else 0.0
            )

            branch_error_rank.append(
                CronBranchErrorRankItem(
                    bbk_id=bbk_id,
                    bbk_name=bbk_name,
                    total_executions=total_executions,
                    error_count=error_count,
                    error_rate=round(error_rate, 2),
                    affected_managers=affected_managers,
                ),
            )

        return CronBranchErrorResponse(
            start_date=start_str,
            end_date=end_str,
            affected_branch_count=affected_branch_count,
            affected_manager_count=affected_manager_count,
            error_reasons=error_reasons,
            branch_error_rank=branch_error_rank,
        )

    async def _fetch_cron_error_reasons(
        self,
        db: Any,
        start_time: datetime,
        end_time: datetime,
        bbk_filter_sql: str,
        bbk_filter_params: List,
        source_filter_sql: str = "",
        source_filter_params: List = None,
    ) -> List[CronErrorReasonItem]:
        """获取报错原因分布（综合判断失败状态）."""
        if source_filter_params is None:
            source_filter_params = []

        # 综合判断失败状态，区分失败原因来源：
        # - status='error': 使用 error_message 分类
        # - status='success' AND async_status='error': 失败原因为"子任务执行失败"
        rows = await db.fetch_all(
            f"""
            SELECT
                CASE
                    WHEN e.status = 'success' AND e.async_status = 'error'
                        THEN '子任务执行失败'
                    WHEN e.error_message LIKE '%%channel not found%%'
                        THEN '渠道不存在'
                    WHEN e.error_message LIKE '%%cron auth user_info is expired%%'
                        THEN 'token过期'
                    WHEN e.error_message LIKE '%%Illegal Argument%%'
                        THEN '密文长度错误'
                    WHEN LOWER(e.error_message) LIKE '%%validation error for agentrequest%%'
                        THEN '智能体请求校验失败'
                    WHEN e.error_message LIKE '%%Agent execution did not complete%%'
                        THEN '模型错误'
                    ELSE '其他'
                END AS reason,
                COUNT(*) AS count
            FROM swe_cron_executions e
            LEFT JOIN swe_cron_jobs j ON e.job_id = j.id
            WHERE e.actual_time >= %s AND e.actual_time <= %s
              AND (
                e.status = 'error'
                OR (e.status = 'success' AND e.async_status = 'error')
              )
              AND j.deleted_at IS NULL
              AND j.status != 'deleted'
              {bbk_filter_sql}
              {source_filter_sql}
            GROUP BY 1
            ORDER BY count DESC, reason ASC
            LIMIT 10
            """,
            tuple(
                [start_time, end_time]
                + bbk_filter_params
                + source_filter_params,
            ),
        )

        pairs = [
            (row.get("reason") or "其他", int(row.get("count") or 0))
            for row in rows
        ]
        total = sum(count for _, count in pairs)

        items = []
        for reason, count in pairs:
            percent = (count / total * 100) if total > 0 else 0.0
            items.append(
                CronErrorReasonItem(
                    reason=reason,
                    count=count,
                    percent=round(percent, 2),
                ),
            )
        return items

    def _parse_date_range(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Tuple[datetime, datetime]:
        """解析日期字符串为时间范围。

        Args:
            start_date: 开始日期字符串 (YYYY-MM-DD格式)
            end_date: 结束日期字符串 (YYYY-MM-DD格式)

        Returns:
            (start_time, end_time) datetime 元组

        Note:
            未传参数时默认最近30天。
            结束日期会设置为当天的23:59:59以包含全天数据。
        """
        if start_date and end_date:
            try:
                start_time = datetime.strptime(start_date, "%Y-%m-%d")
                end_time = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    hour=23,
                    minute=59,
                    second=59,
                    microsecond=999999,
                )
                return start_time, end_time
            except ValueError:
                # 格式错误时使用默认值
                pass
        # 默认最近30天
        end_time = (
            datetime.now(BEIJING_TZ)
            .replace(
                hour=23,
                minute=59,
                second=59,
                microsecond=999999,
            )
            .replace(tzinfo=None)
        )
        start_time = end_time - timedelta(days=30)
        start_time = start_time.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return start_time, end_time

    def _resolve_time_range(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> Tuple[datetime, datetime]:
        """解析时间范围，未传则默认最近30天。"""
        if start_date and end_date:
            return start_date, end_date
        # 默认最近30天
        end_time = (
            datetime.now(BEIJING_TZ)
            .replace(
                hour=23,
                minute=59,
                second=59,
                microsecond=999999,
            )
            .replace(tzinfo=None)
        )
        start_time = end_time - timedelta(days=30)
        start_time = start_time.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return start_time, end_time

    @staticmethod
    def _init_skill_dicts(
        skill_jobs: dict,
        skill_total: dict,
        skill_success: dict,
        skill_read: dict,
        skill_error: dict,
        sk: str,
    ) -> None:
        skill_jobs[sk] = set()
        skill_total[sk] = 0
        skill_success[sk] = 0
        skill_read[sk] = 0
        skill_error[sk] = 0

    @staticmethod
    def _parse_skills_used(value: Any) -> Optional[list]:
        """Parse skills_used field into a list of skill name strings.

        Returns None if the value cannot be parsed into a valid list.
        """
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                return None
        if not isinstance(value, list):
            return None
        return value

    @staticmethod
    def _count_skill_execution(
        skill_jobs: dict,
        skill_total: dict,
        skill_success: dict,
        skill_read: dict,
        skill_error: dict,
        sk: str,
        job_id: str,
        status: str,
        is_read: bool,
    ) -> None:
        """Count a single skill execution in the aggregation dicts."""
        skill_total[sk] += 1
        skill_jobs[sk].add(job_id)
        if status == "success":
            skill_success[sk] += 1
        if is_read:
            skill_read[sk] += 1
        if status in ("error", "timeout", "cancelled"):
            skill_error[sk] += 1

    async def get_branch_skills(
        self,
        bbk_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> BranchSkillResponse:
        """获取分行技能维度数据。

        从 swe_cron_executions + swe_tracing_traces 链路，
        提取 skills_used JSON 数组并聚合统计每项技能的执行情况。
        """
        db = get_db_connection()

        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        source_where = " AND j.source_id = %s" if source_id else ""

        sql = f"""
            SELECT
                e.job_id,
                e.status,
                e.is_read,
                t.skills_used
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id = j.id
            JOIN swe_tracing_traces t ON e.trace_id COLLATE utf8mb4_unicode_ci = t.trace_id
            WHERE j.bbk_id = %s
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND t.session_id LIKE 'cron-task%%'
              AND t.skills_used IS NOT NULL
              {source_where}
        """
        params: list = [bbk_id, start_time, end_time]
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(sql, tuple(params))

        seen_jobs: set[str] = set()
        skill_jobs: dict[str, set[str]] = {}
        skill_total: dict[str, int] = {}
        skill_success: dict[str, int] = {}
        skill_read: dict[str, int] = {}
        skill_error: dict[str, int] = {}

        for row in rows:
            skills = self._parse_skills_used(row["skills_used"])
            if not skills:
                continue
            job_id = row["job_id"]
            status = (row["status"] or "").lower()
            is_read = bool(row["is_read"])
            for sk in skills:
                sk = str(sk).strip() if sk else ""
                if not sk:
                    continue
                if sk not in self._ALLOWED_BRANCH_SKILLS:
                    continue
                if sk not in skill_jobs:
                    self._init_skill_dicts(
                        skill_jobs,
                        skill_total,
                        skill_success,
                        skill_read,
                        skill_error,
                        sk,
                    )
                self._count_skill_execution(
                    skill_jobs,
                    skill_total,
                    skill_success,
                    skill_read,
                    skill_error,
                    sk,
                    job_id,
                    status,
                    is_read,
                )

        items: list[BranchSkillItem] = []
        for skill_name, jobs in skill_jobs.items():
            task_count = len(jobs)
            success = skill_success.get(skill_name, 0)
            exec_total = skill_total.get(skill_name, 0)
            items.append(
                BranchSkillItem(
                    skill_name=skill_name,
                    cron_task_count=task_count,
                    success_count=success,
                    success_rate=self._percent(success, exec_total),
                    read_count=skill_read.get(skill_name, 0),
                    error_count=skill_error.get(skill_name, 0),
                ),
            )

        items.sort(key=lambda item: item.cron_task_count, reverse=True)

        return BranchSkillResponse(
            start_date=start_str,
            end_date=end_str,
            bbk_id=bbk_id,
            bbk_name=get_bbk_name_by_id(bbk_id) or bbk_id,
            items=items,
        )

    def _build_allowed_skill_filter(self) -> tuple[str, list[str]]:
        """构建白名单技能过滤条件."""
        allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
        placeholders = ", ".join(["%s"] * len(allowed_skills))
        return placeholders, allowed_skills

    async def _fetch_manager_base_info(
        self,
        db: DatabaseConnection,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> list[dict]:
        """查询客户经理基础信息."""
        placeholders, allowed_skills = self._build_allowed_skill_filter()
        source_where = " AND j.source_id = %s" if source_id else ""
        sql = f"""
            SELECT
                j.tenant_id AS user_id,
                MAX(j.tenant_name) AS user_name,
                COUNT(DISTINCT j.id) AS total_tasks,
                SUM(CASE WHEN e.status = 'success' AND e.async_status = 'success'
                    THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN e.is_read = 1 THEN 1 ELSE 0 END) AS read_tasks
            FROM swe_cron_jobs j
            JOIN swe_cron_executions e ON j.id = e.job_id
                AND e.actual_time >= %s AND e.actual_time <= %s
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE j.bbk_id = %s AND j.deleted_at IS NULL AND j.status != 'deleted'
              AND t.skills_used IS NOT NULL AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']')))
                IN ({placeholders})
              {source_where}
            GROUP BY j.tenant_id
        """
        params: list = [start_time, end_time, bbk_id] + allowed_skills
        if source_id:
            params.append(source_id)
        return await db.fetch_all(sql, tuple(params))

    async def _fetch_manager_skill_count(
        self,
        db: DatabaseConnection,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> dict[str, int]:
        """查询客户经理技能数量."""
        placeholders, allowed_skills = self._build_allowed_skill_filter()
        source_where = " AND j.source_id = %s" if source_id else ""
        sql = f"""
            SELECT j.tenant_id AS user_id,
                COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(t.skills_used,
                    CONCAT('$[', idx.i, ']')))) AS skill_count
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id = j.id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE j.bbk_id = %s AND e.actual_time >= %s AND e.actual_time <= %s
              AND t.skills_used IS NOT NULL AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']')))
                IN ({placeholders})
              {source_where}
            GROUP BY j.tenant_id
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(sql, tuple(params))
        return {row["user_id"]: row["skill_count"] for row in rows}

    async def _fetch_manager_recommended_customers(
        self,
        db: DatabaseConnection,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> dict[str, int]:
        """查询推荐客户数."""
        placeholders, allowed_skills = self._build_allowed_skill_filter()
        source_where = " AND j.source_id = %s" if source_id else ""
        sql = f"""
            SELECT j.tenant_id AS user_id,
                COUNT(DISTINCT s.custuid) AS recommended_customers
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id = j.id
            JOIN swe_cron_subtasks s ON e.trace_id = s.trace_id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE j.bbk_id = %s AND e.actual_time >= %s AND e.actual_time <= %s
              AND s.custuid IS NOT NULL AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']')))
                IN ({placeholders})
              {source_where}
            GROUP BY j.tenant_id
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(sql, tuple(params))
        return {row["user_id"]: row["recommended_customers"] for row in rows}

    async def _fetch_manager_click_stats(
        self,
        db: DatabaseConnection,
        bbk_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> dict[str, dict[str, int]]:
        """查询客户点击统计."""
        placeholders, allowed_skills = self._build_allowed_skill_filter()
        source_where = " AND c.source_id = %s" if source_id else ""
        sql = f"""
            SELECT c.user_id, c.button_type,
                COUNT(DISTINCT c.customer_id) AS customer_count
            FROM swe_html_preview_click_events c
            JOIN swe_cron_executions e ON c.cron_task_id = e.job_id
                AND c.clicked_at >= e.actual_time
                AND c.clicked_at <= COALESCE(e.end_time,
                    e.actual_time + INTERVAL 1 DAY)
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE c.bbk_id = %s AND c.clicked_at >= %s AND c.clicked_at <= %s
              AND c.button_type IN ('plan', 'insight', 'phone')
              AND c.customer_id IS NOT NULL AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']')))
                IN ({placeholders})
              {source_where}
            GROUP BY c.user_id, c.button_type
        """
        params: list = [bbk_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(sql, tuple(params))
        click_map: dict[str, dict[str, int]] = {}
        for row in rows:
            user_id = row["user_id"]
            if user_id not in click_map:
                click_map[user_id] = {}
            click_map[user_id][row["button_type"]] = row["customer_count"]
        return click_map

    def _build_manager_summary_items(
        self,
        base_rows: list[dict],
        skill_count_map: dict[str, int],
        recommended_map: dict[str, int],
        click_map: dict[str, dict[str, int]],
    ) -> list[BranchManagerSummaryItem]:
        """构建客户经理汇总结果."""
        items: list[BranchManagerSummaryItem] = []
        for row in base_rows:
            user_id = row["user_id"]
            user_clicks = click_map.get(user_id, {})
            items.append(
                BranchManagerSummaryItem(
                    user_id=user_id,
                    user_name=row["user_name"] or "",
                    skill_count=skill_count_map.get(user_id, 0),
                    total_tasks=row["total_tasks"] or 0,
                    success_count=row["success_count"] or 0,
                    read_tasks=row["read_tasks"] or 0,
                    recommended_customers=recommended_map.get(user_id, 0),
                    viewed_customers=user_clicks.get("plan", 0),
                    insight_customers=user_clicks.get("insight", 0),
                    phone_customers=user_clicks.get("phone", 0),
                ),
            )
        items.sort(key=lambda x: x.success_count, reverse=True)
        return items

    async def get_branch_manager_summary(
        self,
        bbk_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> BranchManagerSummaryResponse:
        """获取分行客户经理汇总数据（技能视角，使用白名单过滤）。

        只统计使用白名单技能的客户经理，各项指标都基于白名单技能过滤。
        """
        db = get_db_connection()
        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        # 并行查询各项数据
        base_rows, skill_count_map, recommended_map, click_map = (
            await asyncio.gather(
                self._fetch_manager_base_info(
                    db,
                    bbk_id,
                    start_time,
                    end_time,
                    source_id,
                ),
                self._fetch_manager_skill_count(
                    db,
                    bbk_id,
                    start_time,
                    end_time,
                    source_id,
                ),
                self._fetch_manager_recommended_customers(
                    db,
                    bbk_id,
                    start_time,
                    end_time,
                    source_id,
                ),
                self._fetch_manager_click_stats(
                    db,
                    bbk_id,
                    start_time,
                    end_time,
                    source_id,
                ),
            )
        )

        items = self._build_manager_summary_items(
            base_rows,
            skill_count_map,
            recommended_map,
            click_map,
        )

        return BranchManagerSummaryResponse(
            start_date=start_str,
            end_date=end_str,
            bbk_id=bbk_id,
            bbk_name=get_bbk_name_by_id(bbk_id) or bbk_id,
            items=items,
        )

    async def get_branch_skill_managers(
        self,
        bbk_id: str,
        skill_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> BranchSkillManagerResponse:
        """获取分行+技能的客户经理维度数据。

        从 swe_cron_executions 出发，联结 jobs 获取 tenant_name，
        联结 traces 筛选技能，LEFT JOIN click_events 统计点击指标。
        无点击记录时 plan/insight/phone 计数为 0，last_click_time 为 None。
        user_name 取自 swe_cron_jobs.tenant_name。
        """
        db = get_db_connection()

        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        source_where = " AND j.source_id = %s" if source_id else ""
        click_source_on = " AND c.source_id = %s" if source_id else ""

        sql = f"""
            SELECT
                j.tenant_id AS user_id,
                MAX(j.tenant_name) AS user_name,
                COUNT(DISTINCT CASE WHEN e.is_read = 1 THEN e.id END) AS read_count,
                COUNT(DISTINCT CASE WHEN c.button_type = 'plan' THEN c.id END) AS plan_count,
                COUNT(DISTINCT CASE WHEN c.button_type = 'insight' THEN c.id END) AS insight_count,
                COUNT(DISTINCT CASE WHEN c.button_type = 'phone' THEN c.id END) AS phone_count,
                MAX(c.clicked_at) AS last_click_time
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id COLLATE utf8mb4_unicode_ci = j.id
            JOIN swe_tracing_traces t ON e.trace_id COLLATE utf8mb4_unicode_ci = t.trace_id
            LEFT JOIN swe_html_preview_click_events c
                ON c.cron_task_id COLLATE utf8mb4_unicode_ci = e.job_id
                AND c.clicked_at >= %s AND c.clicked_at <= %s
                {click_source_on}
            WHERE j.bbk_id = %s
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND t.skills_used IS NOT NULL
              AND JSON_CONTAINS(t.skills_used, JSON_QUOTE(%s))
              AND t.session_id LIKE 'cron-task%%'
              {source_where}
            GROUP BY j.tenant_id
            ORDER BY read_count DESC
        """
        params: list = [
            start_time,
            end_time,
            bbk_id,
            start_time,
            end_time,
            skill_name,
        ]
        if source_id:
            params.insert(2, source_id)  # click_source_on placeholder
            params.append(source_id)  # source_where placeholder
        rows = await db.fetch_all(sql, tuple(params))

        items: list[BranchSkillManagerItem] = []
        for row in rows:
            last_click = row["last_click_time"]
            items.append(
                BranchSkillManagerItem(
                    user_id=row["user_id"] or "",
                    user_name=row["user_name"] or "",
                    read_count=row["read_count"] or 0,
                    plan_count=row["plan_count"] or 0,
                    insight_count=row["insight_count"] or 0,
                    phone_count=row["phone_count"] or 0,
                    last_click_time=(
                        last_click.strftime("%Y-%m-%d %H:%M:%S")
                        if last_click
                        else None
                    ),
                ),
            )

        return BranchSkillManagerResponse(
            start_date=start_str,
            end_date=end_str,
            bbk_id=bbk_id,
            skill_name=skill_name,
            items=items,
        )

    async def get_branch_skill_manager_customers(
        self,
        bbk_id: str,
        skill_name: str,
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> BranchSkillManagerCustomerResponse:
        """获取分行+技能+客户经理的客户维度数据。

        从 swe_html_preview_click_events 出发，通过 cron_executions
        联结 traces，筛选 skills_used 包含指定技能以及指定客户经理的行，
        按客户聚合点击行为。
        """
        db = get_db_connection()

        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        source_where = " AND c.source_id = %s" if source_id else ""

        sql = f"""
            SELECT
                c.customer_id,
                c.customer_name,
                MAX(CASE WHEN c.button_type = 'plan' THEN 1 ELSE 0 END) AS clicked_plan,
                MAX(CASE WHEN c.button_type = 'insight' THEN 1 ELSE 0 END) AS clicked_insight,
                MAX(CASE WHEN c.button_type = 'phone' THEN 1 ELSE 0 END) AS clicked_phone,
                MAX(c.clicked_at) AS click_time
            FROM swe_html_preview_click_events c
            JOIN swe_cron_executions e ON c.cron_task_id COLLATE utf8mb4_unicode_ci = e.job_id
            JOIN swe_tracing_traces t ON e.trace_id COLLATE utf8mb4_unicode_ci = t.trace_id
            WHERE c.bbk_id = %s
              AND c.user_id = %s
              AND t.skills_used IS NOT NULL
              AND JSON_CONTAINS(t.skills_used, JSON_QUOTE(%s))
              AND c.clicked_at >= %s AND c.clicked_at <= %s
              AND t.session_id LIKE 'cron-task%%'
              {source_where}
            GROUP BY c.customer_id, c.customer_name
            ORDER BY click_time DESC
        """
        params: list = [bbk_id, user_id, skill_name, start_time, end_time]
        if source_id:
            params.append(source_id)
        rows = await db.fetch_all(sql, tuple(params))

        items: list[BranchSkillManagerCustomerItem] = []
        for row in rows:
            click_time = row["click_time"]
            items.append(
                BranchSkillManagerCustomerItem(
                    customer_id=row["customer_id"] or "",
                    customer_name=row["customer_name"] or "",
                    clicked_plan=bool(row["clicked_plan"]),
                    clicked_insight=bool(row["clicked_insight"]),
                    clicked_phone=bool(row["clicked_phone"]),
                    click_time=(
                        click_time.strftime("%Y-%m-%d %H:%M:%S")
                        if click_time
                        else None
                    ),
                ),
            )

        return BranchSkillManagerCustomerResponse(
            start_date=start_str,
            end_date=end_str,
            bbk_id=bbk_id,
            skill_name=skill_name,
            user_id=user_id,
            items=items,
        )

    async def _fetch_manager_user_name(
        self,
        db: DatabaseConnection,
        bbk_id: str,
        user_id: str,
        source_id: Optional[str],
    ) -> str:
        """查询客户经理姓名."""
        source_where = " AND source_id = %s" if source_id else ""
        sql = f"""
            SELECT MAX(tenant_name) AS user_name
            FROM swe_cron_jobs
            WHERE bbk_id = %s AND tenant_id = %s
              AND deleted_at IS NULL AND status != 'deleted'
              {source_where}
        """
        params: list = [bbk_id, user_id]
        if source_id:
            params.append(source_id)
        row = await db.fetch_one(sql, tuple(params))
        return row["user_name"] if row else ""

    async def _fetch_manager_skill_stats(
        self,
        db: DatabaseConnection,
        bbk_id: str,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
        source_id: Optional[str],
    ) -> list[dict]:
        """查询客户经理技能统计."""
        placeholders, allowed_skills = self._build_allowed_skill_filter()
        source_where = " AND j.source_id = %s" if source_id else ""
        sql = f"""
            SELECT
                JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']')))
                    AS skill_name,
                COUNT(DISTINCT e.job_id) AS cron_task_count,
                SUM(CASE WHEN e.status = 'success' AND e.async_status = 'success'
                    THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN e.is_read = 1 THEN 1 ELSE 0 END) AS read_count,
                SUM(CASE WHEN e.status = 'error'
                         OR (e.status = 'success' AND e.async_status = 'error')
                    THEN 1 ELSE 0 END) AS error_count
            FROM swe_cron_executions e
            JOIN swe_cron_jobs j ON e.job_id = j.id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE j.bbk_id = %s AND j.tenant_id = %s
              AND e.actual_time >= %s AND e.actual_time <= %s
              AND t.skills_used IS NOT NULL AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']')))
                IN ({placeholders})
              {source_where}
            GROUP BY skill_name
            ORDER BY success_count DESC
        """
        params: list = [bbk_id, user_id, start_time, end_time] + allowed_skills
        if source_id:
            params.append(source_id)
        return await db.fetch_all(sql, tuple(params))

    def _build_manager_skill_items(
        self,
        rows: list[dict],
    ) -> list[ManagerSkillItem]:
        """构建客户经理技能统计结果（SQL已过滤白名单技能）."""
        items: list[ManagerSkillItem] = []
        for row in rows:
            skill_name = row["skill_name"]
            success_count = row["success_count"] or 0
            error_count = row["error_count"] or 0
            items.append(
                ManagerSkillItem(
                    skill_name=skill_name,
                    cron_task_count=row["cron_task_count"] or 0,
                    success_count=success_count,
                    success_rate=self._percent(
                        success_count,
                        success_count + error_count,
                    ),
                    read_count=row["read_count"] or 0,
                    error_count=error_count,
                ),
            )
        return items

    async def get_manager_skills(
        self,
        bbk_id: str,
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> ManagerSkillResponse:
        """获取客户经理技能维度数据。

        统计指定客户经理在各技能下的执行数据。
        """
        db = get_db_connection()
        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        user_name = await self._fetch_manager_user_name(
            db,
            bbk_id,
            user_id,
            source_id,
        )
        rows = await self._fetch_manager_skill_stats(
            db,
            bbk_id,
            user_id,
            start_time,
            end_time,
            source_id,
        )
        items = self._build_manager_skill_items(rows)

        return ManagerSkillResponse(
            start_date=start_str,
            end_date=end_str,
            bbk_id=bbk_id,
            user_id=user_id,
            user_name=user_name or user_id,
            items=items,
        )

    async def get_manager_customers(
        self,
        bbk_id: str,
        user_id: str,
        skill_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> ManagerCustomerResponse:
        """获取客户经理客户维度数据（技能视角，使用白名单过滤）。

        从 click_events 获取该客户经理点击过的客户，但只统计白名单技能任务的点击。
        如果指定了 skill_name，则只返回该技能下的客户点击情况。
        """
        db = get_db_connection()

        start_time, end_time = self._parse_date_range(start_date, end_date)
        start_str = start_date or start_time.strftime("%Y-%m-%d")
        end_str = end_date or end_time.strftime("%Y-%m-%d")

        source_where = " AND c.source_id = %s" if source_id else ""

        # 如果指定了 skill_name，只用该技能过滤；否则使用白名单
        if skill_name:
            skill_filter = "= %s"
            skill_params = [skill_name]
        else:
            allowed_skills = list(self._ALLOWED_BRANCH_SKILLS)
            skill_filter = f"IN ({', '.join(['%s'] * len(allowed_skills))})"
            skill_params = allowed_skills

        # 查询客户经理姓名（不需要表别名）
        user_source_where = " AND source_id = %s" if source_id else ""
        user_name_sql = f"""
            SELECT MAX(tenant_name) AS user_name
            FROM swe_cron_jobs
            WHERE bbk_id = %s AND tenant_id = %s
              AND deleted_at IS NULL AND status != 'deleted'
              {user_source_where}
        """
        params: list = [bbk_id, user_id]
        if source_id:
            params.append(source_id)
        user_row = await db.fetch_one(user_name_sql, tuple(params))
        user_name = user_row["user_name"] if user_row else ""

        # 查询客户点击统计（技能过滤）
        # 只通过 cron_task_id 关联，不限制点击时间必须在执行期间
        sql = f"""
            SELECT
                c.customer_id,
                c.customer_name,
                MAX(CASE WHEN c.button_type = 'plan' THEN 1 ELSE 0 END) AS clicked_plan,
                MAX(CASE WHEN c.button_type = 'insight' THEN 1 ELSE 0 END) AS clicked_insight,
                MAX(CASE WHEN c.button_type = 'phone' THEN 1 ELSE 0 END) AS clicked_phone,
                MAX(c.clicked_at) AS click_time
            FROM swe_html_preview_click_events c
            JOIN swe_cron_executions e ON c.cron_task_id = e.job_id
            JOIN swe_tracing_traces t ON e.trace_id = t.trace_id
            CROSS JOIN (
                SELECT 0 AS i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
            ) idx
            WHERE c.bbk_id = %s
              AND c.user_id = %s
              AND c.clicked_at >= %s AND c.clicked_at <= %s
              AND c.customer_id IS NOT NULL
              AND t.skills_used IS NOT NULL
              AND t.session_id LIKE 'cron-task%%'
              AND JSON_LENGTH(t.skills_used) > idx.i
              AND JSON_UNQUOTE(JSON_EXTRACT(t.skills_used, CONCAT('$[', idx.i, ']'))) {skill_filter}
              {source_where}
            GROUP BY c.customer_id, c.customer_name
            ORDER BY click_time DESC
        """
        customer_params: list = [
            bbk_id,
            user_id,
            start_time,
            end_time,
        ] + skill_params
        if source_id:
            customer_params.append(source_id)
        rows = await db.fetch_all(sql, tuple(customer_params))

        items: list[ManagerCustomerItem] = []
        for row in rows:
            click_time = row["click_time"]
            items.append(
                ManagerCustomerItem(
                    customer_id=row["customer_id"] or "",
                    customer_name=row["customer_name"] or "",
                    clicked_plan=bool(row["clicked_plan"]),
                    clicked_insight=bool(row["clicked_insight"]),
                    clicked_phone=bool(row["clicked_phone"]),
                    click_time=(
                        click_time.strftime("%Y-%m-%d %H:%M:%S")
                        if click_time
                        else None
                    ),
                ),
            )

        return ManagerCustomerResponse(
            start_date=start_str,
            end_date=end_str,
            bbk_id=bbk_id,
            user_id=user_id,
            user_name=user_name or user_id,
            items=items,
        )

    def _build_bbk_filter(
        self,
        bbk_ids: Optional[str],
    ) -> Tuple[str, List]:
        """构建 bbk 过滤条件。"""
        if not bbk_ids:
            return "", []
        ids = [id.strip() for id in bbk_ids.split(",") if id.strip()]
        if not ids:
            return "", []
        # 总行 100 需同时查询 V00（虚拟标识）
        if "100" in ids and "V00" not in ids:
            ids.append("V00")
        placeholders = ", ".join(["%s"] * len(ids))
        return f" AND j.bbk_id IN ({placeholders})", ids

    def _build_source_filter(
        self,
        source_id: Optional[str],
    ) -> Tuple[str, List]:
        """构建 source 过滤条件。"""
        if not source_id:
            return "", []
        return " AND j.source_id = %s", [source_id]


# Global query service instance
_query_service: Optional[QueryService] = None


def get_query_service() -> QueryService:
    """Get the query service instance.

    Returns:
        QueryService instance
    """
    global _query_service
    if _query_service is None:
        _query_service = QueryService()
    return _query_service
