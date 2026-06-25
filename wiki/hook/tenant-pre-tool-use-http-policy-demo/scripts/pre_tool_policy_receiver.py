# -*- coding: utf-8 -*-
"""租户级 PreToolUse HTTP 策略服务样例。"""

from __future__ import annotations

import argparse
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LOGGER = logging.getLogger(__name__)
HOOK_PATH = "/hooks/pre-tool-policy"


def _extract_command(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    return str(tool_input.get("command") or "").strip()


def _build_policy_response(payload: dict[str, Any]) -> dict[str, Any]:
    command = _extract_command(payload)
    if not command:
        return {}

    if "rm -rf" in command:
        return {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "命令包含高风险删除操作",
            },
        }

    if command.startswith("git push"):
        return {
            "hookSpecificOutput": {
                "permissionDecision": "ask",
                "permissionDecisionReason": "该命令会影响远端仓库，请先审批",
            },
        }

    if command == "ls":
        return {
            "hookSpecificOutput": {
                "permissionDecision": "allow",
                "permissionDecisionReason": "远端策略为 ls 补全展示参数",
                "updatedInput": {
                    "command": "ls -la",
                },
            },
        }

    return {
        "hookSpecificOutput": {
            "permissionDecision": "allow",
            "permissionDecisionReason": "远端策略允许该工具调用",
        },
    }


class PreToolPolicyHandler(BaseHTTPRequestHandler):
    """处理 PreToolUse 策略请求。"""

    server_version = "TenantPreToolPolicyDemo/1.0"

    def do_POST(self) -> None:  # noqa: N802
        if self.path != HOOK_PATH:
            self.send_error(HTTPStatus.NOT_FOUND, "unknown hook path")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid json body")
            return

        if not isinstance(payload, dict):
            self.send_error(HTTPStatus.BAD_REQUEST, "json body must be object")
            return

        response_body = json.dumps(
            _build_policy_response(payload),
            ensure_ascii=False,
        ).encode("utf-8")
        LOGGER.info(
            "policy request event=%s tool=%s",
            payload.get("hook_event_name"),
            payload.get("tool_name"),
        )
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="启动租户级 PreToolUse HTTP 策略服务样例",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=9100, help="监听端口")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    server = ThreadingHTTPServer(
        (args.host, args.port),
        PreToolPolicyHandler,
    )
    LOGGER.info(
        "启动策略服务: http://%s:%s%s",
        args.host,
        args.port,
        HOOK_PATH,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("收到中断信号，准备退出")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
