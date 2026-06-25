# -*- coding: utf-8 -*-
"""资产上传记录数据模型。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AssetUploadRecord(BaseModel):
    """资产上传记录。"""

    id: Optional[int] = Field(default=None, ge=1)
    file_name: str = Field(..., min_length=1, max_length=512)
    file_size: int = Field(..., ge=0)
    asset_path: str = Field(..., min_length=1, max_length=512)
    source_id: Optional[str] = Field(default=None, max_length=64)
    template_flag: Optional[str] = Field(default=None, max_length=64)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AssetUploadRecordCreate(BaseModel):
    """创建上传记录的请求体。"""

    file_name: str = Field(..., min_length=1, max_length=512)
    file_size: int = Field(..., ge=0)
    asset_path: str = Field(..., min_length=1, max_length=512)
    source_id: Optional[str] = Field(default=None, max_length=64)
    template_flag: Optional[str] = Field(default=None, max_length=64)


class PaginatedAssetUploadRecords(BaseModel):
    """分页查询上传记录的响应。"""

    items: list[AssetUploadRecord] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class TemplateItem(BaseModel):
    """模板条目。"""

    templateId: int
    templateName: str
    templateFlag: Optional[str] = None


class AssetUploadFileNameList(BaseModel):
    """所有上传文件名列表。"""

    code: int = Field(default=200)
    error: Optional[str] = Field(default=None)
    data: list[TemplateItem] = Field(default_factory=list)


class TemplateSearchResponse(BaseModel):
    """按文件名搜索模板的响应。"""

    code: int = Field(default=200)
    error: Optional[str] = Field(default=None)
    data: Optional[int] = None


class TemplateResultRequest(BaseModel):
    """查询模板结果的请求体。"""

    resultId: str
    templateId: int


class TemplateResultResponse(BaseModel):
    """查询模板结果的响应。"""

    code: str = Field(default="200")
    message: str = Field(default="OK")
    result: bool = True
    data: Optional[dict] = None
