# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from agentscope.message import Msg

from swe.agents.hook_runtime.models import (
    CommandHookHandlerConfig,
    LoadedSkillHookSource,
    HookConfig,
    HookDecision,
    HookEventName,
    HookMatcherGroupConfig,
    HookSessionState,
    HookSessionOverlay,
    AdditionalContext,
    MergedHookResult,
)
from swe.app.runner.runner import (
    AgentRunner,
    _build_and_connect_mcp_clients,
    _create_session_skill_detector,
    _QueryAttemptInput,
    _QueryAttemptState,
    _hook_config_enabled,
    _QueryPreflight,
    _QueryRuntime,
    _RetryState,
    _RuntimeStartResult,
    _TurnPlan,
    _QueryTurnOutcome,
    _emit_runner_hook,
)
from swe.app.runner.session import SafeJSONSession
from swe.config.config import SuggestionMode
from swe.tracing.manager import (
    TraceContext,
    get_current_trace,
    set_current_trace,
)


def _agent_config(hooks: HookConfig | None = None):
    return SimpleNamespace(
        id="test-agent",
        hooks=hooks or HookConfig(),
        mcp=None,
        running=SimpleNamespace(
            suggestions=SimpleNamespace(
                enabled=False,
                mode=SuggestionMode.DISABLED,
            ),
        ),
    )


class _FakeAgent:
    last_env_context = ""

    def __init__(self, **kwargs):
        self.memory = _FakeMemory()
        self.env_context = kwargs.get("env_context", "")
        _FakeAgent.last_env_context = self.env_context

    async def register_mcp_clients(self):
        return

    def set_console_output_enabled(self, enabled=False):
        del enabled

    def rebuild_sys_prompt(self):
        return

    async def __call__(self, turn_msgs):
        for msg in turn_msgs:
            self.memory.content.append((msg, []))
        reply = Msg(name="Friday", role="assistant", content="agent reply")
        self.memory.content.append((reply, []))
        return [reply]

    def state_dict(self):
        return {
            "memory": {
                "content": [
                    [msg.to_dict(), marks]
                    for msg, marks in self.memory.content
                ],
            },
        }

    def load_state_dict(self, state):
        memory_state = state.get("memory", {})
        restored = []
        for raw_msg, marks in memory_state.get("content", []) or []:
            restored.append(
                (
                    Msg(
                        name=raw_msg.get("name"),
                        role=raw_msg.get("role"),
                        content=raw_msg.get("content"),
                        metadata=raw_msg.get("metadata"),
                    ),
                    marks,
                ),
            )
        self.memory.content = restored


class _FakeMemory:
    def __init__(self):
        self.content = []

    async def add(self, msg, marks=None):
        if marks is None:
            normalized_marks = []
        elif isinstance(marks, list):
            normalized_marks = marks
        else:
            normalized_marks = [marks]
        self.content.append((msg, normalized_marks))


async def _fake_stream_printing_messages(*, agents, coroutine_task):
    del agents
    turn_msgs = await coroutine_task
    for msg in turn_msgs:
        yield msg, True


def _patch_normal_agent_path(monkeypatch):
    monkeypatch.setattr(
        "swe.app.runner.runner._build_and_connect_mcp_clients",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr("swe.app.runner.runner.SWEAgent", _FakeAgent)
    monkeypatch.setattr(
        "swe.app.runner.runner.stream_printing_messages",
        _fake_stream_printing_messages,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._cleanup_mcp_clients",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner.build_env_context",
        lambda **kwargs: "base context",
    )


def test_hook_config_enabled_accepts_loaded_skill_sources() -> None:
    state = HookSessionState(
        loaded_skill_sources=[
            LoadedSkillHookSource(
                source_id="skill:xlsx",
                skill_name="xlsx",
                skill_root="/workspace/skills/xlsx",
                source_path="/workspace/skills/xlsx/hooks/hooks.json",
                hook_config=HookConfig(
                    enabled=True,
                    events={
                        HookEventName.STOP: [
                            HookMatcherGroupConfig(
                                id="skill:xlsx:stop",
                                hooks=[
                                    CommandHookHandlerConfig(
                                        id="skill:xlsx:stop-hook",
                                        command="echo {}",
                                    ),
                                ],
                            ),
                        ],
                    },
                ),
            ),
        ],
    )

    assert _hook_config_enabled(HookConfig(), _agent_config(), state)


@pytest.mark.asyncio
async def test_create_session_skill_detector_loads_skill_hooks(
    tmp_path,
) -> None:
    skill_root = tmp_path / "skills" / "xlsx"
    (skill_root / "hooks").mkdir(parents=True)
    (skill_root / "scripts").mkdir()
    (skill_root / "scripts" / "check.py").write_text(
        "print('{}')\n",
        encoding="utf-8",
    )
    (skill_root / "hooks" / "hooks.json").write_text(
        """
        {
          "enabled": true,
          "events": {
            "Stop": [
              {
                "hooks": [
                  {
                    "id": "stop",
                    "type": "command",
                    "argv": ["python", "scripts/check.py"]
                  }
                ]
              }
            ]
          }
        }
        """,
        encoding="utf-8",
    )
    state = HookSessionState()

    def get_state() -> HookSessionState:
        return state

    def set_state(new_state: HookSessionState) -> None:
        nonlocal state
        state = new_state

    detector = _create_session_skill_detector(
        workspace_dir=tmp_path,
        tenant_id="tenant-a",
        user_id="user-1",
        session_id="session-1",
        channel="console",
        source_id="source-1",
        enabled_skills=["xlsx"],
        get_hook_state=get_state,
        set_hook_state=set_state,
        approved_http_urls=set(),
    )

    await detector.start_skill(
        "xlsx",
        trigger_tool="user_message",
        trigger_reason="declared",
    )

    assert state.loaded_skill_sources[0].source_id == "skill:xlsx"
    handler = (
        state.loaded_skill_sources[0]
        .hook_config.events[HookEventName.STOP][0]
        .hooks[0]
    )
    assert handler.id == "skill:xlsx:stop"


@pytest.mark.asyncio
async def test_create_session_skill_detector_loads_http_skill_hooks_without_approvals(
    tmp_path,
) -> None:
    skill_root = tmp_path / "skills" / "xlsx"
    (skill_root / "hooks").mkdir(parents=True)
    (skill_root / "scripts").mkdir()
    (skill_root / "hooks" / "hooks.json").write_text(
        """
        {
          "enabled": true,
          "events": {
            "Stop": [
              {
                "hooks": [
                  {
                    "id": "notify",
                    "type": "http",
                    "url": "https://hooks.example.test/skill"
                  }
                ]
              }
            ]
          }
        }
        """,
        encoding="utf-8",
    )
    state = HookSessionState()

    def get_state() -> HookSessionState:
        return state

    def set_state(new_state: HookSessionState) -> None:
        nonlocal state
        state = new_state

    detector = _create_session_skill_detector(
        workspace_dir=tmp_path,
        tenant_id="tenant-a",
        user_id="user-1",
        session_id="session-1",
        channel="console",
        source_id="source-1",
        enabled_skills=["xlsx"],
        get_hook_state=get_state,
        set_hook_state=set_state,
        approved_http_urls=set(),
    )

    await detector.start_skill(
        "xlsx",
        trigger_tool="user_message",
        trigger_reason="declared",
    )

    handler = (
        state.loaded_skill_sources[0]
        .hook_config.events[HookEventName.STOP][0]
        .hooks[0]
    )
    assert handler.id == "skill:xlsx:notify"
    assert handler.url == "https://hooks.example.test/skill"


@pytest.mark.asyncio
async def test_attach_session_skill_detector_reuses_trace_detector_and_tracing(
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    fake_agent = SimpleNamespace(
        _request_context={},
        get_effective_skills=lambda: ["xlsx"],
    )
    runtime = _QueryRuntime(
        agent=fake_agent,
        agent_config=_agent_config(),
        tenant_hooks=HookConfig(),
        hook_overlay=HookSessionOverlay(),
        chat=None,
        session_skill_detector=None,
        mcp_clients=[],
        session_id="session-1",
        user_id="user-1",
        channel="console",
        skip_history=False,
        pending_confirmed_skill_snapshots={},
    )
    request = SimpleNamespace(trace_id="trace-1", source_id="source-1")
    trace_ctx = TraceContext(
        trace_id="trace-1",
        user_id="user-1",
        session_id="session-1",
        channel="console",
        source_id="source-1",
    )
    trace_manager = AsyncMock()
    trace_manager.emit_skill_invocation = AsyncMock(
        return_value="skill-span-1",
    )
    set_current_trace(trace_ctx)

    with (
        patch("swe.app.runner.runner.has_trace_manager", return_value=True),
        patch(
            "swe.app.runner.runner.get_trace_manager",
            return_value=trace_manager,
        ),
    ):
        runner._attach_session_skill_detector(runtime=runtime, request=request)
        detector = runtime.session_skill_detector
        assert (
            detector
            is fake_agent._request_context["_skill_invocation_detector"]
        )
        assert get_current_trace().skill_detector is detector

        await detector.start_skill(
            "xlsx",
            trigger_tool="user_message",
            trigger_reason="declared",
        )

    trace_manager.emit_skill_invocation.assert_awaited_once()
    set_current_trace(None)


@pytest.mark.asyncio
async def test_stream_single_query_attempt_skips_duplicate_detector_setup(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    fake_agent = SimpleNamespace(
        setup_skill_detector=AsyncMock(),
        rebuild_sys_prompt=lambda: None,
    )
    runtime = _QueryRuntime(
        agent=fake_agent,
        agent_config=_agent_config(),
        tenant_hooks=HookConfig(),
        hook_overlay=HookSessionOverlay(),
        chat=None,
        session_skill_detector=object(),
        mcp_clients=[],
        session_id="session-1",
        user_id="user-1",
        channel="console",
        skip_history=False,
        pending_confirmed_skill_snapshots={},
    )
    monkeypatch.setattr(
        runner,
        "_prepare_query_runtime",
        AsyncMock(return_value=_RuntimeStartResult(runtime=runtime)),
    )
    sentinel = RuntimeError("stop after detector guard")
    monkeypatch.setattr(
        runner,
        "get_state_loaded",
        AsyncMock(side_effect=sentinel),
    )

    attempt_input = _QueryAttemptInput(
        request=SimpleNamespace(),
        msgs=[],
        query=None,
        preflight=_QueryPreflight(),
        trace_id="trace-1",
    )
    attempt_state = _QueryAttemptState()
    retry_state = _RetryState()

    with pytest.raises(RuntimeError, match="stop after detector guard"):
        async for _ in runner._stream_single_query_attempt(
            attempt_input=attempt_input,
            outcome=_QueryTurnOutcome(),
            retry_state=retry_state,
            attempt_state=attempt_state,
        ):
            pass

    fake_agent.setup_skill_detector.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_single_query_attempt_rebinds_trace_detector_from_runtime(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    detector = object()
    fake_agent = SimpleNamespace(
        setup_skill_detector=AsyncMock(),
        rebuild_sys_prompt=lambda: None,
        get_effective_skills=lambda: ["xlsx"],
        _request_context={"_skill_invocation_detector": detector},
    )
    runtime = _QueryRuntime(
        agent=fake_agent,
        agent_config=_agent_config(),
        tenant_hooks=HookConfig(),
        hook_overlay=HookSessionOverlay(),
        chat=None,
        session_skill_detector=detector,
        mcp_clients=[],
        session_id="session-1",
        user_id="user-1",
        channel="console",
        skip_history=False,
        pending_confirmed_skill_snapshots={},
    )
    monkeypatch.setattr(
        runner,
        "_prepare_query_runtime",
        AsyncMock(return_value=_RuntimeStartResult(runtime=runtime)),
    )
    trace_ctx = TraceContext(
        trace_id="trace-1",
        user_id="user-1",
        session_id="session-1",
        channel="console",
        source_id="source-1",
    )
    set_current_trace(trace_ctx)
    sentinel = RuntimeError("stop after trace rebind")
    monkeypatch.setattr(
        runner,
        "get_state_loaded",
        AsyncMock(side_effect=sentinel),
    )

    attempt_input = _QueryAttemptInput(
        request=SimpleNamespace(source_id="source-1"),
        msgs=[],
        query=None,
        preflight=_QueryPreflight(),
        trace_id="trace-1",
    )
    attempt_state = _QueryAttemptState()
    retry_state = _RetryState()

    with pytest.raises(RuntimeError, match="stop after trace rebind"):
        async for _ in runner._stream_single_query_attempt(
            attempt_input=attempt_input,
            outcome=_QueryTurnOutcome(),
            retry_state=retry_state,
            attempt_state=attempt_state,
        ):
            pass

    assert get_current_trace().skill_detector is detector
    assert get_current_trace().enabled_skills == ["xlsx"]
    fake_agent.setup_skill_detector.assert_not_awaited()
    set_current_trace(None)


@pytest.mark.asyncio
async def test_query_handler_user_prompt_hook_blocks_before_command_dispatch(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value={}),
        mutate_session_state=AsyncMock(return_value={}),
    )
    setattr(runner, "_chat_manager", None)
    tenant_hooks = HookConfig(
        enabled=True,
        events={
            HookEventName.USER_PROMPT_SUBMIT: [
                HookMatcherGroupConfig(
                    hooks=[
                        CommandHookHandlerConfig(
                            id="blocker",
                            command="unused",
                        ),
                    ],
                ),
            ],
        },
    )

    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: tenant_hooks,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        AsyncMock(
            return_value=MergedHookResult(
                decision=HookDecision.BLOCK,
                reason="blocked prompt",
            ),
        ),
    )
    command_path = AsyncMock()
    monkeypatch.setattr("swe.app.runner.runner.run_command_path", command_path)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="/history")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert outputs[-1][1] is True
    assert "blocked prompt" in outputs[-1][0].get_text_content()
    command_path.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_handler_no_config_does_not_emit_hook(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value={}),
        mutate_session_state=AsyncMock(return_value={}),
    )
    setattr(runner, "_chat_manager", None)

    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(),
    )
    emit_hook = AsyncMock(return_value=MergedHookResult())
    monkeypatch.setattr("swe.app.runner.runner._emit_runner_hook", emit_hook)

    async def fake_run_command_path(request, msgs, runner):
        yield Msg(name="Friday", role="assistant", content="command"), True

    monkeypatch.setattr(
        "swe.app.runner.runner.run_command_path",
        fake_run_command_path,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="/history")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert outputs[-1][0].get_text_content() == "command"
    emit_hook.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_handler_loads_session_skill_hooks_for_media_message(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._resolve_active_model_label",
        lambda *args, **kwargs: "openai/gpt-test",
    )
    emit_hook = AsyncMock(return_value=MergedHookResult())
    monkeypatch.setattr("swe.app.runner.runner._emit_runner_hook", emit_hook)

    persisted_overlay = HookSessionState(
        loaded_skill_sources=[
            LoadedSkillHookSource(
                source_id="skill:xlsx",
                skill_name="xlsx",
                skill_root=str(tmp_path / "skills" / "xlsx"),
                source_path=str(
                    tmp_path / "skills" / "xlsx" / "hooks" / "hooks.json",
                ),
                hook_config=HookConfig(
                    enabled=True,
                    events={
                        HookEventName.STOP: [
                            HookMatcherGroupConfig(
                                hooks=[
                                    CommandHookHandlerConfig(
                                        id="skill:xlsx:stop",
                                        command="unused",
                                    ),
                                ],
                            ),
                        ],
                    },
                ),
            ),
        ],
    )
    await runner.session.save_merged_state(
        session_id="session-1",
        user_id="user-1",
        state={
            "hook_overlay": persisted_overlay.model_dump(
                mode="json",
                by_alias=True,
            ),
        },
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[{"type": "image", "url": "file:///tmp/image.png"}],
        ),
    ]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert outputs[-1][0].get_text_content() == "agent reply"
    emitted_events = [call.args[0] for call in emit_hook.await_args_list]
    assert HookEventName.USER_PROMPT_SUBMIT not in emitted_events
    assert emitted_events == [
        HookEventName.SESSION_START,
        HookEventName.BEFORE_STOP,
        HookEventName.STOP,
    ]


@pytest.mark.asyncio
async def test_user_prompt_hook_conversation_snapshot_uses_persisted_memory(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(
            HookConfig(
                enabled=True,
                events={
                    HookEventName.USER_PROMPT_SUBMIT: [
                        HookMatcherGroupConfig(
                            hooks=[
                                CommandHookHandlerConfig(
                                    id="prompt-policy",
                                    command="unused",
                                    includeConversationSnapshot=True,
                                ),
                            ],
                        ),
                    ],
                },
            ),
        ),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(),
    )
    seen_payloads: list[dict] = []

    async def fake_execute_handler_result(handler, context, *, workspace_dir):
        del workspace_dir
        seen_payloads.append(context.to_handler_payload())
        from swe.agents.hook_runtime.models import HookHandlerResult

        return HookHandlerResult(handler_id=handler.id, order=0)

    monkeypatch.setattr(
        "swe.agents.hook_runtime.runtime.execute_handler",
        fake_execute_handler_result,
    )
    await runner.session.save_merged_state(
        session_id="session-1",
        user_id="user-1",
        state={
            "agent": {
                "memory": {
                    "content": [
                        [
                            Msg(
                                name="user",
                                role="user",
                                content="previous question",
                            ).to_dict(),
                            [],
                        ],
                        [
                            Msg(
                                name="Friday",
                                role="assistant",
                                content="previous answer",
                            ).to_dict(),
                            [],
                        ],
                    ],
                },
            },
        },
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="next question")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert outputs[-1][0].get_text_content() == "agent reply"
    assert seen_payloads[0]["hook_event_name"] == "UserPromptSubmit"
    assert seen_payloads[0]["conversation_snapshot"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "previous question"}],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "previous answer"}],
        },
    ]
    assert seen_payloads[0]["conversation_snapshot_meta"] == {
        "included_messages": 2,
        "omitted_messages": 0,
        "limit": 50,
        "reasoning_omitted": False,
        "media_content_omitted": False,
    }


@pytest.mark.asyncio
async def test_query_handler_injects_prompt_additional_context(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._resolve_active_model_label",
        lambda *args, **kwargs: "openai/gpt-test",
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        AsyncMock(
            side_effect=[
                MergedHookResult(
                    session_title="Hooked",
                    additional_context=[
                        AdditionalContext(
                            handler_id="prompt",
                            context="prompt context",
                        ),
                    ],
                ),
                MergedHookResult(
                    additional_context=[
                        AdditionalContext(
                            handler_id="start",
                            context="start context",
                        ),
                    ],
                ),
                MergedHookResult(),
                MergedHookResult(),
            ],
        ),
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert outputs[-1][0].get_text_content() == "agent reply"
    assert request.channel_meta["session_title"] == "Hooked"
    assert "prompt context" in _FakeAgent.last_env_context
    assert "start context" in _FakeAgent.last_env_context


@pytest.mark.asyncio
async def test_query_handler_session_start_block_yields_before_cleanup(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    chat = SimpleNamespace(id="chat-1")
    chat_manager = SimpleNamespace(
        get_or_create_chat=AsyncMock(return_value=chat),
        update_chat=AsyncMock(return_value=chat),
    )
    setattr(runner, "_chat_manager", chat_manager)

    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def slow_cleanup(clients):
        assert clients == ["mcp-client"]
        cleanup_started.set()
        await cleanup_release.wait()

    monkeypatch.setattr(
        "swe.app.runner.runner._build_and_connect_mcp_clients",
        AsyncMock(return_value=["mcp-client"]),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._cleanup_mcp_clients",
        slow_cleanup,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner.build_env_context",
        lambda **kwargs: "base context",
    )
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._resolve_active_model_label",
        lambda *args, **kwargs: "openai/gpt-test",
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        AsyncMock(
            side_effect=[
                MergedHookResult(),
                MergedHookResult(
                    decision=HookDecision.BLOCK,
                    reason="session start blocked",
                ),
            ],
        ),
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]
    stream = runner.query_handler(msgs, request=request)
    next_item = asyncio.create_task(anext(stream))

    try:
        done, _pending = await asyncio.wait({next_item}, timeout=0.05)
        assert next_item in done
        msg, last = next_item.result()
        assert last is True
        assert msg.get_text_content() == "session start blocked"
        assert not cleanup_started.is_set()

        close_task = asyncio.create_task(stream.aclose())
        await asyncio.wait_for(cleanup_started.wait(), timeout=0.5)
        chat_manager.update_chat.assert_awaited_once_with(chat)
        cleanup_release.set()
        await asyncio.wait_for(close_task, timeout=0.5)
    finally:
        cleanup_release.set()
        if not next_item.done():
            next_item.cancel()
            await asyncio.gather(next_item, return_exceptions=True)


def test_resolve_active_model_label_prefers_scoped_override(monkeypatch):
    from swe.app.crons import model_slot_context
    from swe.providers.models import ModelSlotConfig
    from swe.app.runner.runner import _resolve_active_model_label

    monkeypatch.setattr(
        model_slot_context,
        "get_current_model_slot_override",
        lambda: ModelSlotConfig(
            provider_id="openai",
            model="gpt-5.4",
        ),
    )
    provider_manager = SimpleNamespace(
        get_active_model=lambda: ModelSlotConfig(
            provider_id="anthropic",
            model="claude-3-7-sonnet",
        ),
    )
    monkeypatch.setattr(
        "swe.providers.provider_manager.ProviderManager.get_instance",
        lambda _tenant_id: provider_manager,
    )

    assert _resolve_active_model_label("tenant-a") == "openai/gpt-5.4"


@pytest.mark.asyncio
async def test_build_and_connect_mcp_clients_logs_duration(
    monkeypatch,
) -> None:
    import swe.app.runner.runner as runner_module

    class FakeClient:
        async def connect(self, timeout: float = 30.0):
            del timeout
            return None

    fake_client = FakeClient()
    monkeypatch.setattr(
        "swe.app.runner.runner._create_mcp_client_with_headers",
        AsyncMock(return_value=fake_client),
    )

    config = SimpleNamespace(
        clients={
            "weather": SimpleNamespace(enabled=True),
        },
    )
    with patch.object(runner_module.logger, "debug") as mock_debug:
        clients = await _build_and_connect_mcp_clients(config)

    assert clients == [fake_client]
    assert any(
        call.args
        and "mcp_client_connect_duration_ms=" in call.args[0]
        and call.args[2] == 1
        for call in mock_debug.call_args_list
    )


@pytest.mark.asyncio
async def test_build_and_connect_mcp_clients_passes_explicit_connect_timeout(
    monkeypatch,
) -> None:
    import swe.app.runner.runner as runner_module

    captured: dict[str, float] = {}

    class FakeClient:
        async def connect(self, timeout: float = 30.0):
            captured["timeout"] = timeout

    fake_client = FakeClient()
    monkeypatch.setattr(
        "swe.app.runner.runner._create_mcp_client_with_headers",
        AsyncMock(return_value=fake_client),
    )

    config = SimpleNamespace(
        clients={
            "weather": SimpleNamespace(enabled=True),
        },
    )

    clients = await _build_and_connect_mcp_clients(config)

    assert clients == [fake_client]
    assert captured["timeout"] == runner_module._MCP_CONNECT_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_prepare_query_runtime_logs_agent_build_duration(
    monkeypatch,
    tmp_path,
) -> None:
    import swe.app.runner.runner as runner_module

    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    chat = SimpleNamespace(id="chat-1")
    setattr(
        runner,
        "_chat_manager",
        SimpleNamespace(
            get_or_create_chat=AsyncMock(return_value=chat),
        ),
    )
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._resolve_active_model_label",
        lambda *args, **kwargs: "openai/gpt-test",
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        AsyncMock(return_value=MergedHookResult()),
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    with patch.object(runner_module.logger, "debug") as mock_debug:
        result = await runner._prepare_query_runtime(
            request=request,
            msgs=msgs,
            query="hello",
            preflight=_QueryPreflight(),
        )

    assert result.runtime is not None
    assert any(
        call.args
        and "swe_agent_build_duration_ms=" in call.args[0]
        and call.args[2] == "test-agent"
        for call in mock_debug.call_args_list
    )


@pytest.mark.asyncio
async def test_query_handler_before_stop_allow_emits_stop_and_completes(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )
    emit_hook = AsyncMock()

    async def fake_emit_runner_hook(event_name, **kwargs):
        await emit_hook(event_name, **kwargs)
        if event_name == HookEventName.BEFORE_STOP:
            assert kwargs["assistant_response"] == "agent reply"
            return MergedHookResult(
                decision=HookDecision.ALLOW,
                reason="completion approved",
            )
        return MergedHookResult()

    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        fake_emit_runner_hook,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert [item[0].get_text_content() for item in outputs] == [
        "agent reply",
    ]
    assert [call.args[0] for call in emit_hook.await_args_list] == [
        HookEventName.USER_PROMPT_SUBMIT,
        HookEventName.SESSION_START,
        HookEventName.BEFORE_STOP,
        HookEventName.STOP,
    ]


@pytest.mark.asyncio
async def test_query_handler_before_stop_block_continues_without_stop(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )
    before_stop_calls = 0
    stop_calls = 0

    async def fake_emit_runner_hook(event_name, **kwargs):
        nonlocal before_stop_calls, stop_calls
        if event_name == HookEventName.BEFORE_STOP:
            before_stop_calls += 1
            if before_stop_calls == 1:
                return MergedHookResult(
                    decision=HookDecision.BLOCK,
                    reason="test tests before stopping",
                )
            return MergedHookResult(
                decision=HookDecision.ALLOW,
                reason="completion approved",
            )
        if event_name == HookEventName.STOP:
            stop_calls += 1
        return MergedHookResult()

    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        fake_emit_runner_hook,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert [item[0].get_text_content() for item in outputs] == [
        "agent reply",
        "agent reply",
    ]
    assert before_stop_calls == 2
    assert stop_calls == 1


@pytest.mark.asyncio
async def test_query_handler_before_stop_block_exhausts_default_budget(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )
    before_stop_calls = 0

    async def fake_emit_runner_hook(event_name, **kwargs):
        nonlocal before_stop_calls
        if event_name == HookEventName.BEFORE_STOP:
            before_stop_calls += 1
            return MergedHookResult(
                decision=HookDecision.BLOCK,
                reason=f"reason-{before_stop_calls}",
            )
        return MergedHookResult()

    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        fake_emit_runner_hook,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]
    output_texts = [item[0].get_text_content() for item in outputs]

    assert output_texts[:3] == ["agent reply", "agent reply", "agent reply"]
    assert "任务未完成" in output_texts[-1]
    assert "reason-3" in output_texts[-1]
    assert before_stop_calls == 3


@pytest.mark.asyncio
async def test_query_handler_before_stop_budget_exhaustion_finalizes_trace(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )
    runner._generate_backend_suggestions_if_needed = AsyncMock()
    runner._index_model_output_if_needed = AsyncMock()
    runner._end_trace_if_needed = AsyncMock()

    async def fake_emit_runner_hook(event_name, **kwargs):
        if event_name == HookEventName.BEFORE_STOP:
            return MergedHookResult(
                decision=HookDecision.BLOCK,
                reason="still incomplete",
            )
        return MergedHookResult()

    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        fake_emit_runner_hook,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert "任务未完成" in outputs[-1][0].get_text_content()
    runner._generate_backend_suggestions_if_needed.assert_not_awaited()
    runner._index_model_output_if_needed.assert_awaited_once()
    runner._end_trace_if_needed.assert_awaited_once()


@pytest.mark.asyncio
async def test_query_handler_before_stop_budget_exhaustion_persists_notice(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )

    async def fake_emit_runner_hook(event_name, **kwargs):
        if event_name == HookEventName.BEFORE_STOP:
            return MergedHookResult(
                decision=HookDecision.BLOCK,
                reason="still incomplete",
            )
        return MergedHookResult()

    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        fake_emit_runner_hook,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]
    notice_text = outputs[-1][0].get_text_content()
    stored_state = await runner.session.get_session_state_dict(
        session_id="session-1",
        user_id="user-1",
    )
    stored_content = stored_state["agent"]["memory"]["content"]
    stored_texts = [entry[0]["content"] for entry in stored_content]

    assert "任务未完成" in notice_text
    assert stored_texts[-1] == notice_text


@pytest.mark.asyncio
async def test_query_handler_before_stop_defers_completion_side_effects(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )
    runner._generate_backend_suggestions_if_needed = AsyncMock()
    runner._index_model_output_if_needed = AsyncMock()
    runner._end_trace_if_needed = AsyncMock()
    before_stop_calls = 0

    async def fake_emit_runner_hook(event_name, **kwargs):
        nonlocal before_stop_calls
        if event_name == HookEventName.BEFORE_STOP:
            before_stop_calls += 1
            if before_stop_calls == 1:
                runner._generate_backend_suggestions_if_needed.assert_not_awaited()
                runner._index_model_output_if_needed.assert_not_awaited()
                runner._end_trace_if_needed.assert_not_awaited()
                return MergedHookResult(
                    decision=HookDecision.BLOCK,
                    reason="run checks first",
                )
            return MergedHookResult(decision=HookDecision.ALLOW, reason="ok")
        return MergedHookResult()

    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        fake_emit_runner_hook,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert [item[0].get_text_content() for item in outputs] == [
        "agent reply",
        "agent reply",
    ]
    runner._generate_backend_suggestions_if_needed.assert_awaited_once()
    runner._index_model_output_if_needed.assert_awaited_once()
    runner._end_trace_if_needed.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_single_query_attempt_ends_trace_when_runtime_blocked(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner._prepare_query_runtime = AsyncMock(
        return_value=_RuntimeStartResult(
            block_response=Msg(
                name="Friday",
                role="assistant",
                content="blocked",
            ),
        ),
    )
    runner._end_trace_if_needed = AsyncMock()

    attempt_input = _QueryAttemptInput(
        request=SimpleNamespace(),
        msgs=[],
        query="hello",
        preflight=_QueryPreflight(),
        trace_id="trace-blocked",
    )
    outcome = _QueryTurnOutcome()
    retry_state = _RetryState()
    attempt_state = _QueryAttemptState()

    outputs = [
        item
        async for item in runner._stream_single_query_attempt(
            attempt_input=attempt_input,
            outcome=outcome,
            retry_state=retry_state,
            attempt_state=attempt_state,
        )
    ]

    assert [item[0].get_text_content() for item in outputs] == ["blocked"]
    assert attempt_state.should_return is True
    runner._end_trace_if_needed.assert_awaited_once_with(
        "trace-blocked",
        "completed",
    )


@pytest.mark.asyncio
async def test_query_handler_aggregate_budget_counts_before_stop_only(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    agent_config = _agent_config(HookConfig(enabled=True))
    agent_config.running.max_before_stop_turns = 2
    agent_config.running.max_automatic_follow_up_turns = 2
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: agent_config,
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )
    before_stop_calls = 0

    async def fake_emit_runner_hook(event_name, **kwargs):
        nonlocal before_stop_calls
        if event_name == HookEventName.BEFORE_STOP:
            before_stop_calls += 1
            return MergedHookResult(
                decision=HookDecision.BLOCK,
                reason=f"gate-{before_stop_calls}",
            )
        return MergedHookResult()

    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        fake_emit_runner_hook,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]
    output_texts = [item[0].get_text_content() for item in outputs]

    assert output_texts == [
        "agent reply",
        "agent reply",
        "agent reply",
        output_texts[-1],
    ]
    assert "任务未完成" in output_texts[-1]
    assert "gate-3" in output_texts[-1]
    assert before_stop_calls == 3


@pytest.mark.asyncio
async def test_emit_before_stop_hook_respects_active_guard(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    runtime = _QueryRuntime(
        agent=_FakeAgent(),
        agent_config=_agent_config(
            HookConfig(
                enabled=True,
                events={
                    HookEventName.BEFORE_STOP: [
                        HookMatcherGroupConfig(
                            hooks=[
                                CommandHookHandlerConfig(
                                    id="policy",
                                    command="unused",
                                ),
                            ],
                        ),
                    ],
                },
            ),
        ),
        tenant_hooks=HookConfig(enabled=True),
        hook_overlay=HookSessionOverlay(),
        chat=SimpleNamespace(id="chat-1"),
        session_skill_detector=None,
        mcp_clients=[],
        session_id="session-1",
        user_id="user-1",
        channel="console",
        skip_history=False,
        pending_confirmed_skill_snapshots={},
    )
    plan = _TurnPlan(
        original_user_message="hello",
        turn_msgs=[],
    )
    outcome = _QueryTurnOutcome(
        assistant_response="agent reply",
        stop_hook_active=True,
    )
    emit_hook = AsyncMock()
    monkeypatch.setattr("swe.app.runner.runner._emit_runner_hook", emit_hook)

    result = await runner._emit_before_stop_hook_if_needed(
        request=SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            channel_meta={},
        ),
        runtime=runtime,
        plan=plan,
        outcome=outcome,
    )

    assert result is None
    emit_hook.assert_not_awaited()


@pytest.mark.asyncio
async def test_before_stop_hook_conversation_snapshot_uses_live_memory(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    agent = _FakeAgent()
    await agent.memory.add(Msg(name="user", role="user", content="hello"))
    await agent.memory.add(
        Msg(
            name="Friday",
            role="assistant",
            content=[
                {"type": "thinking", "thinking": "hidden"},
                {"type": "text", "text": "visible"},
            ],
        ),
    )
    runtime = _QueryRuntime(
        agent=agent,
        agent_config=_agent_config(
            HookConfig(
                enabled=True,
                events={
                    HookEventName.BEFORE_STOP: [
                        HookMatcherGroupConfig(
                            hooks=[
                                CommandHookHandlerConfig(
                                    id="policy",
                                    command="unused",
                                    includeConversationSnapshot=True,
                                ),
                            ],
                        ),
                    ],
                },
            ),
        ),
        tenant_hooks=HookConfig(),
        hook_overlay=HookSessionOverlay(),
        chat=SimpleNamespace(id="chat-1"),
        session_skill_detector=None,
        mcp_clients=[],
        session_id="session-1",
        user_id="user-1",
        channel="console",
        skip_history=False,
        pending_confirmed_skill_snapshots={},
    )
    plan = _TurnPlan(original_user_message="hello", turn_msgs=[])
    outcome = _QueryTurnOutcome(assistant_response="agent reply")
    seen_payloads: list[dict] = []

    async def fake_execute_handler_result(handler, context, *, workspace_dir):
        del workspace_dir
        seen_payloads.append(context.to_handler_payload())
        from swe.agents.hook_runtime.models import HookHandlerResult

        return HookHandlerResult(handler_id=handler.id, order=0)

    monkeypatch.setattr(
        "swe.agents.hook_runtime.runtime.execute_handler",
        fake_execute_handler_result,
    )

    await runner._emit_before_stop_hook_if_needed(
        request=SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            channel_meta={},
        ),
        runtime=runtime,
        plan=plan,
        outcome=outcome,
    )

    assert seen_payloads[0]["conversation_snapshot"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "hello"}],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "visible"}],
        },
    ]


@pytest.mark.asyncio
async def test_before_stop_hook_conversation_snapshot_does_not_fall_back_to_stale_persisted_memory(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    await runner.session.save_merged_state(
        session_id="session-1",
        user_id="user-1",
        state={
            "agent": {
                "memory": {
                    "content": [
                        [
                            Msg(
                                name="user",
                                role="user",
                                content="stale question",
                            ).to_dict(),
                            [],
                        ],
                    ],
                },
            },
        },
    )
    seen_payloads: list[dict] = []

    async def fake_execute_handler_result(handler, context, *, workspace_dir):
        del workspace_dir
        seen_payloads.append(context.to_handler_payload())
        from swe.agents.hook_runtime.models import HookHandlerResult

        return HookHandlerResult(handler_id=handler.id, order=0)

    monkeypatch.setattr(
        "swe.agents.hook_runtime.runtime.execute_handler",
        fake_execute_handler_result,
    )

    await _emit_runner_hook(
        HookEventName.BEFORE_STOP,
        request=SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            channel_meta={},
        ),
        runner=runner,
        tenant_hooks=HookConfig(),
        agent_config=_agent_config(
            HookConfig(
                enabled=True,
                events={
                    HookEventName.BEFORE_STOP: [
                        HookMatcherGroupConfig(
                            hooks=[
                                CommandHookHandlerConfig(
                                    id="policy",
                                    command="unused",
                                    includeConversationSnapshot=True,
                                ),
                            ],
                        ),
                    ],
                },
            ),
        ),
        overlay=HookSessionOverlay(),
        prompt="current question",
        assistant_response="current answer",
        agent=SimpleNamespace(memory=SimpleNamespace()),
    )

    assert seen_payloads[0]["conversation_snapshot"] == []
    assert seen_payloads[0]["conversation_snapshot_meta"] == {
        "included_messages": 0,
        "omitted_messages": 0,
        "limit": 50,
        "unavailable": True,
        "unavailable_reason": "agent_memory_unavailable",
    }


@pytest.mark.asyncio
async def test_runner_hook_conversation_snapshot_unavailable_without_agent(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    seen_payloads: list[dict] = []

    async def fake_execute_handler_result(handler, context, *, workspace_dir):
        del workspace_dir
        seen_payloads.append(context.to_handler_payload())
        from swe.agents.hook_runtime.models import HookHandlerResult

        return HookHandlerResult(handler_id=handler.id, order=0)

    monkeypatch.setattr(
        "swe.agents.hook_runtime.runtime.execute_handler",
        fake_execute_handler_result,
    )

    await _emit_runner_hook(
        HookEventName.SESSION_START,
        request=SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            channel_meta={},
        ),
        runner=runner,
        tenant_hooks=HookConfig(),
        agent_config=_agent_config(
            HookConfig(
                enabled=True,
                events={
                    HookEventName.SESSION_START: [
                        HookMatcherGroupConfig(
                            hooks=[
                                CommandHookHandlerConfig(
                                    id="policy",
                                    command="unused",
                                    includeConversationSnapshot=True,
                                ),
                            ],
                        ),
                    ],
                },
            ),
        ),
        overlay=HookSessionOverlay(),
        source="startup",
    )

    assert seen_payloads[0]["conversation_snapshot"] == []
    assert seen_payloads[0]["conversation_snapshot_meta"] == {
        "included_messages": 0,
        "omitted_messages": 0,
        "limit": 50,
        "unavailable": True,
        "unavailable_reason": "agent_memory_unavailable",
    }


@pytest.mark.asyncio
async def test_session_start_hook_conversation_snapshot_uses_persisted_memory(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    await runner.session.save_merged_state(
        session_id="session-1",
        user_id="user-1",
        state={
            "agent": {
                "memory": {
                    "content": [
                        [
                            Msg(
                                name="user",
                                role="user",
                                content="resumed question",
                            ).to_dict(),
                            [],
                        ],
                        [
                            Msg(
                                name="Friday",
                                role="assistant",
                                content="resumed answer",
                            ).to_dict(),
                            [],
                        ],
                    ],
                },
            },
        },
    )
    seen_payloads: list[dict] = []

    async def fake_execute_handler_result(handler, context, *, workspace_dir):
        del workspace_dir
        seen_payloads.append(context.to_handler_payload())
        from swe.agents.hook_runtime.models import HookHandlerResult

        return HookHandlerResult(handler_id=handler.id, order=0)

    monkeypatch.setattr(
        "swe.agents.hook_runtime.runtime.execute_handler",
        fake_execute_handler_result,
    )

    await _emit_runner_hook(
        HookEventName.SESSION_START,
        request=SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            channel_meta={},
        ),
        runner=runner,
        tenant_hooks=HookConfig(),
        agent_config=_agent_config(
            HookConfig(
                enabled=True,
                events={
                    HookEventName.SESSION_START: [
                        HookMatcherGroupConfig(
                            hooks=[
                                CommandHookHandlerConfig(
                                    id="policy",
                                    command="unused",
                                    includeConversationSnapshot=True,
                                ),
                            ],
                        ),
                    ],
                },
            ),
        ),
        overlay=HookSessionOverlay(),
        source="startup",
    )

    assert seen_payloads[0]["hook_event_name"] == "SessionStart"
    assert seen_payloads[0]["conversation_snapshot"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "resumed question"}],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "resumed answer"}],
        },
    ]
    assert seen_payloads[0]["conversation_snapshot_meta"] == {
        "included_messages": 2,
        "omitted_messages": 0,
        "limit": 50,
        "reasoning_omitted": False,
        "media_content_omitted": False,
    }


@pytest.mark.asyncio
async def test_query_handler_stop_hook_blocks_completion(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )
    emit_hook = AsyncMock(
        side_effect=[
            MergedHookResult(),
            MergedHookResult(),
            MergedHookResult(),
            MergedHookResult(
                decision=HookDecision.BLOCK,
                reason="stop blocked",
            ),
        ],
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        emit_hook,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert [item[0].get_text_content() for item in outputs] == [
        "agent reply",
        "stop blocked",
    ]
    stop_call = emit_hook.await_args_list[-1]
    assert stop_call.args[0] == HookEventName.STOP
    assert stop_call.kwargs["assistant_response"] == "agent reply"


@pytest.mark.asyncio
async def test_query_handler_persists_mutated_hook_overlay(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(HookConfig(enabled=True)),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(enabled=True),
    )

    async def fake_emit_runner_hook(*args, **kwargs):
        kwargs["overlay"].once_executed[
            "default:user-1:session-1:PreToolUse:once"
        ] = True
        return MergedHookResult()

    monkeypatch.setattr(
        "swe.app.runner.runner._emit_runner_hook",
        fake_emit_runner_hook,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="hello")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]
    state = await runner.session.get_session_state_dict(
        session_id="session-1",
        user_id="user-1",
    )

    assert outputs[-1][0].get_text_content() == "agent reply"
    assert state["hook_overlay"]["once_executed"] == {
        "default:user-1:session-1:PreToolUse:once": True,
    }


@pytest.mark.asyncio
async def test_query_handler_ends_request_skill_detector_in_finally(
    monkeypatch,
    tmp_path,
) -> None:
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    runner.session = SafeJSONSession(save_dir=str(tmp_path))
    setattr(runner, "_chat_manager", None)
    _patch_normal_agent_path(monkeypatch)
    monkeypatch.setattr(
        "swe.app.runner.runner.load_agent_config",
        lambda *args, **kwargs: _agent_config(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._load_tenant_hook_config",
        lambda *args, **kwargs: HookConfig(),
    )

    detector = SimpleNamespace(
        detect_from_user_message=lambda _message: ("xlsx", 0.9),
        start_skill=AsyncMock(),
        on_reasoning_end=AsyncMock(),
    )
    monkeypatch.setattr(
        "swe.app.runner.runner._create_session_skill_detector",
        lambda **kwargs: detector,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )
    msgs = [Msg(name="user", role="user", content="use xlsx")]

    outputs = [
        item async for item in runner.query_handler(msgs, request=request)
    ]

    assert outputs[-1][0].get_text_content() == "agent reply"
    detector.start_skill.assert_awaited_once()
    detector.on_reasoning_end.assert_awaited_once()
