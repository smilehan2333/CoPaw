# -*- coding: utf-8 -*-
"""定时任务在“我的任务”视图中的暂停状态回归测试。"""

from __future__ import annotations

from swe.app.crons.manager import (
    AUTO_PAUSE_REASON,
    MANUAL_PAUSE_REASON,
    CronManager,
)
from swe.app.crons.models import (
    CronJobRequest,
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    ScheduleSpec,
)


def _build_job(
    *,
    enabled: bool,
    user_id: str = "user-1",
    meta: dict[str, object] | None = None,
) -> CronJobSpec:
    return CronJobSpec(
        id="job-1",
        name="daily report",
        enabled=enabled,
        schedule=ScheduleSpec(cron="0 9 * * mon-fri"),
        task_type="agent",
        request=CronJobRequest(
            input="run report",
            session_id="session-1",
            user_id=user_id,
        ),
        dispatch=DispatchSpec(
            target=DispatchTarget(
                user_id=user_id,
                session_id="session-1",
            ),
        ),
        meta={
            "creator_user_id": user_id,
            **(meta or {}),
        },
    )


def _build_manager() -> CronManager:
    manager = object.__new__(CronManager)
    manager._states = {}  # pylint: disable=protected-access
    return manager


def test_disabled_visible_task_without_pause_reason_is_manual_paused():
    job = _build_job(enabled=False)
    manager = _build_manager()

    task = manager.build_task_view(job, "user-1")

    assert task.visible_in_my_tasks is True
    assert task.is_paused is True
    assert task.pause_reason == MANUAL_PAUSE_REASON
    assert "pause_reason" not in job.meta


def test_task_view_preserves_explicit_pause_reason():
    job = _build_job(
        enabled=False,
        meta={"pause_reason": AUTO_PAUSE_REASON},
    )
    manager = _build_manager()

    task = manager.build_task_view(job, "user-1")

    assert task.is_paused is True
    assert task.pause_reason == AUTO_PAUSE_REASON


def test_disabled_task_for_other_user_is_not_marked_manual_paused():
    job = _build_job(enabled=False, user_id="user-1")
    manager = _build_manager()

    task = manager.build_task_view(job, "user-2")

    assert task.visible_in_my_tasks is False
    assert task.is_paused is False
    assert task.pause_reason is None
