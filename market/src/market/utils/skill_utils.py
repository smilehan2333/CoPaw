# -*- coding: utf-8 -*-
"""技能名称处理公共工具.

统一处理技能名称的引号去除、规范化等操作，避免散落在多个文件的重复代码。
"""

from __future__ import annotations


def strip_quotes(value: str) -> str:
    """去除字符串周围的单引号或双引号.

    复用 normalize_version 的引号处理逻辑，用于 name、cn_name 等字段。

    Args:
        value: 原始字符串，如 '"技能A"' 或 "'技能B'"

    Returns:
        去除引号后的字符串，如 '技能A' 或 '技能B'
    """
    if not value:
        return ""
    val = value.strip()
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        val = val[1:-1]
    return val.strip()


def clean_skill_name(name: str) -> str:
    """清理技能名称：去除引号和前后空格.

    用于从 frontmatter 提取 name 字段后的清理。

    Args:
        name: 原始技能名称，如 '"技能A-带版本号"'

    Returns:
        清理后的技能名称，如 '技能A-带版本号'
    """
    return strip_quotes(name)
