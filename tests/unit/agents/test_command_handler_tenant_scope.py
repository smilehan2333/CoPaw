# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from swe.agents.command_handler import CommandHandler


@pytest.mark.asyncio
async def test_handle_command_history_uses_tenant_scoped_agent_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_load_agent_config(agent_id: str, tenant_id: str | None = None):
        calls.append((agent_id, tenant_id))
        return SimpleNamespace(
            running=SimpleNamespace(
                max_input_length=8192,
                history_max_length=4096,
            ),
        )

    monkeypatch.setattr(
        "swe.agents.command_handler.load_agent_config",
        fake_load_agent_config,
    )

    memory = SimpleNamespace(
        get_memory=AsyncMock(return_value=[]),
        get_history_str=AsyncMock(return_value="history payload"),
        get_compressed_summary=lambda: "",
    )
    handler = CommandHandler(
        agent_name="agent",
        memory=memory,
        memory_manager=SimpleNamespace(
            agent_id="default",
            tenant_id="tenant-a",
        ),
    )

    result = await handler.handle_command("/history")

    memory.get_memory.assert_awaited_once_with(prepend_summary=False)
    memory.get_history_str.assert_awaited_once_with(max_input_length=8192)
    assert calls == [("default", "tenant-a")]
    assert result.content[0]["text"] == (
        "history payload\n\n---\n\n- Use /message <index> to view full message content"
    )


def test_command_handler_reads_summary_scope_from_request_context() -> None:
    handler = CommandHandler(
        agent_name="agent",
        memory=SimpleNamespace(),
        memory_manager=None,
        request_context={"session_id": "session-123"},
    )

    assert handler._summary_task_scope_id() == "session-123"
