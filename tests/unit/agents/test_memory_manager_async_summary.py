# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from swe.agents.memory.base_memory_manager import BaseMemoryManager
from swe.agents.memory.reme_light_memory_manager import ReMeLightMemoryManager
from swe.config.config import ToolResultCompactConfig


class _ConcreteMemoryManager(BaseMemoryManager):
    async def start(self) -> None:  # pragma: no cover - test stub
        return None

    async def close(self) -> bool:  # pragma: no cover - test stub
        return True

    async def compact_tool_result(self, **kwargs) -> None:  # pragma: no cover
        del kwargs
        return None

    async def check_context(self, **kwargs) -> tuple:  # pragma: no cover
        del kwargs
        return (), (), True

    async def compact_memory(
        self,
        messages,
        previous_summary="",
        **kwargs,
    ) -> str:  # pragma: no cover
        del messages, previous_summary, kwargs
        return ""

    async def summary_memory(
        self,
        messages,
        **kwargs,
    ) -> str:  # pragma: no cover
        del messages, kwargs
        return ""

    async def dream_memory(
        self,
        tenant_id: str | None = None,
        **kwargs,
    ) -> None:  # pragma: no cover
        del tenant_id, kwargs

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> Any:  # pragma: no cover
        del query, max_results, min_score
        return None

    def get_in_memory_memory(self, **kwargs) -> Any:  # pragma: no cover
        del kwargs


@pytest.mark.asyncio
async def test_add_async_summary_task_freezes_model_snapshot() -> None:
    observed = []
    manager = _ConcreteMemoryManager(
        working_dir="/tmp/ws",
        agent_id="default",
        tenant_id="tenant-a",
    )

    async def fake_summary_memory(messages, **kwargs) -> str:
        del messages
        observed.append(
            (
                kwargs.get("_bound_chat_model"),
                kwargs.get("_bound_formatter"),
            ),
        )
        return "done"

    manager.summary_memory = fake_summary_memory  # type: ignore[method-assign]

    manager.add_async_summary_task(
        messages=[],
        chat_model="model-a",
        formatter="formatter-a",
        scope_id="session-a",
    )
    await manager.await_summary_tasks("session-a")

    assert observed == [
        ("model-a", "formatter-a"),
    ]


@pytest.mark.asyncio
async def test_await_summary_tasks_isolates_scopes() -> None:
    observed = []
    release_a = asyncio.Event()
    release_b = asyncio.Event()
    manager = _ConcreteMemoryManager(
        working_dir="/tmp/ws",
        agent_id="default",
        tenant_id="tenant-a",
    )

    async def fake_summary_memory(messages, **kwargs) -> str:
        del messages
        scope_id = str(kwargs.get("_scope_id") or "")
        observed.append(("start", scope_id))
        if scope_id == "session-a":
            await release_a.wait()
        else:
            await release_b.wait()
        observed.append(("done", scope_id))
        return scope_id

    manager.summary_memory = fake_summary_memory  # type: ignore[method-assign]

    manager.add_async_summary_task(
        messages=[],
        chat_model="model-a",
        formatter="formatter-a",
        scope_id="session-a",
        _scope_id="session-a",
    )
    manager.add_async_summary_task(
        messages=[],
        chat_model="model-b",
        formatter="formatter-b",
        scope_id="session-b",
        _scope_id="session-b",
    )

    release_a.set()
    result_a = await manager.await_summary_tasks("session-a")

    assert "session-a" in result_a
    assert manager.get_summary_task_count("session-a") == 0
    assert manager.get_summary_task_count("session-b") == 1

    release_b.set()
    result_b = await manager.await_summary_tasks("session-b")

    assert "session-b" in result_b
    assert manager.get_summary_task_count("session-b") == 0


@pytest.mark.asyncio
async def test_dream_memory_uses_fresh_execution_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed = {}

    class FakeDreamAgent:
        def __init__(self, **kwargs):
            observed["model"] = kwargs["model"]
            observed["formatter"] = kwargs["formatter"]
            self._total_input_tokens = 0
            self._total_output_tokens = 0

        async def reply(self, _msg):
            return SimpleNamespace(get_text_content=lambda: "dream-ok")

    monkeypatch.setattr(
        "swe.agents.memory.reme_light_memory_manager.ReActAgent",
        FakeDreamAgent,
    )
    monkeypatch.setattr(
        "swe.agents.memory.reme_light_memory_manager.capture_current_trace_context",
        lambda: {
            "trace_id": "trace-dream",
            "user_id": "user-1",
            "session_id": "session-1",
            "channel": "console",
            "source_id": "source-1",
        },
    )
    monkeypatch.setattr(
        "swe.agents.memory.reme_light_memory_manager.load_agent_config",
        lambda agent_id, tenant_id=None: SimpleNamespace(
            agent_id=agent_id,
            language="zh",
            running=SimpleNamespace(
                tool_result_compact=ToolResultCompactConfig(),
            ),
        ),
    )
    monkeypatch.setattr(
        "swe.agents.memory.reme_light_memory_manager.resolve_tool_result_compact_config",
        lambda config: config,
    )
    monkeypatch.setattr(
        "swe.agents.memory.reme_light_memory_manager.set_current_workspace_dir",
        lambda _path: None,
    )
    monkeypatch.setattr(
        "swe.agents.memory.reme_light_memory_manager.set_current_recent_max_bytes",
        lambda _value: None,
    )

    def fake_create_execution_model_formatter(*, trace_context=None):
        observed["trace_context"] = trace_context
        return "fresh-model", "fresh-formatter"

    manager = object.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager.tenant_id = "tenant-a"
    manager.working_dir = str(tmp_path)
    manager.summary_toolkit = object()
    manager._warn_if_version_mismatch = lambda: None
    manager._create_execution_model_formatter = (
        fake_create_execution_model_formatter
    )
    manager._get_dream_prompt = lambda language, current_date: "dream prompt"
    manager._log_dream_result = lambda **kwargs: observed.setdefault(
        "log_status",
        kwargs["status"],
    )

    await manager.dream_memory(tenant_id="tenant-a", trigger="manual")

    assert observed["model"] == "fresh-model"
    assert observed["formatter"] == "fresh-formatter"
    assert observed["trace_context"]["trace_id"] == "trace-dream"
    assert observed["log_status"] == "success"


@pytest.mark.asyncio
async def test_compact_memory_uses_bound_execution_model_without_shared_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {}

    class FakeReMe:
        async def compact_memory(self, **kwargs):
            observed["model"] = kwargs["as_llm"]
            observed["formatter"] = kwargs["as_llm_formatter"]
            return {"history_compact": "ok", "is_valid": True}

    monkeypatch.setattr(
        "swe.agents.memory.reme_light_memory_manager.load_agent_config",
        lambda agent_id, tenant_id=None: SimpleNamespace(
            agent_id=agent_id,
            language="zh",
            workspace_dir="/tmp/ws",
            running=SimpleNamespace(
                max_input_length=128000,
                context_compact=SimpleNamespace(
                    memory_compact_ratio=0.5,
                    compact_with_thinking_block=False,
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        "swe.agents.memory.reme_light_memory_manager.get_swe_token_counter",
        lambda _config: "token-counter",
    )

    manager = object.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager.tenant_id = "tenant-a"
    manager._reme = FakeReMe()
    manager._warn_if_version_mismatch = lambda: None

    result = await manager.compact_memory(
        messages=[],
        previous_summary="",
        _bound_chat_model="bound-model",
        _bound_formatter="bound-formatter",
    )

    assert result == "ok"
    assert observed["model"] == "bound-model"
    assert observed["formatter"] == "bound-formatter"
