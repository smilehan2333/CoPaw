# -*- coding: utf-8 -*-
"""读取完整会话历史并调用外部策略接口判定 BeforeStop。"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

POLICY_URL_ENV = "FINAL_OUTPUT_GUARD_URL"
POLICY_TOKEN_ENV = "FINAL_OUTPUT_GUARD_AUTH_TOKEN"
POLICY_TIMEOUT_ENV = "FINAL_OUTPUT_GUARD_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 10.0


def _block(reason: str) -> dict[str, str]:
    """构造 BeforeStop 支持的保守阻断输出。"""
    return {
        "decision": "block",
        "reason": reason[:2000],
    }


def _read_payload() -> dict[str, Any] | None:
    """读取 hook runtime 通过 stdin 传入的 JSON 对象。"""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("invalid hook payload", file=sys.stderr)
        return None
    if not isinstance(payload, dict):
        print("invalid hook payload", file=sys.stderr)
        return None
    return payload


def _read_transcript(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """读取 HookContext 中 transcript_path 指向的完整会话 JSON。"""
    transcript_path = str(payload.get("transcript_path") or "").strip()
    if not transcript_path:
        return None, "无法读取完整会话历史：HookContext 缺少 transcript_path"

    path = Path(transcript_path).expanduser()
    try:
        raw = path.read_text(encoding="utf-8")
        transcript = json.loads(raw)
    except OSError as exc:
        return None, f"无法读取完整会话历史：{exc}"
    except json.JSONDecodeError as exc:
        return None, f"无法读取完整会话历史：会话文件不是合法 JSON ({exc})"

    if not isinstance(transcript, dict):
        return None, "无法读取完整会话历史：会话文件根对象不是 JSON object"
    return transcript, None


def _policy_timeout() -> float:
    raw = os.environ.get(POLICY_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def _call_policy(
    *,
    url: str,
    hook_context: dict[str, Any],
    transcript: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """调用外部策略接口并返回 JSON 响应。"""
    body = json.dumps(
        {
            "hookContext": hook_context,
            "transcript": transcript,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    token = os.environ.get(POLICY_TOKEN_ENV, "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - demo endpoint is user configured.
            request,
            timeout=_policy_timeout(),
        ) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        if exc.code in {409, 422}:
            return _parse_policy_response(raw)
        return None, f"外部策略接口返回 HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return None, f"外部策略接口调用失败：{exc.reason}"
    except TimeoutError:
        return None, "外部策略接口调用超时"

    return _parse_policy_response(raw)


def _parse_policy_response(
    raw: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """解析外部策略接口响应。"""
    try:
        response = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        return None, f"外部策略接口响应不是合法 JSON：{exc}"
    if not isinstance(response, dict):
        return None, "外部策略接口响应根对象不是 JSON object"
    return response, None


def _normalize_policy_decision(response: dict[str, Any]) -> dict[str, str]:
    """把外部策略响应归一成 BeforeStop 支持的 hook 输出。"""
    decision = str(response.get("decision") or "").strip()
    reason = str(response.get("reason") or "").strip()
    if decision not in {"allow", "block"}:
        return _block(
            "外部策略接口响应缺少合法 decision，只支持 allow 或 block",
        )
    if not reason:
        reason = (
            "外部策略允许最终输出"
            if decision == "allow"
            else "外部策略阻断最终输出"
        )
    return {
        "decision": decision,
        "reason": reason[:2000],
    }


def _build_output(payload: dict[str, Any]) -> dict[str, str]:
    """读取完整历史、调用外部接口并构造 hook 输出。"""
    if payload.get("hook_event_name") != "BeforeStop":
        return {"decision": "allow", "reason": "非 BeforeStop 事件，跳过检查"}

    transcript, error = _read_transcript(payload)
    if error is not None or transcript is None:
        return _block(error or "无法读取完整会话历史")

    policy_url = os.environ.get(POLICY_URL_ENV, "").strip()
    if not policy_url:
        return _block(f"缺少外部策略接口地址：请设置 {POLICY_URL_ENV}")

    response, error = _call_policy(
        url=policy_url,
        hook_context=payload,
        transcript=transcript,
    )
    if error is not None or response is None:
        return _block(error or "外部策略接口调用失败")
    return _normalize_policy_decision(response)


def main() -> int:
    """脚本入口。"""
    payload = _read_payload()
    if payload is None:
        return 1
    print(json.dumps(_build_output(payload), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
