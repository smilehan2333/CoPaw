# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from swe.app.approvals.service import ApprovalService
from swe.app.runner.runner import AgentRunner
from swe.config.context import tenant_context
from swe.security.tool_guard.approval import ApprovalDecision


def _result():
    return SimpleNamespace(findings=[], findings_count=0)


@pytest.mark.asyncio
async def test_hook_approval_is_not_consumed_as_tool_guard_preapproval() -> (
    None
):
    service = ApprovalService()
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        pending = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
            extra={
                "approval_kind": "hook_pre_tool_use",
                "tool_call": {
                    "id": "tool-1",
                    "name": "execute_shell_command",
                    "input": {"cmd": "echo original"},
                },
            },
        )
        await service.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
        )

        consumed = await service.consume_approval(
            "session-1",
            "execute_shell_command",
            tool_params={"cmd": "echo original"},
        )

    assert consumed is False


@pytest.mark.asyncio
async def test_tool_guard_approval_is_consumed_as_preapproval() -> None:
    service = ApprovalService()
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        pending = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
            extra={
                "approval_kind": "tool_guard",
                "tool_call": {
                    "id": "tool-1",
                    "name": "execute_shell_command",
                    "input": {"cmd": "echo original"},
                },
            },
        )
        await service.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
        )

        consumed = await service.consume_approval(
            "session-1",
            "execute_shell_command",
            tool_params={"cmd": "echo original"},
        )

    assert consumed is True


@pytest.mark.asyncio
async def test_pending_approval_lookup_is_scope_aware_for_same_session() -> (
    None
):
    service = ApprovalService()
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        pending_a = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
        )
    with tenant_context(tenant_id="tenant-a", source_id="source-b"):
        pending_b = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
        )

    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        selected_a = await service.get_pending_by_session("session-1")
    with tenant_context(tenant_id="tenant-a", source_id="source-b"):
        selected_b = await service.get_pending_by_session("session-1")

    assert selected_a is not None
    assert selected_b is not None
    assert selected_a.request_id == pending_a.request_id
    assert selected_b.request_id == pending_b.request_id


@pytest.mark.asyncio
async def test_unscoped_lookup_cannot_observe_scoped_pending() -> None:
    service = ApprovalService()
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
        )

    assert await service.get_pending_by_session("session-1") is None


@pytest.mark.asyncio
async def test_unscoped_resolution_cannot_mutate_scoped_pending() -> None:
    service = ApprovalService()
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        pending = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
        )

    resolved = await service.resolve_request(
        pending.request_id,
        ApprovalDecision.APPROVED,
    )

    assert resolved is None
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        assert (await service.get_request(pending.request_id)).status == (
            "pending"
        )


@pytest.mark.asyncio
async def test_pending_approval_uses_canonical_scope_key_for_legacy_input() -> (
    None
):
    service = ApprovalService()
    with tenant_context(
        tenant_id="tenant-a",
        source_id="source-a",
        scope_id="scope.v1.dGVuYW50LWE.c291cmNlLWE",
    ):
        pending = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
        )

    assert pending.scope_id == "dGVuYW50LWE.c291cmNlLWE"


@pytest.mark.asyncio
async def test_pending_approval_gc_keeps_records_inside_timeout_window() -> (
    None
):
    service = ApprovalService()
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        pending = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
        )
        pending.created_at = time.time() - 3600

        await service.create_pending(
            session_id="session-2",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
        )

        assert (await service.get_request(pending.request_id)).status == (
            "pending"
        )


@pytest.mark.asyncio
async def test_runner_approves_requested_pending_id_not_fifo_head(
    monkeypatch,
) -> None:
    service = ApprovalService()
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        first = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
            extra={
                "approval_kind": "tool_guard",
                "tool_call": {
                    "id": "tool-1",
                    "name": "execute_shell_command",
                    "input": {"cmd": "echo first"},
                },
            },
        )
        second = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
            extra={
                "approval_kind": "hook_pre_tool_use",
                "hook_ask_handler_ids": ["hook-a"],
                "tool_call": {
                    "id": "tool-2",
                    "name": "execute_shell_command",
                    "input": {"cmd": "echo second"},
                },
            },
        )
    monkeypatch.setattr(
        "swe.app.approvals.service._approval_service",
        service,
    )
    runner = AgentRunner()

    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        response, consumed, approved_tool_call = (
            await runner._resolve_pending_approval(
                "session-1",
                f"/approve {second.request_id}",
            )
        )

        assert response is None
        assert consumed is True
        assert approved_tool_call is not None
        assert approved_tool_call["id"] == "tool-2"
        assert approved_tool_call["_approval_replay"]["request_id"] == (
            second.request_id
        )
        assert (await service.get_request(first.request_id)).status == (
            "pending"
        )
        assert (await service.get_request(second.request_id)).status == (
            "approved"
        )


@pytest.mark.asyncio
async def test_runner_rejects_requested_pending_id_from_other_source(
    monkeypatch,
) -> None:
    service = ApprovalService()
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        pending = await service.create_pending(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            tool_name="execute_shell_command",
            result=_result(),
        )
    monkeypatch.setattr(
        "swe.app.approvals.service._approval_service",
        service,
    )
    runner = AgentRunner()

    with tenant_context(tenant_id="tenant-a", source_id="source-b"):
        response, consumed, approved_tool_call = (
            await runner._resolve_pending_approval(
                "session-1",
                f"/approve {pending.request_id}",
            )
        )

    assert response is None
    assert consumed is False
    assert approved_tool_call is None
    with tenant_context(tenant_id="tenant-a", source_id="source-a"):
        assert (await service.get_request(pending.request_id)).status == (
            "pending"
        )
