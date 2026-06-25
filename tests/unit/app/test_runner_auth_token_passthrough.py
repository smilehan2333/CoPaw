# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from typing import Any
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from swe.app.runner.runner import AgentRunner


def _fake_agent_config():
    return SimpleNamespace(
        mcp=None,
        running=SimpleNamespace(
            suggestions=SimpleNamespace(
                enabled=False,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_query_handler_injects_auth_headers_into_mcp_headers_and_context(
    monkeypatch,
) -> None:
    runner = AgentRunner(agent_id="test-agent")
    runner.session = SimpleNamespace(
        load_session_state=AsyncMock(),
        mutate_session_state=AsyncMock(return_value={}),
        save_session_state=AsyncMock(),
    )
    setattr(runner, "_chat_manager", None)

    captured: dict[str, Any] = {}

    async def fake_build_clients(
        _mcp,
        passthrough_headers=None,
        session_id=None,
        trace_id=None,
    ):
        captured["passthrough_headers"] = passthrough_headers
        captured["session_id"] = session_id
        captured["trace_id"] = trace_id
        return []

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["request_context"] = kwargs["request_context"]

        async def register_mcp_clients(self):
            return

        def set_console_output_enabled(self, enabled=False):
            del enabled

        def rebuild_sys_prompt(self):
            return

        async def __call__(self, _msgs):
            return

    async def fake_stream_printing_messages(*, agents, coroutine_task):
        del agents
        await coroutine_task
        for item in ():
            yield item

    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _fake_agent_config(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._build_and_connect_mcp_clients",
        fake_build_clients,
    )
    monkeypatch.setattr("swe.app.runner.runner.SWEAgent", FakeAgent)
    monkeypatch.setattr(
        "swe.app.runner.runner.stream_printing_messages",
        fake_stream_printing_messages,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner.build_env_context",
        lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._cleanup_mcp_clients",
        AsyncMock(),
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        trace_id="trace-1",
        auth_token="token-123",
        cookie="foo=bar; com.cmb.dw.rtl.sso.token=auth-123",
    )
    msgs = [SimpleNamespace(get_text_content=lambda: "hello")]

    results = []
    async for item in runner.query_handler(msgs, request=request):
        results.append(item)

    assert not results
    assert captured["passthrough_headers"] == {
        "cookie": "foo=bar; com.cmb.dw.rtl.sso.token=auth-123",
    }
    assert captured["session_id"] == "session-1"
    assert captured["trace_id"] == "trace-1"
    assert captured["request_context"]["auth_token"] == "token-123"


@pytest.mark.asyncio
async def test_query_handler_keeps_existing_passthrough_headers(monkeypatch):
    runner = AgentRunner(agent_id="test-agent")
    runner.session = SimpleNamespace(
        load_session_state=AsyncMock(),
        mutate_session_state=AsyncMock(return_value={}),
        save_session_state=AsyncMock(),
    )
    setattr(runner, "_chat_manager", None)

    captured: dict[str, Any] = {}

    async def fake_build_clients(
        _mcp,
        passthrough_headers=None,
        session_id=None,
        trace_id=None,
    ):
        captured["passthrough_headers"] = passthrough_headers
        captured["session_id"] = session_id
        captured["trace_id"] = trace_id
        return []

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["request_context"] = kwargs["request_context"]

        async def register_mcp_clients(self):
            return

        def set_console_output_enabled(self, enabled=False):
            del enabled

        def rebuild_sys_prompt(self):
            return

        async def __call__(self, _msgs):
            return

    async def fake_stream_printing_messages(*, agents, coroutine_task):
        del agents
        await coroutine_task
        for item in ():
            yield item

    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _fake_agent_config(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._build_and_connect_mcp_clients",
        fake_build_clients,
    )
    monkeypatch.setattr("swe.app.runner.runner.SWEAgent", FakeAgent)
    monkeypatch.setattr(
        "swe.app.runner.runner.stream_printing_messages",
        fake_stream_printing_messages,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner.build_env_context",
        lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._cleanup_mcp_clients",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner.get_current_passthrough_headers",
        lambda: {
            "authorization": "Bearer existing",
            "cookie": "foo=existing",
        },
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        trace_id="trace-1",
        auth_token="token-123",
        cookie="foo=bar; com.cmb.dw.rtl.sso.token=auth-123",
    )
    msgs = [SimpleNamespace(get_text_content=lambda: "hello")]

    results = []
    async for item in runner.query_handler(msgs, request=request):
        results.append(item)

    assert not results
    assert captured["passthrough_headers"] == {
        "authorization": "Bearer existing",
        "cookie": "foo=bar; com.cmb.dw.rtl.sso.token=auth-123",
    }
    assert captured["session_id"] == "session-1"
    assert captured["trace_id"] == "trace-1"
    assert captured["request_context"]["auth_token"] == "token-123"


@pytest.mark.asyncio
async def test_query_handler_injects_identity_into_request_context(
    monkeypatch,
):
    """验证 query handler 会把身份字段注入 agent 请求上下文。"""
    runner = AgentRunner(agent_id="test-agent")
    runner.session = SimpleNamespace(
        load_session_state=AsyncMock(),
        mutate_session_state=AsyncMock(return_value={}),
        save_session_state=AsyncMock(),
    )
    setattr(runner, "_chat_manager", None)

    captured: dict[str, Any] = {}

    async def fake_build_clients(
        _mcp,
        passthrough_headers=None,
        session_id=None,
        trace_id=None,
    ):
        del _mcp, passthrough_headers, session_id, trace_id
        return []

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["request_context"] = kwargs["request_context"]

        async def register_mcp_clients(self):
            return

        def set_console_output_enabled(self, enabled=False):
            del enabled

        def rebuild_sys_prompt(self):
            return

        async def __call__(self, _msgs):
            return

    async def fake_stream_printing_messages(*, agents, coroutine_task):
        del agents
        await coroutine_task
        for item in ():
            yield item

    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _fake_agent_config(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._build_and_connect_mcp_clients",
        fake_build_clients,
    )
    monkeypatch.setattr("swe.app.runner.runner.SWEAgent", FakeAgent)
    monkeypatch.setattr(
        "swe.app.runner.runner.stream_printing_messages",
        fake_stream_printing_messages,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner.build_env_context",
        lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._cleanup_mcp_clients",
        AsyncMock(),
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        trace_id="trace-1",
        channel_meta={
            "source_id": "cmb",
            "user_name": "Alice",
            "bbk_id": "3301",
        },
    )
    msgs = [SimpleNamespace(get_text_content=lambda: "hello")]

    results = []
    async for item in runner.query_handler(msgs, request=request):
        results.append(item)

    assert not results
    assert captured["request_context"]["source_id"] == "cmb"
    assert captured["request_context"]["user_name"] == "Alice"
    assert captured["request_context"]["bbk_id"] == "3301"
