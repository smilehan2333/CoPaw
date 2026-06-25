# -*- coding: utf-8 -*-
"""SKILL.md frontmatter 解析工具.

统一替代散落在 service.py / version_service.py / skills_market.py /
skills_browse.py / skill_versions.py 的多个手写 line parser。

实现基于 python-frontmatter 包，与 swe 侧 skills_manager.py 保持一致的解析方式
（仅对 market 内部生效；swe 侧本次不改）。
"""

from __future__ import annotations

from typing import Any, Dict

import frontmatter

from .version import normalize_version


def parse_frontmatter(md_content: str) -> Dict[str, Any]:
    """解析 SKILL.md frontmatter，返回 metadata dict（无 frontmatter 时返回空 dict）."""
    if not md_content:
        return {}
    try:
        post = frontmatter.loads(md_content)
    except Exception:  # pylint: disable=broad-except
        return {}
    return dict(post.metadata or {})


def extract_version(md_content: str) -> str:
    """提取 frontmatter 中的 version 字段，去除 v 前缀与引号；不存在则返回空串.

    优先级：顶层 version > metadata.version。
    （swe 侧 skills_manager._extract_version 还会回退 metadata.builtin_skill_version，
    但 market 侧本次不引入该字段——保持纯 version 语义。）
    """
    fm = parse_frontmatter(md_content)
    raw = fm.get("version", "")
    if isinstance(raw, (int, float)):
        raw = str(raw)
    if not isinstance(raw, str):
        return ""
    return normalize_version(raw)


def extract_metadata(md_content: str) -> Dict[str, str]:
    """提取常用元数据字段，缺失字段返回空串.

    Returns:
        包含 name / description / version / chinese_name 的 dict。
    """
    fm = parse_frontmatter(md_content)

    def _str(key: str) -> str:
        val = fm.get(key, "")
        if isinstance(val, (int, float)):
            return str(val)
        return val if isinstance(val, str) else ""

    return {
        "name": _str("name"),
        "description": _str("description"),
        "version": extract_version(md_content),
        "chinese_name": _str("chinese_name"),
    }


def extract_skill_id(
    md_content: str,
    source: str,
    skill_name: str,
    creator_id: str = "",
) -> str:
    """提取或生成技能唯一标识符.

    解析优先级：
    1. metadata.skill_id（frontmatter 明确指定）
    2. 自动生成（根据 source 类型）：
       - builtin: builtin_{skill_name}
       - customized: customized_{creator_id}_{skill_name}（含创建者区分）
       - marketplace:{item_id}: {item_id}（市场分发继承）

    Args:
        md_content: SKILL.md 文件内容
        source: 技能来源（builtin/customized/marketplace:{item_id}）
        skill_name: 技能目录名
        creator_id: 创建者ID（仅 customized 需要，用于区分同租户不同用户）

    Returns:
        skill_id 字段值，若 frontmatter 未指定则自动生成
    """
    fm = parse_frontmatter(md_content)

    # 从顶层 metadata 中提取 skill_id（明确指定则直接使用）
    metadata = fm.get("metadata", {})
    if isinstance(metadata, dict):
        skill_id = metadata.get("skill_id", "")
        if isinstance(skill_id, str) and skill_id:
            return skill_id

    # 自动生成（根据 source 类型决定格式）
    if source == "builtin":
        return f"builtin_{skill_name}"
    elif source == "customized":
        # 用户自建：包含 creator_id 区分同租户不同用户上传同名技能
        if creator_id:
            return f"customized_{creator_id}_{skill_name}"
        else:
            return f"customized_{skill_name}"
    elif source.startswith("marketplace:"):
        # 市场分发：直接使用 item_id（去掉 marketplace: 前缀）
        return source.split(":", 1)[1]
    else:
        return f"{source}_{skill_name}"


def extract_cn_name_from_title(md_content: str) -> str:
    """从 SKILL.md 一级标题提取中文展示名.

    Args:
        md_content: SKILL.md 文件内容

    Returns:
        一级标题内容（去除 # 前缀和空格），若无标题则返回空串
    """
    if not md_content:
        return ""

    # 查找第一个一级标题（以 # 开头，且后面不是 #）
    for line in md_content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("##"):
            # 去除 # 和前后空格
            title = stripped[1:].strip()
            if title:
                return title

    return ""
