# -*- coding: utf-8 -*-
"""Tests for tenant-local agent scoped LLM rate limiter state."""

import asyncio

import pytest
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from swe.providers.rate_limiter import (
    RateLimiterScopeKey,
    cleanup_idle_rate_limiters,
    get_rate_limiter,
    reset_rate_limiter,
)
from swe.providers.retry_chat_model import (
    EmptyModelOutputError,
    RateLimitConfig,
    RetryChatModel,
    RetryConfig,
)
from swe.config.llm_workload import (
    LLM_WORKLOAD_CHAT,
    LLM_WORKLOAD_CRON,
    bind_llm_workload,
)


class _StaticChatModel(ChatModelBase):
    def __init__(self):
        super().__init__(model_name="test-model", stream=False)

    async def __call__(self, *args, **kwargs):
        return ChatResponse(content=[{"type": "text", "text": "ok"}])


class _SequenceChatModel(ChatModelBase):
    def __init__(self, responses):
        super().__init__(model_name="test-model", stream=False)
        self.responses = list(responses)
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if not self.responses:
            raise AssertionError("sequence model has no response left")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _TransientServerError(RuntimeError):
    status_code = 500


class _BlockingStreamChatModel(ChatModelBase):
    def __init__(self, release_second_chunk: asyncio.Event):
        super().__init__(model_name="test-model", stream=True)
        self._release_second_chunk = release_second_chunk

    async def __call__(self, *args, **kwargs):
        async def _stream():
            yield ChatResponse(content=[])
            await self._release_second_chunk.wait()
            yield ChatResponse(content=[])

        return _stream()


class _SequenceStreamChatModel(ChatModelBase):
    def __init__(self, streams):
        super().__init__(model_name="test-model", stream=True)
        self.streams = list(streams)
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if not self.streams:
            raise AssertionError("sequence stream model has no stream left")
        chunks = self.streams.pop(0)
        if isinstance(chunks, Exception):
            raise chunks

        async def _stream():
            for chunk in chunks:
                yield chunk

        return _stream()


@pytest.fixture(autouse=True)
def _reset_limiter_registry():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


def test_rate_limit_config_uses_workload_defaults_for_none_concurrency():
    config = RateLimitConfig(
        max_concurrent=7,
        chat_max_concurrent=None,
        cron_max_concurrent=None,
    )

    assert config.max_concurrent_for(LLM_WORKLOAD_CHAT) == 2
    assert config.max_concurrent_for(LLM_WORKLOAD_CRON) == 3


@pytest.mark.asyncio
async def test_same_tenant_same_agent_shares_limiter_state():
    scope = RateLimiterScopeKey("tenant-a", "agent-x")

    first = await get_rate_limiter(
        scope_key=scope,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    second = await get_rate_limiter(
        scope_key=scope,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    assert second is first


@pytest.mark.asyncio
async def test_same_tenant_different_agents_do_not_share_limiter_state():
    agent_x = await get_rate_limiter(
        scope_key=RateLimiterScopeKey("tenant-a", "agent-x"),
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    agent_y = await get_rate_limiter(
        scope_key=RateLimiterScopeKey("tenant-a", "agent-y"),
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    assert agent_y is not agent_x


@pytest.mark.asyncio
async def test_different_tenants_same_agent_do_not_share_limiter_state():
    tenant_a = await get_rate_limiter(
        scope_key=RateLimiterScopeKey("tenant-a", "default"),
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    tenant_b = await get_rate_limiter(
        scope_key=RateLimiterScopeKey("tenant-b", "default"),
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    assert tenant_b is not tenant_a


@pytest.mark.asyncio
async def test_rate_limit_cooldown_stays_inside_agent_scope():
    agent_x = await get_rate_limiter(
        scope_key=RateLimiterScopeKey("tenant-a", "agent-x"),
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    agent_y = await get_rate_limiter(
        scope_key=RateLimiterScopeKey("tenant-a", "agent-y"),
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    await agent_x.report_rate_limit(retry_after=60.0)

    assert agent_x.stats()["is_paused"] is True
    assert agent_y.stats()["is_paused"] is False


@pytest.mark.asyncio
async def test_chat_and_cron_use_independent_concurrency_pools():
    scope = RateLimiterScopeKey("tenant-a", "agent-x")
    chat = await get_rate_limiter(
        scope_key=scope,
        workload=LLM_WORKLOAD_CHAT,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    cron = await get_rate_limiter(
        scope_key=scope,
        workload=LLM_WORKLOAD_CRON,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    await chat.acquire()
    try:
        await asyncio.wait_for(cron.acquire(), timeout=0.05)
        cron.release()

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(chat.acquire(), timeout=0.05)
    finally:
        chat.release()


@pytest.mark.asyncio
async def test_qpm_window_is_shared_across_chat_and_cron_workloads():
    scope = RateLimiterScopeKey("tenant-a", "agent-x")
    chat = await get_rate_limiter(
        scope_key=scope,
        workload=LLM_WORKLOAD_CHAT,
        max_concurrent=1,
        max_qpm=1,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    await chat.acquire()
    chat.release()

    cron = await get_rate_limiter(
        scope_key=scope,
        workload=LLM_WORKLOAD_CRON,
        max_concurrent=1,
        max_qpm=1,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(cron.acquire(), timeout=0.05)


@pytest.mark.asyncio
async def test_rate_limit_cooldown_is_shared_across_workloads_same_agent():
    scope = RateLimiterScopeKey("tenant-a", "agent-x")
    cron = await get_rate_limiter(
        scope_key=scope,
        workload=LLM_WORKLOAD_CRON,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    chat = await get_rate_limiter(
        scope_key=scope,
        workload=LLM_WORKLOAD_CHAT,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    other_agent = await get_rate_limiter(
        scope_key=RateLimiterScopeKey("tenant-a", "agent-y"),
        workload=LLM_WORKLOAD_CHAT,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    await cron.report_rate_limit(retry_after=60.0)

    assert chat.stats()["is_paused"] is True
    assert other_agent.stats()["is_paused"] is False


@pytest.mark.asyncio
async def test_config_change_replaces_later_limiter_without_interrupting_old():
    scope = RateLimiterScopeKey("tenant-a", "agent-x")
    old_limiter = await get_rate_limiter(
        scope_key=scope,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    await old_limiter.acquire()

    new_limiter = await get_rate_limiter(
        scope_key=scope,
        max_concurrent=3,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    assert new_limiter is not old_limiter
    assert old_limiter.stats()["current_in_flight"] == 1
    assert new_limiter.stats()["max_concurrent"] == 3
    assert new_limiter.stats()["current_in_flight"] == 0

    old_limiter.release()


@pytest.mark.asyncio
async def test_cleanup_removes_only_idle_entries():
    idle_scope = RateLimiterScopeKey("tenant-a", "idle-agent")
    busy_scope = RateLimiterScopeKey("tenant-a", "busy-agent")

    await get_rate_limiter(scope_key=idle_scope, max_concurrent=1)
    busy_limiter = await get_rate_limiter(
        scope_key=busy_scope,
        max_concurrent=1,
    )
    await busy_limiter.acquire()

    removed = cleanup_idle_rate_limiters(max_idle_seconds=0)
    same_busy_limiter = await get_rate_limiter(
        scope_key=busy_scope,
        max_concurrent=1,
    )
    new_idle_limiter = await get_rate_limiter(
        scope_key=idle_scope,
        max_concurrent=1,
    )

    assert removed == 1
    assert same_busy_limiter is busy_limiter
    assert new_idle_limiter is not busy_limiter

    busy_limiter.release()


@pytest.mark.asyncio
async def test_cleanup_keeps_paused_limiter_state():
    scope = RateLimiterScopeKey("tenant-a", "paused-agent")
    limiter = await get_rate_limiter(
        scope_key=scope,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    await limiter.report_rate_limit(retry_after=60.0)

    removed = cleanup_idle_rate_limiters(max_idle_seconds=0)
    same_limiter = await get_rate_limiter(
        scope_key=scope,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    assert removed == 0
    assert same_limiter is limiter
    assert same_limiter.stats()["is_paused"] is True


@pytest.mark.asyncio
async def test_cleanup_keeps_recent_qpm_window_state():
    scope = RateLimiterScopeKey("tenant-a", "qpm-agent")
    limiter = await get_rate_limiter(
        scope_key=scope,
        max_concurrent=1,
        max_qpm=1,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    await limiter.acquire()
    limiter.release()

    removed = cleanup_idle_rate_limiters(max_idle_seconds=0)
    same_limiter = await get_rate_limiter(
        scope_key=scope,
        max_concurrent=1,
        max_qpm=1,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    assert removed == 0
    assert same_limiter is limiter
    assert same_limiter.stats()["requests_last_60s"] == 1


@pytest.mark.asyncio
async def test_retry_chat_model_without_explicit_scope_uses_current_agent(
    monkeypatch,
):
    resolve_calls: list[tuple[object, str | None, str | None]] = []

    def _resolve_scope(scope_key=None, tenant_id=None, agent_id=None):
        resolve_calls.append((scope_key, tenant_id, agent_id))
        return RateLimiterScopeKey("tenant-a", "agent-x")

    monkeypatch.setattr(
        "swe.providers.retry_chat_model.resolve_rate_limiter_scope",
        _resolve_scope,
    )

    model = RetryChatModel(
        _StaticChatModel(),
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            chat_max_concurrent=1,
            max_qpm=0,
            pause_seconds=10.0,
            jitter_range=0.0,
        ),
    )

    await model()

    limiter = await get_rate_limiter(
        tenant_id="tenant-a",
        agent_id="agent-x",
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    assert resolve_calls == [(None, None, None)]
    assert limiter.stats()["total_acquired"] == 1


@pytest.mark.asyncio
async def test_retry_chat_model_resolves_workload_at_call_time():
    scope = RateLimiterScopeKey("tenant-a", "agent-x")
    model = RetryChatModel(
        _StaticChatModel(),
        tenant_id=scope.tenant_id,
        agent_id=scope.agent_id,
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            chat_max_concurrent=1,
            cron_max_concurrent=2,
            max_qpm=0,
            pause_seconds=10.0,
            jitter_range=0.0,
        ),
    )

    with bind_llm_workload(LLM_WORKLOAD_CRON):
        await model()

    cron = await get_rate_limiter(
        scope_key=scope,
        workload=LLM_WORKLOAD_CRON,
        max_concurrent=2,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )
    chat = await get_rate_limiter(
        scope_key=scope,
        workload=LLM_WORKLOAD_CHAT,
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=10.0,
        jitter_range=0.0,
    )

    assert cron.stats()["total_acquired"] == 1
    assert chat.stats()["total_acquired"] == 0


@pytest.mark.asyncio
async def test_empty_model_output_retries_once_when_llm_retry_disabled():
    bottom = _SequenceChatModel(
        [
            ChatResponse(content=[]),
            ChatResponse(content=[{"type": "text", "text": "retry ok"}]),
        ],
    )
    model = RetryChatModel(
        bottom,
        retry_config=RetryConfig(enabled=False, max_retries=1),
        rate_limit_config=RateLimitConfig(max_qpm=0),
    )

    response = await model()

    assert response.content[0]["text"] == "retry ok"
    assert bottom.calls == 2


@pytest.mark.asyncio
async def test_empty_model_output_retry_does_not_consume_transient_retries():
    bottom = _SequenceChatModel(
        [
            ChatResponse(content=[]),
            _TransientServerError("first transient failure"),
            _TransientServerError("second transient failure"),
            ChatResponse(content=[{"type": "text", "text": "retry ok"}]),
        ],
    )
    model = RetryChatModel(
        bottom,
        retry_config=RetryConfig(enabled=True, max_retries=2),
        rate_limit_config=RateLimitConfig(max_qpm=0),
    )

    response = await model()

    assert response.content[0]["text"] == "retry ok"
    assert bottom.calls == 4


@pytest.mark.asyncio
async def test_empty_model_output_raises_after_single_retry_is_exhausted():
    bottom = _SequenceChatModel(
        [
            ChatResponse(content=[]),
            ChatResponse(content="   "),
        ],
    )
    model = RetryChatModel(
        bottom,
        retry_config=RetryConfig(enabled=False, max_retries=1),
        rate_limit_config=RateLimitConfig(max_qpm=0),
    )

    with pytest.raises(EmptyModelOutputError, match="empty model output"):
        await model()

    assert bottom.calls == 2


@pytest.mark.asyncio
async def test_reasoning_only_model_output_does_not_retry_as_empty():
    bottom = _SequenceChatModel(
        [
            ChatResponse(content=[{"type": "thinking", "text": ""}]),
        ],
    )
    model = RetryChatModel(
        bottom,
        retry_config=RetryConfig(enabled=False, max_retries=1),
        rate_limit_config=RateLimitConfig(max_qpm=0),
    )

    response = await model()

    assert response.content[0]["type"] == "thinking"
    assert bottom.calls == 1


@pytest.mark.asyncio
async def test_streaming_empty_model_output_retries_whole_call_once():
    bottom = _SequenceStreamChatModel(
        [
            [ChatResponse(content=[])],
            [
                ChatResponse(
                    content=[{"type": "text", "text": "stream retry ok"}],
                ),
            ],
        ],
    )
    model = RetryChatModel(
        bottom,
        retry_config=RetryConfig(enabled=False, max_retries=1),
        rate_limit_config=RateLimitConfig(max_qpm=0),
    )

    stream = await model()
    chunks = [chunk async for chunk in stream]

    assert chunks[-1].content[0]["text"] == "stream retry ok"
    assert bottom.calls == 2


@pytest.mark.asyncio
async def test_streaming_empty_output_retry_does_not_consume_transient_retries():
    bottom = _SequenceStreamChatModel(
        [
            [ChatResponse(content=[])],
            _TransientServerError("first transient failure"),
            _TransientServerError("second transient failure"),
            [
                ChatResponse(
                    content=[{"type": "text", "text": "stream retry ok"}],
                ),
            ],
        ],
    )
    model = RetryChatModel(
        bottom,
        retry_config=RetryConfig(enabled=True, max_retries=2),
        rate_limit_config=RateLimitConfig(max_qpm=0),
    )

    stream = await model()
    chunks = [chunk async for chunk in stream]

    assert chunks[-1].content[0]["text"] == "stream retry ok"
    assert bottom.calls == 4


@pytest.mark.asyncio
async def test_streaming_empty_model_output_raises_after_single_retry():
    bottom = _SequenceStreamChatModel(
        [
            [ChatResponse(content=[])],
            [ChatResponse(content=None)],
        ],
    )
    model = RetryChatModel(
        bottom,
        retry_config=RetryConfig(enabled=False, max_retries=1),
        rate_limit_config=RateLimitConfig(max_qpm=0),
    )

    stream = await model()
    with pytest.raises(EmptyModelOutputError, match="empty model output"):
        _chunks = [chunk async for chunk in stream]

    assert bottom.calls == 2


@pytest.mark.asyncio
async def test_streaming_reasoning_output_does_not_retry_as_empty():
    bottom = _SequenceStreamChatModel(
        [
            [ChatResponse(content=[{"type": "reasoning", "text": ""}])],
        ],
    )
    model = RetryChatModel(
        bottom,
        retry_config=RetryConfig(enabled=False, max_retries=1),
        rate_limit_config=RateLimitConfig(max_qpm=0),
    )

    stream = await model()
    chunks = [chunk async for chunk in stream]

    assert chunks[0].content[0]["type"] == "reasoning"
    assert bottom.calls == 1


@pytest.mark.asyncio
async def test_retry_chat_model_timeout_error_identifies_workload(monkeypatch):
    async def fake_wait_for(awaitable, timeout):
        del timeout
        awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(
        "swe.providers.retry_chat_model.asyncio.wait_for",
        fake_wait_for,
    )
    model = RetryChatModel(
        _StaticChatModel(),
        tenant_id="tenant-a",
        agent_id="agent-x",
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            cron_acquire_timeout=30.0,
            max_qpm=0,
            pause_seconds=10.0,
            jitter_range=0.0,
        ),
    )

    with (
        bind_llm_workload(LLM_WORKLOAD_CRON),
        pytest.raises(RuntimeError, match="workload=cron"),
    ):
        await model()


@pytest.mark.asyncio
async def test_cleanup_keeps_limiter_with_active_stream_after_slot_release():
    release_second_chunk = asyncio.Event()
    scope = RateLimiterScopeKey("tenant-a", "stream-agent")
    model = RetryChatModel(
        _BlockingStreamChatModel(release_second_chunk),
        tenant_id=scope.tenant_id,
        agent_id=scope.agent_id,
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            chat_max_concurrent=1,
            max_qpm=0,
            pause_seconds=10.0,
            jitter_range=0.0,
        ),
    )
    stream = await model()

    try:
        await stream.__anext__()
        limiter = await get_rate_limiter(
            scope_key=scope,
            max_concurrent=1,
            max_qpm=0,
            default_pause_seconds=10.0,
            jitter_range=0.0,
        )

        removed = cleanup_idle_rate_limiters(max_idle_seconds=0)
        same_limiter = await get_rate_limiter(
            scope_key=scope,
            max_concurrent=1,
            max_qpm=0,
            default_pause_seconds=10.0,
            jitter_range=0.0,
        )

        assert limiter.stats()["current_in_flight"] == 0
        assert removed == 0
        assert same_limiter is limiter
    finally:
        release_second_chunk.set()
        await stream.aclose()
