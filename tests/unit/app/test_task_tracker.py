# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json

import pytest

from swe.app.runner.task_tracker import TaskTracker, _RunState
from swe.app.runner.tool_output_frames import (
    emit_tool_output_text,
    tool_output_invocation,
)


@pytest.mark.asyncio
async def test_request_stop_marks_status_stopping_while_producer_is_cleaning_up():
    tracker = TaskTracker()
    stream_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def _stream_fn(_payload):
        stream_started.set()
        yield 'data: {"started": true}\n\n'
        try:
            while True:
                await asyncio.sleep(1)
                yield 'data: {"tick": true}\n\n'
        finally:
            cleanup_started.set()
            await release_cleanup.wait()

    _queue, is_new = await tracker.attach_or_start(
        "chat-1",
        {},
        _stream_fn,
    )
    assert is_new is True
    await asyncio.wait_for(stream_started.wait(), timeout=1)
    assert await tracker.get_status("chat-1") == "running"

    assert await tracker.request_stop("chat-1") is True
    await asyncio.wait_for(cleanup_started.wait(), timeout=1)

    assert await tracker.get_status("chat-1") == "stopping"

    release_cleanup.set()
    await asyncio.wait_for(tracker.wait_all_done(timeout=1), timeout=2)
    assert await tracker.get_status("chat-1") == "idle"


@pytest.mark.asyncio
async def test_mark_stopping_marks_status_without_cancelling_producer():
    tracker = TaskTracker()
    release_stream = asyncio.Event()

    async def _stream_fn(_payload):
        yield 'data: {"started": true}\n\n'
        await release_stream.wait()

    _queue, is_new = await tracker.attach_or_start(
        "chat-1",
        {},
        _stream_fn,
    )
    assert is_new is True
    await asyncio.sleep(0)
    assert await tracker.get_status("chat-1") == "running"

    await tracker.mark_stopping("chat-1")

    assert await tracker.get_status("chat-1") == "stopping"

    release_stream.set()
    await asyncio.wait_for(tracker.wait_all_done(timeout=1), timeout=2)
    assert await tracker.get_status("chat-1") == "idle"


@pytest.mark.asyncio
async def test_old_run_cleanup_does_not_remove_new_run_state():
    tracker = TaskTracker()
    first_cleanup_started = asyncio.Event()
    release_first_cleanup = asyncio.Event()

    async def _first_stream(_payload):
        yield 'data: {"run": 1}\n\n'
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            first_cleanup_started.set()
            await release_first_cleanup.wait()

    _queue, is_new = await tracker.attach_or_start(
        "chat-1",
        {},
        _first_stream,
    )
    assert is_new is True
    await asyncio.sleep(0)
    assert await tracker.request_stop("chat-1") is True
    await asyncio.wait_for(first_cleanup_started.wait(), timeout=1)
    assert await tracker.get_status("chat-1") == "stopping"

    second_task = asyncio.Future()
    async with tracker.lock:
        tracker._runs["chat-1"] = _RunState(task=second_task)

    assert await tracker.get_status("chat-1") == "running"

    release_first_cleanup.set()
    await asyncio.sleep(0)
    assert await tracker.get_status("chat-1") == "running"

    second_task.set_result(None)
    async with tracker.lock:
        tracker._runs.pop("chat-1", None)
    assert await tracker.get_status("chat-1") == "idle"


@pytest.mark.asyncio
async def test_tool_output_frames_are_buffered_for_active_replay():
    tracker = TaskTracker()
    release_stream = asyncio.Event()

    async def _stream_fn(_payload):
        with tool_output_invocation(
            tool_call_id="call-1",
            tool_name="execute_shell_command",
        ):
            await emit_tool_output_text("stdout", "live output\n")
        yield 'data: {"normal": true}\n\n'
        await release_stream.wait()

    queue, is_new = await tracker.attach_or_start("chat-1", {}, _stream_fn)
    assert is_new is True

    live_sse = await asyncio.wait_for(queue.get(), timeout=1)
    assert live_sse.startswith("data: ")
    live_payload = json.loads(live_sse.removeprefix("data: ").strip())
    assert live_payload == {
        "object": "tool_output_frame",
        "tool_call_id": "call-1",
        "tool_name": "execute_shell_command",
        "sequence": 1,
        "source": "stdout",
        "text": "live output\n",
        "truncated": False,
    }

    replay_queue = await tracker.attach("chat-1")
    assert replay_queue is not None
    replay_sse = await asyncio.wait_for(replay_queue.get(), timeout=1)
    replay_payload = json.loads(replay_sse.removeprefix("data: ").strip())
    assert replay_payload["object"] == "tool_output_frame"
    assert replay_payload["text"] == "live output\n"

    release_stream.set()
    await asyncio.wait_for(tracker.wait_all_done(timeout=1), timeout=2)
