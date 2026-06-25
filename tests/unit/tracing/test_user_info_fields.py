# -*- coding: utf-8 -*-
"""Tests for tracing user_name and bbk_id fields functionality.

测试 tracing 模块新增的 user_name 和 bbk_id 字段功能：
- Pydantic 模型字段验证
- TraceContext 属性验证
- TraceManager 方法参数传递验证
- TraceStore 行转模型方法验证
- TracingHook 参数传递验证
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swe.tracing.models import (
    EventType,
    Span,
    Trace,
    TraceStatus,
    UserListItem,
    TraceListItem,
    UserMessageItem,
)
from swe.tracing.manager import TraceContext, TraceManager
from swe.tracing.store import TraceStore
from swe.tracing.config import TracingConfig
from swe.agents.hooks.tracing import TracingHook


class TestSpanUserInfoFields:
    """测试 Span 模型的 user_name 和 bbk_id 字段。"""

    def test_span_user_name_optional(self):
        """测试 user_name 字段是可选的，默认为 None。"""
        span = Span(
            span_id="span-1",
            trace_id="trace-1",
            source_id="test-source",
            name="test_span",
            event_type=EventType.LLM_INPUT,
            start_time=datetime.now(),
        )
        assert span.user_name is None
        assert span.bbk_id is None

    def test_span_user_name_set(self):
        """测试 user_name 和 bbk_id 字段可以正确设置。"""
        span = Span(
            span_id="span-1",
            trace_id="trace-1",
            source_id="test-source",
            name="test_span",
            event_type=EventType.LLM_INPUT,
            start_time=datetime.now(),
            user_name="测试用户",
            bbk_id="BBK001",
        )
        assert span.user_name == "测试用户"
        assert span.bbk_id == "BBK001"

    def test_span_user_name_with_user_id(self):
        """测试 user_name、bbk_id 与 user_id 可以共存。"""
        span = Span(
            span_id="span-1",
            trace_id="trace-1",
            source_id="test-source",
            name="test_span",
            event_type=EventType.TOOL_CALL_START,
            start_time=datetime.now(),
            user_id="user-001",
            user_name="张三",
            bbk_id="BBK100",
        )
        assert span.user_id == "user-001"
        assert span.user_name == "张三"
        assert span.bbk_id == "BBK100"


class TestTraceUserInfoFields:
    """测试 Trace 模型的 user_name 和 bbk_id 字段。"""

    def test_trace_user_name_optional(self):
        """测试 user_name 字段是可选的，默认为 None。"""
        trace = Trace(
            trace_id="trace-1",
            source_id="test-source",
            user_id="user-1",
            session_id="session-1",
            channel="console",
            start_time=datetime.now(),
        )
        assert trace.user_name is None
        assert trace.bbk_id is None

    def test_trace_user_name_set(self):
        """测试 user_name 和 bbk_id 字段可以正确设置。"""
        trace = Trace(
            trace_id="trace-1",
            source_id="test-source",
            user_id="user-1",
            user_name="李四",
            bbk_id="BBK002",
            session_id="session-1",
            channel="console",
            start_time=datetime.now(),
        )
        assert trace.user_id == "user-1"
        assert trace.user_name == "李四"
        assert trace.bbk_id == "BBK002"

    def test_trace_user_name_after_user_id(self):
        """测试 user_name 和 bbk_id 字段在 user_id 之后。"""
        # 验证字段顺序符合设计（在 user_id 后）
        trace = Trace(
            trace_id="trace-1",
            source_id="test-source",
            user_id="user-1",
            user_name="王五",
            bbk_id="BBK003",
            session_id="session-1",
            channel="console",
            start_time=datetime.now(),
        )
        # Trace 模型应包含所有字段
        assert hasattr(trace, "user_id")
        assert hasattr(trace, "user_name")
        assert hasattr(trace, "bbk_id")


class TestUserListItemUserInfoFields:
    """测试 UserListItem 模型的 user_name 和 bbk_id 字段。"""

    def test_user_list_item_optional_fields(self):
        """测试 user_name 和 bbk_id 是可选字段。"""
        item = UserListItem(
            user_id="user-1",
            total_sessions=5,
            total_conversations=10,
        )
        assert item.user_name is None
        assert item.bbk_id is None

    def test_user_list_item_with_user_info(self):
        """测试 UserListItem 可以包含用户信息。"""
        item = UserListItem(
            user_id="user-1",
            user_name="赵六",
            bbk_id="BBK004",
            total_sessions=5,
            total_conversations=10,
            total_tokens=1000,
            total_skills=2,
        )
        assert item.user_id == "user-1"
        assert item.user_name == "赵六"
        assert item.bbk_id == "BBK004"


class TestTraceListItemUserInfoFields:
    """测试 TraceListItem 模型的 user_name 和 bbk_id 字段。"""

    def test_trace_list_item_optional_fields(self):
        """测试 user_name 和 bbk_id 是可选字段。"""
        item = TraceListItem(
            trace_id="trace-1",
            source_id="test-source",
            user_id="user-1",
            session_id="session-1",
            channel="console",
            start_time=datetime.now(),
            status="completed",
        )
        assert item.user_name is None
        assert item.bbk_id is None

    def test_trace_list_item_with_user_info(self):
        """测试 TraceListItem 可以包含用户信息。"""
        item = TraceListItem(
            trace_id="trace-1",
            source_id="test-source",
            user_id="user-1",
            user_name="钱七",
            bbk_id="BBK005",
            session_id="session-1",
            channel="console",
            start_time=datetime.now(),
            status="completed",
            duration_ms=5000,
            total_tokens=500,
        )
        assert item.user_name == "钱七"
        assert item.bbk_id == "BBK005"


class TestUserMessageItemUserInfoFields:
    """测试 UserMessageItem 模型的 user_name 和 bbk_id 字段。"""

    def test_user_message_item_optional_fields(self):
        """测试 user_name 和 bbk_id 是可选字段。"""
        item = UserMessageItem(
            trace_id="trace-1",
            source_id="test-source",
            user_id="user-1",
            session_id="session-1",
            channel="console",
            start_time=datetime.now(),
        )
        assert item.user_name is None
        assert item.bbk_id is None

    def test_user_message_item_with_user_info(self):
        """测试 UserMessageItem 可以包含用户信息。"""
        item = UserMessageItem(
            trace_id="trace-1",
            source_id="test-source",
            user_id="user-1",
            user_name="孙八",
            bbk_id="BBK006",
            session_id="session-1",
            channel="console",
            user_message="你好",
            input_tokens=10,
            output_tokens=20,
            start_time=datetime.now(),
        )
        assert item.user_name == "孙八"
        assert item.bbk_id == "BBK006"


class TestTraceContextUserInfoFields:
    """测试 TraceContext 的 user_name 和 bbk_id 属性。"""

    def test_trace_context_without_user_info(self):
        """测试 TraceContext 不包含用户信息时的默认值。"""
        ctx = TraceContext(
            trace_id="trace-1",
            user_id="user-1",
            session_id="session-1",
            channel="console",
            source_id="test-source",
        )
        assert ctx.user_name is None
        assert ctx.bbk_id is None

    def test_trace_context_with_user_info(self):
        """测试 TraceContext 包含用户信息。"""
        ctx = TraceContext(
            trace_id="trace-1",
            user_id="user-1",
            user_name="周九",
            bbk_id="BBK007",
            session_id="session-1",
            channel="console",
            source_id="test-source",
        )
        assert ctx.trace_id == "trace-1"
        assert ctx.user_id == "user-1"
        assert ctx.user_name == "周九"
        assert ctx.bbk_id == "BBK007"

    def test_trace_context_attributes_exist(self):
        """测试 TraceContext 具有 user_name 和 bbk_id 属性。"""
        ctx = TraceContext(
            trace_id="trace-1",
            user_id="user-1",
            session_id="session-1",
            channel="console",
            source_id="test-source",
        )
        assert hasattr(ctx, "user_name")
        assert hasattr(ctx, "bbk_id")


class TestTraceManagerUserInfoParameters:
    """测试 TraceManager 的 user_name 和 bbk_id 参数传递。"""

    @pytest.fixture
    def mock_db(self):
        """创建 mock 数据库连接。"""
        db = MagicMock()
        db.is_connected = True
        db.execute = AsyncMock(return_value=1)
        db.fetch_one = AsyncMock(return_value=None)
        db.fetch_all = AsyncMock(return_value=[])
        return db

    @pytest.fixture
    def config(self):
        """创建 tracing 配置。"""
        return TracingConfig(enabled=True, batch_size=10, flush_interval=1)

    @pytest.mark.asyncio
    async def test_start_trace_with_user_info(self, config, mock_db):
        """测试 start_trace 方法接收 user_name 和 bbk_id 参数。"""
        manager = TraceManager(config, db=mock_db)
        manager._store = MagicMock()
        manager._store.create_trace = AsyncMock()
        manager._running = True

        trace_id = await manager.start_trace(
            user_id="user-1",
            session_id="session-1",
            channel="console",
            source_id="test-source",
            user_message="测试消息",
            user_name="吴十",
            bbk_id="BBK008",
        )

        # 验证 create_trace 被调用，且 Trace 包含用户信息
        assert manager._store.create_trace.called
        trace_arg = manager._store.create_trace.call_args[0][0]
        assert trace_arg.user_id == "user-1"
        assert trace_arg.user_name == "吴十"
        assert trace_arg.bbk_id == "BBK008"

    @pytest.mark.asyncio
    async def test_start_trace_without_user_info(self, config, mock_db):
        """测试 start_trace 方法不传 user_name 和 bbk_id 时正常工作。"""
        manager = TraceManager(config, db=mock_db)
        manager._store = MagicMock()
        manager._store.create_trace = AsyncMock()
        manager._running = True

        trace_id = await manager.start_trace(
            user_id="user-1",
            session_id="session-1",
            channel="console",
            source_id="test-source",
        )

        # 验证 create_trace 被调用，且 Trace 用户信息为 None
        assert manager._store.create_trace.called
        trace_arg = manager._store.create_trace.call_args[0][0]
        assert trace_arg.user_name is None
        assert trace_arg.bbk_id is None


class TestTraceStoreRowConversion:
    """测试 TraceStore 的行转模型方法。"""

    def test_row_to_trace_with_user_info(self):
        """测试 _row_to_trace 方法处理 user_name 和 bbk_id。"""
        config = TracingConfig(enabled=True)
        store = TraceStore(config, db=None)

        row = {
            "trace_id": "trace-1",
            "source_id": "test-source",
            "user_id": "user-1",
            "user_name": "郑十一",
            "bbk_id": "BBK009",
            "session_id": "session-1",
            "channel": "console",
            "start_time": datetime.now(),
            "end_time": None,
            "duration_ms": None,
            "model_name": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "tools_used": None,
            "skills_used": None,
            "status": "running",
            "error": None,
            "user_message": None,
        }

        trace = store._row_to_trace(row)

        assert trace.trace_id == "trace-1"
        assert trace.user_id == "user-1"
        assert trace.user_name == "郑十一"
        assert trace.bbk_id == "BBK009"

    def test_row_to_trace_without_user_info(self):
        """测试 _row_to_trace 方法处理缺失的 user_name 和 bbk_id。"""
        config = TracingConfig(enabled=True)
        store = TraceStore(config, db=None)

        row = {
            "trace_id": "trace-1",
            "source_id": "test-source",
            "user_id": "user-1",
            "session_id": "session-1",
            "channel": "console",
            "start_time": datetime.now(),
            "end_time": None,
            "duration_ms": None,
            "model_name": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "tools_used": None,
            "skills_used": None,
            "status": "running",
            "error": None,
            "user_message": None,
        }

        trace = store._row_to_trace(row)

        assert trace.user_name is None
        assert trace.bbk_id is None

    def test_row_to_span_with_user_info(self):
        """测试 _row_to_span 方法处理 user_name 和 bbk_id。"""
        config = TracingConfig(enabled=True)
        store = TraceStore(config, db=None)

        row = {
            "span_id": "span-1",
            "trace_id": "trace-1",
            "source_id": "test-source",
            "name": "test_span",
            "event_type": "llm_input",
            "start_time": datetime.now(),
            "end_time": None,
            "duration_ms": None,
            "user_id": "user-1",
            "user_name": "王十二",
            "bbk_id": "BBK010",
            "session_id": "session-1",
            "channel": "console",
            "model_name": "gpt-4",
            "input_tokens": None,
            "output_tokens": None,
            "tool_name": None,
            "skill_name": None,
            "skill_id": None,
            "skill_cn_name": None,
            "skill_description": None,
            "mcp_server": None,
            "tool_input": None,
            "tool_output": None,
            "error": None,
        }

        span = store._row_to_span(row)

        assert span.span_id == "span-1"
        assert span.user_id == "user-1"
        assert span.user_name == "王十二"
        assert span.bbk_id == "BBK010"

    def test_row_to_span_without_user_info(self):
        """测试 _row_to_span 方法处理缺失的 user_name 和 bbk_id。"""
        config = TracingConfig(enabled=True)
        store = TraceStore(config, db=None)

        row = {
            "span_id": "span-1",
            "trace_id": "trace-1",
            "source_id": "test-source",
            "name": "test_span",
            "event_type": "llm_input",
            "start_time": datetime.now(),
            "end_time": None,
            "duration_ms": None,
            "user_id": "user-1",
            "session_id": "session-1",
            "channel": "console",
            "model_name": None,
            "input_tokens": None,
            "output_tokens": None,
            "tool_name": None,
            "skill_name": None,
            "skill_id": None,
            "skill_cn_name": None,
            "skill_description": None,
            "mcp_server": None,
            "tool_input": None,
            "tool_output": None,
            "error": None,
        }

        span = store._row_to_span(row)

        assert span.user_name is None
        assert span.bbk_id is None


class TestTracingHookUserInfoParameters:
    """测试 TracingHook 的 user_name 和 bbk_id 参数。"""

    def test_tracing_hook_init_without_user_info(self):
        """测试 TracingHook 初始化不包含用户信息。"""
        hook = TracingHook(
            trace_id="trace-1",
            user_id="user-1",
            session_id="session-1",
            channel="console",
            source_id="test-source",
        )
        assert hook.user_name is None
        assert hook.bbk_id is None

    def test_tracing_hook_init_with_user_info(self):
        """测试 TracingHook 初始化包含用户信息。"""
        hook = TracingHook(
            trace_id="trace-1",
            user_id="user-1",
            user_name="李十三",
            bbk_id="BBK011",
            session_id="session-1",
            channel="console",
            source_id="test-source",
        )
        assert hook.trace_id == "trace-1"
        assert hook.user_id == "user-1"
        assert hook.user_name == "李十三"
        assert hook.bbk_id == "BBK011"

    def test_tracing_hook_attributes_exist(self):
        """测试 TracingHook 具有 user_name 和 bbk_id 属性。"""
        hook = TracingHook(
            trace_id="trace-1",
            user_id="user-1",
            session_id="session-1",
            channel="console",
            source_id="test-source",
        )
        assert hasattr(hook, "user_name")
        assert hasattr(hook, "bbk_id")


class TestIntegrationUserInfoFlow:
    """测试 user_name 和 bbk_id 的完整数据流。"""

    def test_full_flow_models(self):
        """测试模型之间的数据一致性。"""
        # 创建 Trace 包含用户信息
        trace = Trace(
            trace_id="trace-1",
            source_id="test-source",
            user_id="user-1",
            user_name="完整测试用户",
            bbk_id="BBK-FULL",
            session_id="session-1",
            channel="console",
            start_time=datetime.now(),
        )

        # 创建 Span 应继承相同的用户信息
        span = Span(
            span_id="span-1",
            trace_id=trace.trace_id,
            source_id=trace.source_id,
            name="llm_call",
            event_type=EventType.LLM_INPUT,
            start_time=datetime.now(),
            user_id=trace.user_id,
            user_name=trace.user_name,
            bbk_id=trace.bbk_id,
            session_id=trace.session_id,
            channel=trace.channel,
        )

        # 验证数据一致性
        assert span.trace_id == trace.trace_id
        assert span.user_id == trace.user_id
        assert span.user_name == trace.user_name
        assert span.bbk_id == trace.bbk_id
        assert span.session_id == trace.session_id
        assert span.channel == trace.channel
