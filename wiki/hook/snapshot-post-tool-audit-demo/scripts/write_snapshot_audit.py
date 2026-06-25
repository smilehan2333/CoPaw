# -*- coding: utf-8 -*-
"""PostToolUse 快照审计样例脚本。"""

from __future__ import annotations

import json
import sys
from typing import Any

MAX_SUMMARY_LENGTH = 240


def _load_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("hook payload must be an object")
    return payload


def _summarize(value: Any) -> str:
    if value is None:
        return "无工具结果"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return text[:MAX_SUMMARY_LENGTH]


def _snapshot_meta_summary(payload: dict[str, Any]) -> str:
    meta = payload.get("conversation_snapshot_meta")
    if not isinstance(meta, dict):
        return "未收到会话快照元信息"
    included = meta.get("included_messages", 0)
    omitted = meta.get("omitted_messages", 0)
    limit = meta.get("limit", 0)
    unavailable = meta.get("unavailable")
    if unavailable:
        reason = meta.get("unavailable_reason") or "unknown"
        return f"会话快照不可用: {reason}"
    return f"会话快照 included={included}, omitted={omitted}, limit={limit}"


def _build_output(payload: dict[str, Any]) -> dict[str, Any]:
    context = [
        f"PostToolUse 审计事件: {payload.get('hook_event_name')}",
        f"工具: {payload.get('tool_name') or 'unknown'}",
        f"tool_use_id: {payload.get('tool_use_id') or 'unknown'}",
        f"tool_response 摘要: {_summarize(payload.get('tool_response'))}",
        _snapshot_meta_summary(payload),
    ]
    return {
        "hookSpecificOutput": {
            "additionalContext": context,
        },
    }


def main() -> int:
    try:
        payload = _load_payload()
    except Exception as exc:
        print(f"invalid hook payload: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(_build_output(payload), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
