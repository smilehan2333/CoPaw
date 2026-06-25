# -*- coding: utf-8 -*-
"""Tests for process-local runtime diagnostic collection."""

from __future__ import annotations

import asyncio
import json

import pytest
from swe.app import runtime_diagnostic
from swe.app.runtime_diagnostic import RuntimeDiagnosticManager


class _Process:
    def __init__(self) -> None:
        self.cpu_values = iter([0.0, 25.0])

    def cpu_percent(self) -> float:
        return next(self.cpu_values)

    def memory_info(self):
        return type("Memory", (), {"rss": 100, "vms": 200})()

    def num_threads(self) -> int:
        return 3

    def num_fds(self) -> int:
        return 4

    def create_time(self) -> float:
        return 900.0


class _BrokenProcess(_Process):
    def memory_info(self):
        raise RuntimeError("memory unavailable")


class _PartiallyBrokenProcess(_Process):
    def memory_info(self):
        class _Memory:
            @property
            def rss(self):
                raise RuntimeError("rss unavailable")

            vms = 200

        return _Memory()

    def num_threads(self) -> int:
        raise RuntimeError("threads unavailable")


def _disk_usage(_path: str):
    return type(
        "Disk",
        (),
        {"total": 1000, "used": 600, "free": 400, "percent": 60.0},
    )()


def _payload(message: str) -> dict[str, object]:
    prefix = "RUNTIME_DIAGNOSTIC "
    assert message.startswith(prefix)
    return json.loads(message.removeprefix(prefix))


def _manager(**overrides) -> RuntimeDiagnosticManager:
    messages: list[str] = overrides.pop("messages", [])
    options = {
        "hostname": "pod-a",
        "wall_time": lambda: 1000.0,
        "process": _Process(),
        "disk_usage": _disk_usage,
        "pod_open_fd_count": lambda: 6,
        "pod_disk_io_bytes": lambda: (100, 200),
        "log_sink": messages.append,
    }
    options.update(overrides)
    return RuntimeDiagnosticManager(
        **options,
    )


def test_lifecycle_events_use_flat_versioned_contract() -> None:
    messages: list[str] = []
    manager = _manager(messages=messages)

    manager.emit_registered()
    manager.emit_deregistered()

    assert _payload(messages[0]) == {
        "schema": "runtime_diagnostic.v1",
        "event_type": "instance_registered",
        "hostname": "pod-a",
        "event_at_ms": 1000000,
    }
    assert _payload(messages[1]) == {
        "schema": "runtime_diagnostic.v1",
        "event_type": "instance_deregistered",
        "hostname": "pod-a",
        "event_at_ms": 1000000,
    }


def test_diagnostic_payload_contains_confirmed_metrics() -> None:
    manager = _manager()
    manager.record_sse_opened()
    manager.record_sse_opened()
    manager.record_sse_closed()
    manager.record_sample(lag_ms=10.0, cpu_percent=20.0)
    manager.record_sample(lag_ms=1200.0, cpu_percent=40.0)

    payload = manager.build_diagnostic_payload()

    assert payload == {
        "schema": "runtime_diagnostic.v1",
        "event_type": "diagnostic_flow",
        "hostname": "pod-a",
        "event_at_ms": 1000000,
        "sse_active_connections": 1,
        "sse_peak_connections": 2,
        "event_loop_lag_avg_ms": 605.0,
        "event_loop_lag_p95_ms": 1200.0,
        "event_loop_lag_max_ms": 1200.0,
        "event_loop_blocked_count": 1,
        "process_cpu_avg_percent": 30.0,
        "process_cpu_max_percent": 40.0,
        "process_rss_bytes": 100,
        "process_vms_bytes": 200,
        "process_thread_count": 3,
        "process_open_fd_count": 4,
        "process_uptime_seconds": 100,
        "pod_open_fd_count": 6,
        "pod_disk_read_bytes_per_second": None,
        "pod_disk_read_bytes_per_second_peak": None,
        "pod_disk_write_bytes_per_second": None,
        "pod_disk_write_bytes_per_second_peak": None,
        "storage_total_bytes": 1000,
        "storage_used_bytes": 600,
        "storage_free_bytes": 400,
        "storage_used_percent": 60.0,
    }


def test_failed_metric_group_emits_null_fields_without_suppressing_payload() -> (
    None
):
    manager = _manager(
        process=_BrokenProcess(),
        disk_usage=lambda _path: (_ for _ in ()).throw(
            RuntimeError("disk unavailable"),
        ),
    )

    payload = manager.build_diagnostic_payload()

    assert payload["process_rss_bytes"] is None
    assert payload["process_vms_bytes"] is None
    assert payload["process_thread_count"] == 3
    assert payload["process_open_fd_count"] == 4
    assert payload["process_uptime_seconds"] == 100
    assert payload["storage_total_bytes"] is None
    assert payload["storage_used_bytes"] is None
    assert payload["storage_free_bytes"] is None
    assert payload["storage_used_percent"] is None
    assert payload["sse_active_connections"] == 0


def test_failed_process_fields_do_not_suppress_other_process_fields() -> None:
    manager = _manager(process=_PartiallyBrokenProcess())

    payload = manager.build_diagnostic_payload()

    assert payload["process_rss_bytes"] is None
    assert payload["process_vms_bytes"] == 200
    assert payload["process_thread_count"] is None
    assert payload["process_open_fd_count"] == 4
    assert payload["process_uptime_seconds"] == 100


def test_pod_disk_io_reports_latest_and_peak_rates() -> None:
    manager = _manager()
    manager.record_sample(
        lag_ms=1.0,
        cpu_percent=1.0,
        pod_disk_io_bytes=(100, 200),
        sampled_at=10.0,
    )
    manager.record_sample(
        lag_ms=1.0,
        cpu_percent=1.0,
        pod_disk_io_bytes=(300, 500),
        sampled_at=11.0,
    )
    manager.record_sample(
        lag_ms=1.0,
        cpu_percent=1.0,
        pod_disk_io_bytes=(500, 900),
        sampled_at=13.0,
    )

    payload = manager.build_diagnostic_payload()

    assert payload["pod_disk_read_bytes_per_second"] == 100.0
    assert payload["pod_disk_read_bytes_per_second_peak"] == 200.0
    assert payload["pod_disk_write_bytes_per_second"] == 200.0
    assert payload["pod_disk_write_bytes_per_second_peak"] == 300.0


def test_failed_pod_metrics_emit_null_without_suppressing_other_fields() -> (
    None
):
    manager = _manager(
        pod_open_fd_count=lambda: (_ for _ in ()).throw(
            PermissionError("fd unavailable"),
        ),
    )
    manager.record_sample(
        lag_ms=1.0,
        cpu_percent=1.0,
        pod_disk_io_bytes=(100, 200),
        sampled_at=10.0,
    )
    manager.record_sample(
        lag_ms=1.0,
        cpu_percent=1.0,
        pod_disk_io_bytes=None,
        sampled_at=11.0,
    )

    payload = manager.build_diagnostic_payload()

    assert payload["pod_open_fd_count"] is None
    assert payload["pod_disk_read_bytes_per_second"] is None
    assert payload["pod_disk_read_bytes_per_second_peak"] is None
    assert payload["pod_disk_write_bytes_per_second"] is None
    assert payload["pod_disk_write_bytes_per_second_peak"] is None
    assert payload["process_rss_bytes"] == 100


def test_window_rotation_preserves_active_sse_and_clears_samples() -> None:
    manager = _manager()
    manager.record_sse_opened()
    manager.record_sse_opened()
    manager.record_sse_closed()
    manager.record_sample(
        lag_ms=100.0,
        cpu_percent=50.0,
        pod_disk_io_bytes=(100, 200),
        sampled_at=10.0,
    )
    manager.record_sample(
        lag_ms=100.0,
        cpu_percent=50.0,
        pod_disk_io_bytes=(200, 400),
        sampled_at=11.0,
    )

    manager.rotate_window()
    manager.record_sample(
        lag_ms=100.0,
        cpu_percent=50.0,
        pod_disk_io_bytes=(500, 1000),
        sampled_at=13.0,
    )
    payload = manager.build_diagnostic_payload()

    assert payload["sse_active_connections"] == 1
    assert payload["sse_peak_connections"] == 1
    assert payload["event_loop_lag_avg_ms"] == 100.0
    assert payload["event_loop_lag_p95_ms"] == 100.0
    assert payload["event_loop_lag_max_ms"] == 100.0
    assert payload["event_loop_blocked_count"] == 0
    assert payload["process_cpu_avg_percent"] == 50.0
    assert payload["process_cpu_max_percent"] == 50.0
    assert payload["pod_disk_read_bytes_per_second"] == 150.0
    assert payload["pod_disk_read_bytes_per_second_peak"] == 150.0
    assert payload["pod_disk_write_bytes_per_second"] == 300.0
    assert payload["pod_disk_write_bytes_per_second_peak"] == 300.0


@pytest.mark.asyncio
async def test_start_and_stop_emit_lifecycle_events() -> None:
    messages: list[str] = []
    manager = _manager(messages=messages)

    await manager.start()
    await manager.stop()

    assert _payload(messages[0])["event_type"] == "instance_registered"
    assert _payload(messages[-1])["event_type"] == "instance_deregistered"


@pytest.mark.asyncio
async def test_sample_once_records_event_loop_lag_and_process_cpu() -> None:
    manager = _manager(monotonic_time=lambda: 11.25)

    manager.prime_process_cpu()
    await manager.sample_once(planned_wakeup=10.0)
    payload = manager.build_diagnostic_payload()

    assert payload["event_loop_lag_avg_ms"] == 1250.0
    assert payload["event_loop_blocked_count"] == 1
    assert payload["process_cpu_avg_percent"] == 25.0


@pytest.mark.asyncio
async def test_sample_once_latches_pod_disk_io_collection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    exception_logs: list[str] = []

    def unavailable_pod_disk_io_bytes() -> tuple[int, int]:
        nonlocal calls
        calls += 1
        raise OSError("cgroup io counters unavailable")

    monkeypatch.setattr(
        runtime_diagnostic.logger,
        "exception",
        lambda message, *args: exception_logs.append(
            message % args if args else message,
        ),
    )
    manager = _manager(
        monotonic_time=lambda: 11.0,
        pod_disk_io_bytes=unavailable_pod_disk_io_bytes,
    )

    await manager.sample_once(planned_wakeup=10.0)
    await manager.sample_once(planned_wakeup=11.0)

    payload = manager.build_diagnostic_payload()

    assert calls == 1
    assert exception_logs == [
        "Failed to collect runtime diagnostic Pod disk I/O",
    ]
    assert payload["pod_disk_read_bytes_per_second"] is None
    assert payload["pod_disk_read_bytes_per_second_peak"] is None
    assert payload["pod_disk_write_bytes_per_second"] is None
    assert payload["pod_disk_write_bytes_per_second_peak"] is None


@pytest.mark.asyncio
async def test_sampler_loop_uses_ten_second_interval() -> None:
    sleeps: list[float] = []
    planned_wakeups: list[float] = []
    now = 100.0

    async def fake_sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    manager = _manager(
        monotonic_time=lambda: now,
        sleep=fake_sleep,
    )

    async def fake_sample_once(*, planned_wakeup: float) -> None:
        planned_wakeups.append(planned_wakeup)

    manager.sample_once = fake_sample_once  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await manager.run_sampler_loop()

    assert sleeps == [10.0, 10.0, 10.0]
    assert planned_wakeups == [110.0, 120.0]


@pytest.mark.asyncio
async def test_periodic_loop_uses_initial_jitter_then_regular_interval() -> (
    None
):
    sleeps: list[float] = []
    messages: list[str] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    manager = _manager(
        messages=messages,
        sleep=fake_sleep,
        jitter=lambda _start, _end: 7.0,
    )

    with pytest.raises(asyncio.CancelledError):
        await manager.run_periodic_loop()

    assert sleeps == [127.0, 1800.0]
    assert [_payload(message)["event_type"] for message in messages] == [
        "diagnostic_flow",
    ]
