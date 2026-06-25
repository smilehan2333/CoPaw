# -*- coding: utf-8 -*-
"""应用市场数据模型."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MarketItem(BaseModel):
    """市场条目（index.json 中的单条记录）."""

    item_id: str
    item_type: str = "skill"
    name: str
    skill_id: str = ""  # 技能唯一标识符，跨租户共享
    chinese_name: str = ""
    description: str = ""
    guidance: str = ""
    version: str = "1.0.0"
    creator_id: str
    creator_name: str = ""
    category_id: Optional[int] = None
    bbk_ids: list[str] = Field(default_factory=list)
    client_key: str = ""  # MCP 专用，业务唯一键
    status: str = "active"
    created_at: Optional[str] = None  # ISO8601 string from index.json
    updated_at: Optional[str] = None


class CategoryItem(BaseModel):
    """分类条目."""

    id: int
    source_id: str
    name: str
    sort_order: int = 0
    created_at: Optional[datetime] = None  # datetime from MySQL


class SkillManifest(BaseModel):
    """用户本地技能 skill.json 扩展字段."""

    source: str = "customized"
    distributed_by: Optional[str] = None
    received_version: Optional[str] = None
