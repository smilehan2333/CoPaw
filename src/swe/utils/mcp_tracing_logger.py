# -*- coding: utf-8 -*-
"""MCP Tracing Debug Logger - 专门用于调试 MCP tracing 流程。

将调试日志写入单独文件，避免控制台日志过多。
"""

import logging
from pathlib import Path

# 获取日志目录（通常与 swe.log 同目录）
_LOG_DIR = Path.home() / ".swe" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# 创建单独的 logger，不继承父 logger
_MCP_TRACING_LOGGER = logging.getLogger("mcp_tracing_debug")
_MCP_TRACING_LOGGER.setLevel(logging.DEBUG)
_MCP_TRACING_LOGGER.propagate = False  # 不输出到控制台

# 添加文件 handler
_LOG_FILE = _LOG_DIR / "mcp_tracing_debug.log"
_FILE_HANDLER = logging.FileHandler(
    _LOG_FILE,
    encoding="utf-8",
    mode="a",
)
_FILE_HANDLER.setLevel(logging.DEBUG)
_FILE_HANDLER.setFormatter(
    logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    ),
)
_MCP_TRACING_LOGGER.addHandler(_FILE_HANDLER)


def get_mcp_tracing_logger() -> logging.Logger:
    """获取 MCP tracing debug logger."""
    return _MCP_TRACING_LOGGER


# 清空日志文件，方便查看最新调试信息
def clear_debug_log() -> None:
    """清空调试日志文件，方便查看最新输出。"""
    with open(_LOG_FILE, "w", encoding="utf-8") as f:
        f.write("=== MCP Tracing Debug Log Started ===\n")
        f.write(f"Log file: {_LOG_FILE}\n\n")
