"""校验 Daemon 审批命令的用户可见文案。"""

from __future__ import annotations

import pytest

from swe.app.approvals.service import ApprovalService
from swe.app.runner import daemon_commands


@pytest.mark.asyncio
async def test_daemon_approve_reports_missing_pending_in_chinese(
    monkeypatch,
) -> None:
    service = ApprovalService()
    monkeypatch.setattr(
        "swe.app.approvals.service._approval_service",
        service,
    )

    message = await daemon_commands.run_daemon_approve(
        daemon_commands.DaemonContext(),
        session_id="session-1",
    )

    assert message == (
        "**没有待审批请求**\n\n"
        "- 当前会话没有等待处理的工具审批。\n"
        "- 该命令仅在敏感工具调用等待你审核时有效。"
    )
