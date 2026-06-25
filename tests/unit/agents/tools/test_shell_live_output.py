# -*- coding: utf-8 -*-
import asyncio
import os
import signal
import sys

import pytest


@pytest.mark.asyncio
async def test_unix_shell_emits_live_stdout_and_stderr_frames(tmp_path):
    if sys.platform == "win32":
        pytest.skip("Unix subprocess live output is not used on Windows")

    from swe.agents.tools import shell
    from swe.app.runner.tool_output_frames import (
        bind_tool_output_emitter,
        tool_output_invocation,
    )

    frames = []

    async def collect(frame):
        frames.append(frame)

    with (
        bind_tool_output_emitter(collect),
        tool_output_invocation(
            tool_call_id="call-1",
            tool_name="execute_shell_command",
        ),
    ):
        returncode, stdout, stderr = await shell._execute_unix_subprocess(
            "printf 'out-line\\n'; printf 'err-line\\n' >&2",
            tmp_path,
            5,
            os.environ.copy(),
        )

    assert returncode == 0
    assert stdout == "out-line"
    assert stderr == "err-line"

    assert {frame["source"] for frame in frames} == {"stdout", "stderr"}
    assert {frame["text"] for frame in frames} == {"out-line\n", "err-line\n"}
    assert all(frame["object"] == "tool_output_frame" for frame in frames)
    assert all(frame["tool_call_id"] == "call-1" for frame in frames)
    assert all(
        frame["tool_name"] == "execute_shell_command" for frame in frames
    )
    assert [frame["sequence"] for frame in frames] == [1, 2]


@pytest.mark.asyncio
async def test_unix_shell_timeout_covers_background_pipe_holders(tmp_path):
    if sys.platform == "win32":
        pytest.skip("Unix subprocess live output is not used on Windows")

    from swe.agents.tools import shell

    returncode, stdout, stderr = await asyncio.wait_for(
        shell._execute_unix_subprocess(
            "sleep 2 & echo done",
            tmp_path,
            0.1,
            os.environ.copy(),
        ),
        timeout=1,
    )

    assert returncode == -1
    assert stdout == "done"
    assert "TimeoutError" in stderr


@pytest.mark.asyncio
async def test_unix_shell_timeout_kills_sigterm_ignoring_pipe_holders(
    tmp_path,
):
    if sys.platform == "win32":
        pytest.skip("Unix subprocess live output is not used on Windows")

    from swe.agents.tools import shell

    pid_file = tmp_path / "background.pid"
    background_pid: int | None = None
    try:
        returncode, stdout, stderr = await asyncio.wait_for(
            shell._execute_unix_subprocess(
                (
                    "trap '' TERM; "
                    "while :; do sleep 1; done & "
                    f"echo $! > {pid_file}; "
                    "echo done"
                ),
                tmp_path,
                0.1,
                os.environ.copy(),
            ),
            timeout=4,
        )

        background_pid = int(pid_file.read_text().strip())

        assert returncode == -1
        assert stdout == "done"
        assert "TimeoutError" in stderr
        with pytest.raises(ProcessLookupError):
            os.kill(background_pid, 0)
    finally:
        if background_pid is not None:
            try:
                os.killpg(os.getpgid(background_pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
