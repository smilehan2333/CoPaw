# -*- coding: utf-8 -*-
"""验证 Console chat 请求会透传静态文件 URL 网络字段。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from swe.app.routers import console as console_router
from swe.app.routers.console import _extract_session_and_payload


def test_extract_session_and_payload_keeps_file_url_network():
    payload = _extract_session_and_payload(
        {
            "channel": "console",
            "user_id": "alice",
            "session_id": "chat-1",
            "input": [],
            "file_url_network": "business",
        },
    )

    assert payload["meta"]["file_url_network"] == "business"


def test_extract_session_and_payload_keeps_identity_fields():
    """验证 Console chat 请求会透传 tracing 依赖的身份字段。"""
    payload = _extract_session_and_payload(
        {
            "channel": "console",
            "user_id": "alice",
            "session_id": "chat-1",
            "input": [],
            "user_name": "Alice",
            "bbk_id": "3301",
        },
    )

    assert payload["meta"]["user_name"] == "Alice"
    assert payload["meta"]["bbk_id"] == "3301"


def test_extract_session_and_payload_reads_identity_from_agent_request_meta():
    """验证 AgentRequest 路径会从 channel_meta 兜底读取身份字段。"""
    fake_request = SimpleNamespace(
        channel="console",
        user_id="alice",
        session_id="chat-1",
        input=[],
        channel_meta={
            "user_name": "Alice",
            "bbk_id": "3301",
        },
    )
    with patch.object(console_router, "AgentRequest", SimpleNamespace):
        payload = _extract_session_and_payload(fake_request)

    assert payload["meta"]["user_name"] == "Alice"
    assert payload["meta"]["bbk_id"] == "3301"
