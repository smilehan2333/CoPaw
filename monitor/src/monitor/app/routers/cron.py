# -*- coding: utf-8 -*-
"""Cron query API router for frontend.

Provides endpoints for frontend to query job definitions and execution history.
"""

import logging
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..models.cron import (
    CronJobModel,
    CronJobQueryParams,
    CronOverviewResponse,
    CronOverviewStatsResponse,
    CronBranchRankingResponse,
    CronBranchTaskRankingResponse,
    CronBranchErrorResponse,
    BranchSkillResponse,
    BranchManagerSummaryResponse,
    BranchSkillManagerResponse,
    BranchSkillManagerCustomerResponse,
    ManagerSkillResponse,
    ManagerCustomerResponse,
    ExecutionModel,
    ExecutionQueryParams,
    PaginatedResponse,
    ExecutionDetailResponse,
    MarkReadResponse,
    SubscriptionDetailItem,
    SubscriptionOverviewItem,
    UnreadCountResponse,
)
from ..services.cron import QueryService, get_query_service
from ..services.cron.export_service import ExportService, get_export_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitor/cron", tags=["cron"])


def _get_source_id_from_header(request: Request) -> str:
    """从请求头获取 source_id."""
    header_source_id = request.headers.get("X-Source-Id")
    if header_source_id:
        return header_source_id
    return "default"


@router.get("/filter-options")
async def get_filter_options(
    request: Request,
    service: QueryService = Depends(get_query_service),
) -> dict:
    """获取筛选项下拉框选项列表。

    返回用户、分行、渠道、来源、任务名称等筛选项的可选值列表，
    用于前端下拉框组件。

    Args:
        service: Query service

    Returns:
        包含各筛选项列表的字典
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_filter_options(source_id=actual_source_id)


@router.get("/overview", response_model=CronOverviewResponse)
async def get_overview(
    request: Request,
    tenant_id: str | None = Query(default=None, description="租户ID筛选"),
    bbk_id: str | None = Query(default=None, description="分行号筛选"),
    start_time: datetime | None = Query(default=None, description="开始时间"),
    end_time: datetime | None = Query(default=None, description="结束时间"),
    service: QueryService = Depends(get_query_service),
) -> CronOverviewResponse:
    """Get aggregated data for the cron overview page."""
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_overview(
        tenant_id=tenant_id,
        bbk_id=bbk_id,
        source_id=actual_source_id,
        start_time=start_time,
        end_time=end_time,
    )


@router.get("/jobs", response_model=PaginatedResponse[CronJobModel])
async def list_jobs(
    request: Request,
    tenant_id: str | None = Query(default=None, description="租户ID筛选"),
    bbk_id: str | None = Query(default=None, description="分行号筛选"),
    creator_user_id: str | None = Query(
        default=None,
        description="创建者ID筛选",
    ),
    job_origin: str | None = Query(default=None, description="任务来源筛选"),
    status: str | None = Query(default=None, description="状态筛选"),
    enabled: bool | None = Query(default=None, description="是否启用筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页数量"),
    service: QueryService = Depends(get_query_service),
) -> PaginatedResponse[CronJobModel]:
    """List cron jobs with pagination and filters.

    Args:
        request: FastAPI request object
        tenant_id: Tenant ID filter
        bbk_id: BBK ID filter (分行号)
        creator_user_id: Creator user ID filter
        status: Status filter
        enabled: Enabled filter
        page: Page number
        page_size: Page size
        service: Query service

    Returns:
        Paginated job list
    """
    actual_source_id = _get_source_id_from_header(request)
    params = CronJobQueryParams(
        tenant_id=tenant_id,
        bbk_id=bbk_id,
        source_id=actual_source_id,
        creator_user_id=creator_user_id,
        job_origin=job_origin,
        status=status,
        enabled=enabled,
        page=page,
        page_size=page_size,
    )
    return await service.list_jobs(params)


@router.get(
    "/subscription-overview",
    response_model=PaginatedResponse[SubscriptionOverviewItem],
)
async def get_subscription_overview(
    request: Request,
    keyword: str | None = Query(default=None, description="订阅任务名称搜索"),
    tenant_id: str | None = Query(default=None, description="租户ID筛选"),
    bbk_id: str | None = Query(default=None, description="所属机构筛选"),
    start_time: datetime | None = Query(default=None, description="开始时间"),
    end_time: datetime | None = Query(default=None, description="结束时间"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页数量"),
    service: QueryService = Depends(get_query_service),
) -> PaginatedResponse[SubscriptionOverviewItem]:
    """查询订阅任务概览聚合数据。"""
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_subscription_overview(
        keyword=keyword,
        tenant_id=tenant_id,
        bbk_id=bbk_id,
        source_id=actual_source_id,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/subscription-overview/{subscription_key}/jobs",
    response_model=PaginatedResponse[SubscriptionDetailItem],
)
async def get_subscription_details(
    request: Request,
    subscription_key: str,
    tenant_id: str | None = Query(default=None, description="租户ID筛选"),
    bbk_id: str | None = Query(default=None, description="所属机构筛选"),
    start_time: datetime | None = Query(default=None, description="开始时间"),
    end_time: datetime | None = Query(default=None, description="结束时间"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页数量"),
    service: QueryService = Depends(get_query_service),
) -> PaginatedResponse[SubscriptionDetailItem]:
    """查询订阅任务详情弹窗数据。"""
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_subscription_details(
        subscription_key=subscription_key,
        tenant_id=tenant_id,
        bbk_id=bbk_id,
        source_id=actual_source_id,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )


@router.get("/jobs/{job_id}", response_model=CronJobModel)
async def get_job(
    request: Request,
    job_id: str,
    service: QueryService = Depends(get_query_service),
) -> CronJobModel:
    """Get a single job by ID.

    Args:
        job_id: Job ID
        service: Query service

    Returns:
        Job details

    Raises:
        HTTPException: If job not found
    """
    actual_source_id = _get_source_id_from_header(request)
    job = await service.get_job(job_id, source_id=actual_source_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/executions", response_model=PaginatedResponse[ExecutionModel])
async def list_executions(
    request: Request,
    job_id: str | None = Query(default=None, description="任务ID筛选"),
    tenant_id: str | None = Query(default=None, description="租户ID筛选"),
    bbk_id: str | None = Query(default=None, description="分行号筛选"),
    status: str | None = Query(default=None, description="执行状态筛选"),
    start_time: datetime | None = Query(
        default=None,
        description="开始时间范围",
    ),
    end_time: datetime | None = Query(
        default=None,
        description="结束时间范围",
    ),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页数量"),
    service: QueryService = Depends(get_query_service),
) -> PaginatedResponse[ExecutionModel]:
    """List execution history with pagination and filters.

    Args:
        request: FastAPI request object
        job_id: Job ID filter
        tenant_id: Tenant ID filter
        bbk_id: BBK ID filter
        status: Status filter
        start_time: Start time filter
        end_time: End time filter
        page: Page number
        page_size: Page size
        service: Query service

    Returns:
        Paginated execution list
    """
    actual_source_id = _get_source_id_from_header(request)
    logger.warning(
        "[cron executions debug] request received: source_id=%s job_id=%s tenant_id=%s bbk_id=%s status=%s start_time=%s end_time=%s page=%s page_size=%s",
        actual_source_id,
        job_id,
        tenant_id,
        bbk_id,
        status,
        start_time,
        end_time,
        page,
        page_size,
    )
    params = ExecutionQueryParams(
        job_id=job_id,
        tenant_id=tenant_id,
        bbk_id=bbk_id,
        source_id=actual_source_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    return await service.list_executions(params)


@router.get(
    "/executions/{execution_id}",
    response_model=ExecutionDetailResponse,
)
async def get_execution(
    request: Request,
    execution_id: int,
    service: QueryService = Depends(get_query_service),
) -> ExecutionDetailResponse:
    """Get a single execution by ID.

    Args:
        execution_id: Execution ID
        service: Query service

    Returns:
        Execution details

    Raises:
        HTTPException: If execution not found
    """
    actual_source_id = _get_source_id_from_header(request)
    execution = await service.get_execution(
        execution_id,
        source_id=actual_source_id,
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ExecutionDetailResponse.model_validate(execution)


@router.get("/export")
async def export_data(
    request: Request,
    job_id: str | None = Query(default=None, description="任务ID筛选"),
    tenant_id: str | None = Query(default=None, description="租户ID筛选"),
    bbk_id: str | None = Query(default=None, description="分行号筛选"),
    enabled: bool | None = Query(default=None, description="是否启用筛选"),
    status: str | None = Query(default=None, description="状态筛选"),
    start_time: datetime | None = Query(
        default=None,
        description="开始时间范围",
    ),
    end_time: datetime | None = Query(
        default=None,
        description="结束时间范围",
    ),
    export_type: str = Query(
        default="executions",
        description="导出类型: jobs/executions",
    ),
    query_service: QueryService = Depends(get_query_service),
    export_service: ExportService = Depends(get_export_service),
) -> StreamingResponse:
    """Export cron data to Excel.

    Args:
        request: FastAPI request object
        job_id: Job ID filter (for executions)
        tenant_id: Tenant ID filter
        bbk_id: BBK ID filter (分行号)
        enabled: Enabled filter (是否启用)
        status: Status filter
        start_time: Start time filter (for executions)
        end_time: End time filter (for executions)
        export_type: Export type (jobs or executions)
        query_service: Query service
        export_service: Export service

    Returns:
        Excel file download
    """
    actual_source_id = _get_source_id_from_header(request)
    try:
        if export_type == "jobs":
            jobs = await query_service.get_jobs_for_export(
                tenant_id=tenant_id,
                bbk_id=bbk_id,
                source_id=actual_source_id,
                enabled=enabled,
                status=status,
            )
            excel_bytes = export_service.export_jobs(jobs)
            filename = "定时任务.xlsx"
        else:
            executions = await query_service.get_executions_for_export(
                job_id=job_id,
                tenant_id=tenant_id,
                source_id=actual_source_id,
                status=status,
                start_time=start_time,
                end_time=end_time,
            )
            excel_bytes = export_service.export_executions(executions)
            filename = "定时任务执行情况.xlsx"

        # RFC 5987: 使用filename*参数支持中文文件名
        encoded_filename = quote(filename)
        return StreamingResponse(
            BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            },
        )
    except Exception as e:
        logger.error("Failed to export data: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/mark-read", response_model=MarkReadResponse)
async def mark_job_as_read(
    request: Request,
    job_id: str,
    service: QueryService = Depends(get_query_service),
) -> MarkReadResponse:
    """标记任务为已读。

    将指定任务的所有成功执行的未读记录标记为已读。
    用户查看任务执行结果后调用此接口。

    Args:
        job_id: 任务ID
        service: Query service

    Returns:
        标记结果，包含更新的记录数
    """
    actual_source_id = _get_source_id_from_header(request)
    try:
        count = await service.mark_job_as_read(
            job_id,
            source_id=actual_source_id,
        )
        return MarkReadResponse(marked=True, count=count)
    except Exception as e:
        logger.error("Failed to mark job as read: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    request: Request,
    tenant_id: str | None = Query(default=None, description="租户ID筛选"),
    service: QueryService = Depends(get_query_service),
) -> UnreadCountResponse:
    """获取未读任务数量统计。

    返回各任务的未读成功执行记录数量，用于前端展示未读提醒。

    Args:
        tenant_id: 租户ID筛选（可选）
        service: Query service

    Returns:
        未读数量统计
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_unread_count(
        tenant_id,
        source_id=actual_source_id,
    )


@router.get("/overview-stats", response_model=CronOverviewStatsResponse)
async def get_overview_stats(
    request: Request,
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    bbk_ids: str | None = Query(
        default=None,
        description="分行号筛选（逗号分隔）",
    ),
    service: QueryService = Depends(get_query_service),
) -> CronOverviewStatsResponse:
    """获取定时任务概览统计。

    返回时间范围内的定时任务总数、执行次数、成功率、已读率等统计数据。

    Args:
        start_date: 开始日期筛选 (YYYY-MM-DD格式)
        end_date: 结束日期筛选 (YYYY-MM-DD格式)
        bbk_ids: 分行号筛选（多个用逗号分隔，不传代表查所有分行）
        service: Query service

    Returns:
        概览统计数据
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_overview_stats(
        start_date=start_date,
        end_date=end_date,
        bbk_ids=bbk_ids,
        source_id=actual_source_id,
    )


@router.get("/branch-behavior", response_model=CronBranchRankingResponse)
async def get_branch_behavior(
    request: Request,
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    bbk_ids: str | None = Query(
        default=None,
        description="分行号筛选（逗号分隔）",
    ),
    service: QueryService = Depends(get_query_service),
) -> CronBranchRankingResponse:
    """获取分行综合排行。

    返回各分行的覆盖客户经理数、定时任务数、成功执行数、成功率、已读任务数。

    Args:
        start_date: 开始日期筛选 (YYYY-MM-DD格式)
        end_date: 结束日期筛选 (YYYY-MM-DD格式)
        bbk_ids: 分行号筛选（多个用逗号分隔）
        service: Query service

    Returns:
        分行综合排行数据
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_branch_behavior(
        start_date=start_date,
        end_date=end_date,
        bbk_ids=bbk_ids,
        source_id=actual_source_id,
    )


@router.get(
    "/branch-task-behavior",
    response_model=CronBranchTaskRankingResponse,
)
async def get_branch_task_behavior(
    request: Request,
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    bbk_ids: str | None = Query(
        default=None,
        description="分行号筛选（逗号分隔）",
    ),
    service: QueryService = Depends(get_query_service),
) -> CronBranchTaskRankingResponse:
    """获取分行任务视角综合排行。

    返回各分行的覆盖客户经理数、定时任务数、成功执行数、成功率、
    已读任务数、查看方案任务数/点击数、点击去洞察任务数/点击数、
    点击去电访任务数/点击数、报错执行次数。

    Args:
        start_date: 开始日期筛选 (YYYY-MM-DD格式)
        end_date: 结束日期筛选 (YYYY-MM-DD格式)
        bbk_ids: 分行号筛选（多个用逗号分隔）
        service: Query service

    Returns:
        分行任务视角排行数据
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_branch_task_behavior(
        start_date=start_date,
        end_date=end_date,
        bbk_ids=bbk_ids,
        source_id=actual_source_id,
    )


@router.get("/branch-error", response_model=CronBranchErrorResponse)
async def get_branch_error(
    request: Request,
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    bbk_ids: str | None = Query(
        default=None,
        description="分行号筛选（逗号分隔）",
    ),
    service: QueryService = Depends(get_query_service),
) -> CronBranchErrorResponse:
    """获取分行层异常执行数据。

    返回受影响分行数量、报错原因分布、分行异常排行等数据。

    Args:
        start_date: 开始日期筛选 (YYYY-MM-DD格式)
        end_date: 结束日期筛选 (YYYY-MM-DD格式)
        bbk_ids: 分行号筛选（多个用逗号分隔）
        service: Query service

    Returns:
        分行异常执行数据
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_branch_error(
        start_date=start_date,
        end_date=end_date,
        bbk_ids=bbk_ids,
        source_id=actual_source_id,
    )


@router.get("/branch-skills", response_model=BranchSkillResponse)
async def get_branch_skills(
    request: Request,
    bbk_id: str = Query(..., description="分行ID"),
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    service: QueryService = Depends(get_query_service),
) -> BranchSkillResponse:
    """获取分行技能维度数据。

    返回指定分行在时间范围内的技能统计，包括定时任务数、
    成功执行数、成功率、已读任务数、报错次数。

    Args:
        bbk_id: 分行ID
        start_date: 开始日期
        end_date: 结束日期
        service: Query service

    Returns:
        技能维度列表
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_branch_skills(
        bbk_id=bbk_id,
        start_date=start_date,
        end_date=end_date,
        source_id=actual_source_id,
    )


@router.get(
    "/branch-manager-summary",
    response_model=BranchManagerSummaryResponse,
)
async def get_branch_manager_summary(
    request: Request,
    bbk_id: str = Query(..., description="分行ID"),
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    service: QueryService = Depends(get_query_service),
) -> BranchManagerSummaryResponse:
    """获取分行客户经理汇总数据。

    返回指定分行在时间范围内的客户经理统计，包括技能数量、
    任务总数、成功执行数、已读任务数、推荐客户数、查看方案客户数、
    去洞察客户数、去电访客户数。

    Args:
        bbk_id: 分行ID
        start_date: 开始日期
        end_date: 结束日期
        service: Query service

    Returns:
        客户经理汇总列表
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_branch_manager_summary(
        bbk_id=bbk_id,
        start_date=start_date,
        end_date=end_date,
        source_id=actual_source_id,
    )


@router.get(
    "/branch-skill-managers",
    response_model=BranchSkillManagerResponse,
)
async def get_branch_skill_managers(
    request: Request,
    bbk_id: str = Query(..., description="分行ID"),
    skill_name: str = Query(..., description="技能名称"),
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    service: QueryService = Depends(get_query_service),
) -> BranchSkillManagerResponse:
    """获取技能下的客户经理维度数据。

    返回指定分行、指定技能下的客户经理统计，包括已读次数、
    方案次数、洞察次数、电访次数、最后一次点击时间。

    Args:
        bbk_id: 分行ID
        skill_name: 技能名称
        start_date: 开始日期
        end_date: 结束日期
        service: Query service

    Returns:
        客户经理维度列表
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_branch_skill_managers(
        bbk_id=bbk_id,
        skill_name=skill_name,
        start_date=start_date,
        end_date=end_date,
        source_id=actual_source_id,
    )


@router.get(
    "/branch-skill-manager-customers",
    response_model=BranchSkillManagerCustomerResponse,
)
async def get_branch_skill_manager_customers(
    request: Request,
    bbk_id: str = Query(..., description="分行ID"),
    skill_name: str = Query(..., description="技能名称"),
    user_id: str = Query(..., description="客户经理ID"),
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    service: QueryService = Depends(get_query_service),
) -> BranchSkillManagerCustomerResponse:
    """获取客户经理下的客户维度数据。

    返回指定分行、指定技能、指定客户经理下的客户统计，包括
    是否点击方案、是否点击洞察、是否点击电访、点击时间。

    Args:
        bbk_id: 分行ID
        skill_name: 技能名称
        user_id: 客户经理ID
        start_date: 开始日期
        end_date: 结束日期
        service: Query service

    Returns:
        客户维度列表
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_branch_skill_manager_customers(
        bbk_id=bbk_id,
        skill_name=skill_name,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        source_id=actual_source_id,
    )


@router.get("/manager-skills", response_model=ManagerSkillResponse)
async def get_manager_skills(
    request: Request,
    bbk_id: str = Query(..., description="分行ID"),
    user_id: str = Query(..., description="客户经理ID"),
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    service: QueryService = Depends(get_query_service),
) -> ManagerSkillResponse:
    """获取客户经理技能维度数据。

    返回指定客户经理在各技能下的统计，包括定时任务数、成功执行数、
    成功率、已读任务数、报错次数。

    Args:
        bbk_id: 分行ID
        user_id: 客户经理ID
        start_date: 开始日期
        end_date: 结束日期
        service: Query service

    Returns:
        技能维度列表
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_manager_skills(
        bbk_id=bbk_id,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        source_id=actual_source_id,
    )


@router.get("/manager-customers", response_model=ManagerCustomerResponse)
async def get_manager_customers(
    request: Request,
    bbk_id: str = Query(..., description="分行ID"),
    user_id: str = Query(..., description="客户经理ID"),
    skill_name: str | None = Query(
        default=None,
        description="技能名称（可选，用于筛选特定技能的客户）",
    ),
    start_date: str | None = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
    ),
    end_date: str | None = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
    ),
    service: QueryService = Depends(get_query_service),
) -> ManagerCustomerResponse:
    """获取客户经理客户维度数据。

    返回指定客户经理点击过的客户统计，包括是否点击方案、是否点击洞察、
    是否点击电访、点击时间。

    Args:
        bbk_id: 分行ID
        user_id: 客户经理ID
        skill_name: 技能名称（可选，用于筛选特定技能的客户）
        start_date: 开始日期
        end_date: 结束日期
        service: Query service

    Returns:
        客户维度列表
    """
    actual_source_id = _get_source_id_from_header(request)
    return await service.get_manager_customers(
        bbk_id=bbk_id,
        user_id=user_id,
        skill_name=skill_name,
        start_date=start_date,
        end_date=end_date,
        source_id=actual_source_id,
    )
