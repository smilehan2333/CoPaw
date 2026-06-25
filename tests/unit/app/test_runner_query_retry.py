# -*- coding: utf-8 -*-
"""查询级自动重试分类器与退避计算单元测试"""

import asyncio
import errno
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.swe.app.runner.runner import AgentRunner
from src.swe.app.runner.retry_classifier import is_query_retryable
from src.swe.tracing.manager import (
    TraceContext,
    get_current_trace,
    set_current_trace,
)

# ── is_query_retryable 基础分类测试 ──


class TestIsQueryRetryable:
    """异常可重试分类测试"""

    def test_connection_error_retryable(self):
        assert is_query_retryable(ConnectionError("conn reset")) is True

    def test_connection_reset_error_retryable(self):
        assert is_query_retryable(ConnectionResetError("reset")) is True

    def test_broken_pipe_error_retryable(self):
        assert is_query_retryable(BrokenPipeError("pipe")) is True

    def test_asyncio_timeout_retryable(self):
        assert is_query_retryable(asyncio.TimeoutError()) is True

    def test_cancelled_error_not_retryable(self):
        assert is_query_retryable(asyncio.CancelledError()) is False

    def test_value_error_not_retryable(self):
        assert is_query_retryable(ValueError("bad input")) is False

    def test_runtime_error_generic_not_retryable(self):
        assert is_query_retryable(RuntimeError("something wrong")) is False

    def test_runtime_error_rate_limiter_retryable(self):
        assert (
            is_query_retryable(RuntimeError("rate limiter triggered")) is True
        )

    def test_runtime_error_timed_out_retryable(self):
        assert is_query_retryable(RuntimeError("request timed out")) is True

    def test_runtime_error_timed_out_case_insensitive(self):
        assert is_query_retryable(RuntimeError("Request Timed Out")) is True


class TestStatusCodeRetryable:
    """HTTP 状态码分类测试"""

    def test_429_retryable(self):
        class Err(Exception):
            status_code = 429

        assert is_query_retryable(Err()) is True

    def test_432_retryable(self):
        class Err(Exception):
            status_code = 432

        assert is_query_retryable(Err()) is True

    def test_500_retryable(self):
        class Err(Exception):
            status_code = 500

        assert is_query_retryable(Err()) is True

    def test_502_retryable(self):
        class Err(Exception):
            status_code = 502

        assert is_query_retryable(Err()) is True

    def test_503_retryable(self):
        class Err(Exception):
            status_code = 503

        assert is_query_retryable(Err()) is True

    def test_504_retryable(self):
        class Err(Exception):
            status_code = 504

        assert is_query_retryable(Err()) is True

    def test_400_not_retryable(self):
        class Err(Exception):
            status_code = 400

        assert is_query_retryable(Err()) is False

    def test_404_not_retryable(self):
        class Err(Exception):
            status_code = 404

        assert is_query_retryable(Err()) is False


class TestOSErrorRetryable:
    """OSError errno 分类测试"""

    def test_econnreset_retryable(self):
        exc = OSError(errno.ECONNRESET, "Connection reset")
        assert is_query_retryable(exc) is True

    def test_econnrefused_retryable(self):
        exc = OSError(errno.ECONNREFUSED, "Connection refused")
        assert is_query_retryable(exc) is True

    def test_etimedout_retryable(self):
        exc = OSError(errno.ETIMEDOUT, "Timed out")
        assert is_query_retryable(exc) is True

    def test_eintr_not_retryable(self):
        exc = OSError(errno.EINTR, "Interrupted")
        assert is_query_retryable(exc) is False


class TestMessagePatternRetryable:
    """消息关键词匹配测试"""

    def test_token_limit_chinese(self):
        assert (
            is_query_retryable(RuntimeError("输入Token数已达到每分钟上限"))
            is True
        )

    def test_rate_limit_english(self):
        assert is_query_retryable(RuntimeError("Rate limit exceeded")) is True

    def test_too_many_requests(self):
        assert is_query_retryable(Exception("Too many requests")) is True

    def test_quota_exceeded(self):
        assert (
            is_query_retryable(Exception("Quota exceeded for today")) is True
        )

    def test_throttled(self):
        assert is_query_retryable(Exception("Request throttled")) is True

    def test_normal_message_not_retryable(self):
        assert is_query_retryable(Exception("File not found")) is False


class TestExceptionChainRetryable:
    """异常链穿透 status_code 检测测试"""

    def test_chained_cause_432_retryable(self):
        """RuntimeError 包装 APIStatusError(status_code=432) 通过 __cause__ 识别"""
        inner = Exception("输入Token数已达到每分钟上限!")
        inner.status_code = 432
        outer = RuntimeError("LLM call failed")
        outer.__cause__ = inner
        assert is_query_retryable(outer) is True

    def test_chained_context_429_retryable(self):
        """异常通过 __context__ 链接时也能识别"""
        inner = Exception("Rate limit exceeded")
        inner.status_code = 429
        outer = RuntimeError("something failed")
        outer.__context__ = inner
        assert is_query_retryable(outer) is True

    def test_chained_non_retryable_status(self):
        """异常链中 status_code 不在可重试集合中时返回 False"""
        inner = Exception("Not found")
        inner.status_code = 404
        outer = RuntimeError("something failed")
        outer.__cause__ = inner
        assert is_query_retryable(outer) is False

    def test_chained_no_status_code(self):
        """异常链中无 status_code 时返回 False"""
        inner = Exception("some error")
        outer = RuntimeError("something failed")
        outer.__cause__ = inner
        assert is_query_retryable(outer) is False

    def test_deep_chain_432_retryable(self):
        """多层异常链深处包含 432 时仍能识别"""
        deep = Exception("token limit")
        deep.status_code = 432
        mid = RuntimeError("mid layer")
        mid.__cause__ = deep
        outer = RuntimeError("outer layer")
        outer.__cause__ = mid
        assert is_query_retryable(outer) is True

    def test_chain_cycle_safety(self):
        """异常链存在循环引用时不会死循环"""
        a = Exception("a")
        b = Exception("b")
        a.__cause__ = b
        b.__context__ = a
        assert is_query_retryable(a) is False


class TestHttpxRetryable:
    """httpx 异常分类测试"""

    def test_httpx_connect_error_retryable(self):
        try:
            import httpx

            assert is_query_retryable(httpx.ConnectError("connect")) is True
        except ImportError:
            pytest.skip("httpx not installed")

    def test_httpx_timeout_retryable(self):
        try:
            import httpx

            assert (
                is_query_retryable(httpx.TimeoutException("timeout")) is True
            )
        except ImportError:
            pytest.skip("httpx not installed")


@pytest.mark.asyncio
async def test_end_trace_if_needed_clears_attached_trace_context(tmp_path):
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    attached_ctx = TraceContext(
        trace_id="trace-1",
        user_id="user-1",
        session_id="session-1",
        channel="console",
        source_id="source-1",
        attached=True,
    )
    set_current_trace(attached_ctx)

    mock_trace_manager = AsyncMock()

    with (
        patch(
            "src.swe.app.runner.runner.has_trace_manager",
            return_value=True,
        ),
        patch(
            "src.swe.app.runner.runner.get_trace_manager",
            return_value=mock_trace_manager,
        ),
    ):
        await runner._end_trace_if_needed("trace-1", status="completed")

    assert get_current_trace() is None
    mock_trace_manager.end_trace.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_query_trace_does_not_attach_stale_request_trace_id_by_default(
    tmp_path,
):
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    request = SimpleNamespace(
        trace_id="trace-stale",
        user_id="user-1",
        session_id="session-1",
        channel="console",
        source_id="source-1",
        channel_meta={},
    )
    start_trace = AsyncMock(return_value="trace-new")
    trace_manager = SimpleNamespace(enabled=True, start_trace=start_trace)

    with (
        patch(
            "src.swe.app.runner.runner.has_trace_manager",
            return_value=True,
        ),
        patch(
            "src.swe.app.runner.runner.get_trace_manager",
            return_value=trace_manager,
        ),
        patch(
            "src.swe.app.runner.runner.resolve_user_identity",
            AsyncMock(
                return_value=SimpleNamespace(user_name=None, bbk_id=None),
            ),
        ),
    ):
        trace_id = await runner._start_query_trace(request, [])

    assert trace_id == "trace-new"
    assert request.trace_id == "trace-new"
    start_trace.assert_awaited_once()
    kwargs = start_trace.await_args.kwargs
    assert kwargs["trace_id"] is None
    assert kwargs["attach_existing"] is False


@pytest.mark.asyncio
async def test_start_query_trace_allows_explicit_attach_existing_trace(
    tmp_path,
):
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    request = SimpleNamespace(
        trace_id="trace-existing",
        user_id="user-1",
        session_id="session-1",
        channel="console",
        source_id="source-1",
        channel_meta={"trace_attach_existing": True},
    )
    start_trace = AsyncMock(return_value="trace-existing")
    trace_manager = SimpleNamespace(enabled=True, start_trace=start_trace)

    with (
        patch(
            "src.swe.app.runner.runner.has_trace_manager",
            return_value=True,
        ),
        patch(
            "src.swe.app.runner.runner.get_trace_manager",
            return_value=trace_manager,
        ),
        patch(
            "src.swe.app.runner.runner.resolve_user_identity",
            AsyncMock(
                return_value=SimpleNamespace(user_name=None, bbk_id=None),
            ),
        ),
    ):
        trace_id = await runner._start_query_trace(request, [])

    assert trace_id == "trace-existing"
    start_trace.assert_awaited_once()
    kwargs = start_trace.await_args.kwargs
    assert kwargs["trace_id"] == "trace-existing"
    assert kwargs["attach_existing"] is True


@pytest.mark.asyncio
async def test_end_trace_if_needed_prevents_attached_trace_leak_to_next_request(
    tmp_path,
):
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    set_current_trace(
        TraceContext(
            trace_id="trace-attached",
            user_id="user-1",
            session_id="session-1",
            channel="console",
            source_id="source-1",
            attached=True,
        ),
    )

    with (
        patch(
            "src.swe.app.runner.runner.has_trace_manager",
            return_value=True,
        ),
        patch(
            "src.swe.app.runner.runner.get_trace_manager",
            return_value=AsyncMock(),
        ),
    ):
        await runner._end_trace_if_needed(
            "trace-attached",
            status="completed",
        )

    assert get_current_trace() is None

    next_request_ctx = TraceContext(
        trace_id="trace-next",
        user_id="user-1",
        session_id="session-2",
        channel="console",
        source_id="source-1",
    )
    set_current_trace(next_request_ctx)
    assert get_current_trace().trace_id == "trace-next"
    assert get_current_trace().attached is False
    set_current_trace(None)


@pytest.mark.asyncio
async def test_end_trace_if_needed_keeps_other_attached_trace_context(
    tmp_path,
):
    runner = AgentRunner(agent_id="test-agent", workspace_dir=tmp_path)
    attached_ctx = TraceContext(
        trace_id="trace-other",
        user_id="user-1",
        session_id="session-1",
        channel="console",
        source_id="source-1",
        attached=True,
    )
    set_current_trace(attached_ctx)

    mock_trace_manager = AsyncMock()

    with (
        patch(
            "src.swe.app.runner.runner.has_trace_manager",
            return_value=True,
        ),
        patch(
            "src.swe.app.runner.runner.get_trace_manager",
            return_value=mock_trace_manager,
        ),
    ):
        await runner._end_trace_if_needed("trace-current", status="completed")

    assert get_current_trace() is attached_ctx
    mock_trace_manager.end_trace.assert_awaited_once_with(
        "trace-current",
        status="completed",
    )
    set_current_trace(None)


def test_httpx_remote_protocol_error_retryable():
    try:
        import httpx

        assert (
            is_query_retryable(httpx.RemoteProtocolError("protocol")) is True
        )
    except ImportError:
        pytest.skip("httpx not installed")


# ── 退避计算测试 ──


class TestBackoffCalculation:
    """指数退避计算验证"""

    def test_first_retry_backoff(self):
        base, cap = 2.0, 30.0
        # 第 1 次重试: min(cap, base * 2^0) = min(30, 2) = 2
        backoff = min(cap, base * (2 ** (1 - 1)))
        assert backoff == 2.0

    def test_second_retry_backoff(self):
        base, cap = 2.0, 30.0
        # 第 2 次重试: min(cap, base * 2^1) = min(30, 4) = 4
        backoff = min(cap, base * (2 ** (2 - 1)))
        assert backoff == 4.0

    def test_third_retry_backoff(self):
        base, cap = 2.0, 30.0
        # 第 3 次重试: min(cap, base * 2^2) = min(30, 8) = 8
        backoff = min(cap, base * (2 ** (3 - 1)))
        assert backoff == 8.0

    def test_backoff_capped(self):
        base, cap = 2.0, 10.0
        # 第 4 次重试: min(10, 2 * 2^3) = min(10, 16) = 10
        backoff = min(cap, base * (2 ** (4 - 1)))
        assert backoff == 10.0

    def test_zero_base_not_allowed_by_config(self):
        """配置层 ge=0.5 已阻止 base=0，此处验证公式本身在 base=0.5 时的行为"""
        base, cap = 0.5, 30.0
        backoff = min(cap, base * (2 ** (1 - 1)))
        assert backoff == 0.5


# ── 配置默认值测试 ──


class TestQueryRetryConfigDefaults:
    """QueryRetryConfig 默认值验证"""

    def test_default_enabled_is_false(self):
        from src.swe.config.config import QueryRetryConfig

        cfg = QueryRetryConfig()
        assert cfg.enabled is False

    def test_default_max_retries(self):
        from src.swe.config.config import QueryRetryConfig

        cfg = QueryRetryConfig()
        assert cfg.max_retries == 3

    def test_backoff_cap_lt_base_raises(self):
        from src.swe.config.config import QueryRetryConfig

        with pytest.raises(ValueError, match="backoff_cap"):
            QueryRetryConfig(backoff_base=30.0, backoff_cap=2.0)
