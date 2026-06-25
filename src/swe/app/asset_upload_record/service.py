# -*- coding: utf-8 -*-
"""资产上传记录业务逻辑。"""

import logging
import os
from typing import Any, Optional

import httpx

from .models import (
    AssetUploadRecord,
    AssetUploadFileNameList,
    PaginatedAssetUploadRecords,
    TemplateItem,
    TemplateResultRequest,
    TemplateResultResponse,
    TemplateSearchResponse,
)
from .store import AssetUploadRecordStore

logger = logging.getLogger(__name__)

_LLM_EVALUATE_API_URL = os.environ.get(
    "SWE_LLM_EVALUATE_API_URL",
    "",
)


class AssetUploadRecordService:
    """资产上传记录服务。"""

    def __init__(self, store: AssetUploadRecordStore):
        self._store = store

    async def create_record(
        self,
        *,
        file_name: str,
        file_size: int,
        asset_path: str,
        source_id: Optional[str] = None,
        template_flag: Optional[str] = None,
    ) -> Optional[int]:
        """创建上传记录，写库失败时记录警告但不抛异常。"""
        try:
            return await self._store.insert_record(
                file_name=file_name,
                file_size=file_size,
                asset_path=asset_path,
                source_id=source_id,
                template_flag=template_flag,
            )
        except Exception:
            logger.warning(
                "Failed to persist upload record for file: %s",
                file_name,
                exc_info=True,
            )
            return None

    async def query_records(
        self,
        *,
        source_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PaginatedAssetUploadRecords:
        """分页查询上传记录。"""
        items = await self._store.list_records(
            source_id=source_id,
            page=page,
            page_size=page_size,
        )
        total = await self._store.count_records(source_id=source_id)
        return PaginatedAssetUploadRecords(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_all_file_names(self) -> AssetUploadFileNameList:
        """查询所有上传文件名。"""
        rows = await self._store.list_all_file_names()
        data = [
            TemplateItem(
                templateId=row["id"],
                templateName=row["file_name"],
                templateFlag=row.get("template_flag"),
            )
            for row in rows
        ]
        return AssetUploadFileNameList(data=data)

    async def search_template_id(
        self,
        template_name: str,
    ) -> TemplateSearchResponse:
        """根据文件名搜索模板ID。"""
        template_id = await self._store.get_template_id_by_name(template_name)
        if template_id is None:
            return TemplateSearchResponse(
                code=404,
                error="Template not found",
                data=None,
            )
        return TemplateSearchResponse(data=template_id)

    async def query_template_result(
        self,
        result_id: str,
        template_id: int,
    ) -> TemplateResultResponse:
        """调用外部接口查询模板结果。"""
        base_url = os.environ.get(
            "SWE_LLM_EVALUATE_API_URL",
            _LLM_EVALUATE_API_URL,
        )
        url = f"{base_url.rstrip('/')}/answer/query-record"
        payload = TemplateResultRequest(
            resultId=result_id,
            templateId=template_id,
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload.model_dump())
                resp.raise_for_status()
                body: dict[str, Any] = resp.json()
                return TemplateResultResponse(
                    code=str(body.get("code", "200")),
                    message=body.get("message", "OK"),
                    result=body.get("result", False),
                    data=body.get("data"),
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "Failed to query template result: %s",
                exc,
                exc_info=True,
            )
            return TemplateResultResponse(
                code="500",
                message=f"External API error: {exc}",
                result=False,
                data=None,
            )
