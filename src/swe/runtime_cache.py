# -*- coding: utf-8 -*-
"""运行态缓存清理工具。

统一处理轻量模型缓存的释放和失效，避免不同模块各自实现导致
资源泄漏或配置切换后继续复用旧实例。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def dispose_cached_model_async(model: Any) -> None:
    """异步释放缓存模型占用的资源。

    优先尝试 `aclose()`，再回退到 `close()` / `shutdown()`。
    这些方法既可能是同步实现，也可能返回 awaitable，因此统一做
    awaitable 检测。
    """
    for method_name in ("aclose", "close", "shutdown"):
        method = getattr(model, method_name, None)
        if not callable(method):
            continue
        try:
            result = method()
            if inspect.isawaitable(result):
                await result
            return
        except Exception:
            logger.warning(
                "Failed to dispose cached model via %s",
                method_name,
                exc_info=True,
            )
            return


def dispose_cached_model(model: Any) -> None:
    """同步入口释放缓存模型资源。

    若底层只支持异步释放，则在当前 event loop 中调度后台任务；
    无运行中的 event loop 时直接同步执行，确保测试和脚本场景也能
    完整释放。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(dispose_cached_model_async(model))
        return

    loop.create_task(dispose_cached_model_async(model))


def reset_scope_bound_model_caches() -> None:
    """清空与请求/trace 绑定的轻量模型缓存。"""
    from swe.agents.utils import tool_summary
    from swe.app.suggestions.service import SuggestionService

    SuggestionService.reset_model()
    tool_summary.reset_summary_caches()
