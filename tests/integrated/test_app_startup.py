# -*- coding: utf-8 -*-
"""Integrated tests for SWE app startup and console."""

# pylint:disable=consider-using-with
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import os
from pathlib import Path

import httpx
import pytest


def _find_free_port(host: str = "127.0.0.1") -> int:
    """Bind to portary 0 and return the OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, 0))
        except PermissionError as exc:
            pytest.skip(
                f"Current environment disallows local port binding: {exc}",
            )
        sock.listen(1)
        return sock.getsockname()[1]


def _tee_stream(stream, buffer: list[str]) -> None:
    """Read subprocess output, print it live, and keep a copy."""
    try:
        for line in iter(stream.readline, ""):
            buffer.append(line)
            print(line, end="", flush=True)
    finally:
        stream.close()


def _subprocess_env() -> dict[str, str]:
    """强制子进程从当前 worktree 导入源码。"""
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    pythonpath_parts = [str(root / "src")]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    console_static_dir = _resolve_console_static_dir(root)
    if console_static_dir is None:
        pytest.skip("Console static build not available for startup test")
    env["SWE_CONSOLE_STATIC_DIR"] = str(console_static_dir)
    return env


def _start_app_process(
    host: str,
    port: int,
    env: dict[str, str],
) -> subprocess.Popen[str]:
    """启动待测 app 子进程。"""
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "swe",
            "app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
    )


def _wait_for_backend_ready(
    process: subprocess.Popen[str],
    host: str,
    port: int,
    log_lines: list[str],
) -> None:
    """等待后端启动完成并校验版本接口。"""
    max_wait = 60
    start_time = time.time()
    last_error = None

    with httpx.Client(timeout=5.0, trust_env=False) as client:
        while time.time() - start_time < max_wait:
            if process.poll() is not None:
                logs = "".join(log_lines)[-4000:]
                if "ImportError" in logs or "ModuleNotFoundError" in logs:
                    raise AssertionError(
                        "Failed due to dependency issue:\n" f"{logs}",
                    )
                raise AssertionError(
                    f"Process exited early with code"
                    f" {process.returncode}.\nLogs:\n{logs}",
                )

            try:
                response = client.get(f"http://{host}:{port}/api/version")
                if response.status_code == 200:
                    version_data = response.json()
                    assert "version" in version_data
                    assert isinstance(version_data["version"], str)
                    return
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = str(e)
                time.sleep(1.0)

    logs = "".join(log_lines)[-4000:]
    raise AssertionError(
        "Backend did not start within timeout period. "
        f"Last error: {last_error}\n"
        f"Logs:\n{logs}",
    )


def _stop_app_process(
    process: subprocess.Popen[str],
    log_thread: threading.Thread,
) -> None:
    """停止待测 app 子进程并回收日志线程。"""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    log_thread.join(timeout=2)


def _resolve_console_static_dir(root: Path) -> Path | None:
    """解析可用于启动测试的 console 静态目录。"""
    candidates = [root / "console" / "dist"]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
            cwd=root,
        )
    except (OSError, subprocess.CalledProcessError):
        result = None

    if result is not None:
        common_dir = Path(result.stdout.strip())
        if not common_dir.is_absolute():
            common_dir = (root / common_dir).resolve()
        shared_root = common_dir.parent
        candidates.append(shared_root / "console" / "dist")

    for candidate in candidates:
        index_path = candidate / "index.html"
        if candidate.is_dir() and index_path.is_file():
            return candidate
    return None


def test_app_startup_and_console() -> None:
    """Test that swe app starts correctly with backend and console."""
    host = "127.0.0.1"
    port = _find_free_port(host)
    log_lines: list[str] = []

    process = _start_app_process(host, port, _subprocess_env())

    assert process.stdout is not None

    log_thread = threading.Thread(
        target=_tee_stream,
        args=(process.stdout, log_lines),
        daemon=True,
    )
    log_thread.start()

    try:
        _wait_for_backend_ready(process, host, port, log_lines)

        with httpx.Client(timeout=5.0, trust_env=False) as client:
            console_response = client.get(f"http://{host}:{port}/console/")
            assert (
                console_response.status_code == 200
            ), f"Console not accessible: {console_response.status_code}"

            assert (
                "text/html"
                in console_response.headers.get("content-type", "").lower()
            ), "Console should return HTML content"

            html_content = console_response.text
            assert len(html_content) > 0, "Console HTML should not be empty"
            assert (
                "<!doctype html>" in html_content.lower()
                or "<html" in html_content.lower()
            ), "Console should return valid HTML"

    finally:
        _stop_app_process(process, log_thread)


def test_app_startup_uses_stdout_stderr_logging(tmp_path: Path) -> None:
    """应用启动应通过 stdout/stderr 输出日志，不再暴露 swe.log 开关。"""
    host = "127.0.0.1"
    port = _find_free_port(host)
    log_lines: list[str] = []
    working_dir = tmp_path / "working"
    env = _subprocess_env()
    env["SWE_WORKING_DIR"] = str(working_dir)
    process = _start_app_process(host, port, env)

    assert process.stdout is not None

    log_thread = threading.Thread(
        target=_tee_stream,
        args=(process.stdout, log_lines),
        daemon=True,
    )
    log_thread.start()

    try:
        _wait_for_backend_ready(process, host, port, log_lines)
        logs = "".join(log_lines)
        assert "Performing minimal startup" in logs
        assert "SWE_FILE_LOG_ENABLED" not in logs
    finally:
        _stop_app_process(process, log_thread)
