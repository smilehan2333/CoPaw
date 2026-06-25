# -*- coding: utf-8 -*-
"""带 if 条件过滤的 PreToolUse command hook 样例脚本。"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

ALLOWED_CURL_HOSTS = ("https://api.example.com/", "https://docs.example.com/")
URL_PATTERN = re.compile(r"https?://\S+")


def _load_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("hook payload must be an object")
    return payload


def _extract_command(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    return str(tool_input.get("command") or "").strip()


def _curl_targets(command: str) -> list[str]:
    return URL_PATTERN.findall(command)


def _build_output(command: str) -> dict[str, Any]:
    if "rm -rf" in command:
        return {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "命令包含高风险删除操作",
            },
        }

    targets = _curl_targets(command)
    if targets and not all(
        target.startswith(ALLOWED_CURL_HOSTS) for target in targets
    ):
        return {
            "hookSpecificOutput": {
                "permissionDecision": "ask",
                "permissionDecisionReason": "curl 目标不在 demo 允许域名内",
            },
        }

    return {
        "hookSpecificOutput": {
            "permissionDecision": "allow",
            "permissionDecisionReason": "命令通过条件策略检查",
        },
    }


def main() -> int:
    try:
        payload = _load_payload()
    except Exception as exc:
        print(f"invalid hook payload: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            _build_output(_extract_command(payload)),
            ensure_ascii=False,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
