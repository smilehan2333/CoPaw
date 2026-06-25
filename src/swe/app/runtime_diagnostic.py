# -*- coding: utf-8 -*-
"""Process-local runtime diagnostic metric collection and logging."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import time
from collections.abc import Callable
from typing import Any

import psutil

from swe.app.pod_resources import (
    collect_pod_disk_io_bytes,
    collect_pod_open_fd_count,
)

logger = logging.getLogger(__name__)

_LOG_PREFIX = "RUNTIME_DIAGNOSTIC "
_SCHEMA = "runtime_diagnostic.v1"
_STORAGE_PATH = "/opt/deployments/app"
_BLOCKED_LAG_THRESHOLD_MS = 1000.0
_SAMPLE_INTERVAL_SECONDS = 10.0
_FIRST_DIAGNOSTIC_DELAY_SECONDS = 120.0
_FIRST_DIAGNOSTIC_JITTER_SECONDS = 10.0
_DIAGNOSTIC_INTERVAL_SECONDS = 1800.0


def _percentile(values: list[float], percentile: float) -> float | None:
    """Return a deterministic nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


class RuntimeDiagnosticManager:
    """Collect and emit Runtime Instance diagnostic metrics."""

    def __init__(
        self,
        *,
        hostname: str | None = None,
        wall_time: Callable[[], float] = time.time,
        process: Any | None = None,
        disk_usage: Callable[[str], Any] = psutil.disk_usage,
        pod_open_fd_count: Callable[[], int] = collect_pod_open_fd_count,
        pod_disk_io_bytes: Callable[
            [],
            tuple[int, int],
        ] = collect_pod_disk_io_bytes,
        log_sink: Callable[[str], None] | None = None,
        monotonic_time: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.hostname = (
            hostname
            if hostname is not None
            else os.environ.get(
                "HOSTNAME",
                "",
            )
        )
        self._wall_time = wall_time
        self._process = process if process is not None else psutil.Process()
        self._disk_usage = disk_usage
        self._pod_open_fd_count = pod_open_fd_count
        self._pod_disk_io_bytes = pod_disk_io_bytes
        self._log_sink = log_sink or logger.info
        self._monotonic_time = monotonic_time
        self._sleep = sleep
        self._jitter = jitter

        self._sse_active_connections = 0
        self._sse_peak_connections = 0
        self._event_loop_lag_samples: list[float] = []
        self._event_loop_blocked_count = 0
        self._process_cpu_samples: list[float] = []
        self._previous_pod_disk_io_bytes: tuple[int, int] | None = None
        self._previous_pod_disk_io_at: float | None = None
        self._pod_disk_io_collection_failed = False
        self._pod_disk_io_valid = True
        self._pod_disk_read_bytes_per_second: float | None = None
        self._pod_disk_read_bytes_per_second_peak: float | None = None
        self._pod_disk_write_bytes_per_second: float | None = None
        self._pod_disk_write_bytes_per_second_peak: float | None = None
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def record_sse_opened(self) -> None:
        """Record one newly active SSE connection."""
        self._sse_active_connections += 1
        self._sse_peak_connections = max(
            self._sse_peak_connections,
            self._sse_active_connections,
        )

    def record_sse_closed(self) -> None:
        """Record one completed SSE connection."""
        self._sse_active_connections = max(0, self._sse_active_connections - 1)

    def record_sample(
        self,
        *,
        lag_ms: float,
        cpu_percent: float | None,
        pod_disk_io_bytes: tuple[int, int] | None = None,
        sampled_at: float | None = None,
    ) -> None:
        """Record one event-loop and process CPU sample."""
        self._event_loop_lag_samples.append(max(0.0, lag_ms))
        if lag_ms > _BLOCKED_LAG_THRESHOLD_MS:
            self._event_loop_blocked_count += 1
        if cpu_percent is not None:
            self._process_cpu_samples.append(cpu_percent)
        self._record_pod_disk_io_sample(
            pod_disk_io_bytes=pod_disk_io_bytes,
            sampled_at=sampled_at,
        )

    def _record_pod_disk_io_sample(
        self,
        *,
        pod_disk_io_bytes: tuple[int, int] | None,
        sampled_at: float | None,
    ) -> None:
        if pod_disk_io_bytes is None or sampled_at is None:
            self._pod_disk_io_valid = False
            self._previous_pod_disk_io_bytes = None
            self._previous_pod_disk_io_at = None
            return

        if (
            self._previous_pod_disk_io_bytes is not None
            and self._previous_pod_disk_io_at is not None
        ):
            elapsed = sampled_at - self._previous_pod_disk_io_at
            read_delta = (
                pod_disk_io_bytes[0] - self._previous_pod_disk_io_bytes[0]
            )
            write_delta = (
                pod_disk_io_bytes[1] - self._previous_pod_disk_io_bytes[1]
            )
            if elapsed <= 0 or read_delta < 0 or write_delta < 0:
                self._pod_disk_io_valid = False
            else:
                read_rate = read_delta / elapsed
                write_rate = write_delta / elapsed
                self._pod_disk_read_bytes_per_second = read_rate
                self._pod_disk_write_bytes_per_second = write_rate
                self._pod_disk_read_bytes_per_second_peak = max(
                    self._pod_disk_read_bytes_per_second_peak or 0.0,
                    read_rate,
                )
                self._pod_disk_write_bytes_per_second_peak = max(
                    self._pod_disk_write_bytes_per_second_peak or 0.0,
                    write_rate,
                )

        self._previous_pod_disk_io_bytes = pod_disk_io_bytes
        self._previous_pod_disk_io_at = sampled_at

    def rotate_window(self) -> None:
        """Reset window metrics while preserving active SSE connections."""
        self._sse_peak_connections = self._sse_active_connections
        self._event_loop_lag_samples.clear()
        self._event_loop_blocked_count = 0
        self._process_cpu_samples.clear()
        self._pod_disk_io_valid = True
        self._pod_disk_read_bytes_per_second = None
        self._pod_disk_read_bytes_per_second_peak = None
        self._pod_disk_write_bytes_per_second = None
        self._pod_disk_write_bytes_per_second_peak = None

    def prime_process_cpu(self) -> None:
        """Prime psutil's non-blocking process CPU measurement."""
        try:
            self._process.cpu_percent()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to prime runtime diagnostic process CPU")

    async def sample_once(self, *, planned_wakeup: float) -> None:
        """Record one event-loop lag and process CPU sample."""
        sampled_at = self._monotonic_time()
        lag_ms = max(0.0, (sampled_at - planned_wakeup) * 1000)
        cpu_percent = None
        pod_disk_io_bytes = None
        try:
            cpu_percent = float(self._process.cpu_percent())
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Failed to collect runtime diagnostic process CPU",
            )
        if not self._pod_disk_io_collection_failed:
            try:
                pod_disk_io_bytes = self._pod_disk_io_bytes()
            except Exception:  # pylint: disable=broad-except
                self._pod_disk_io_collection_failed = True
                logger.exception(
                    "Failed to collect runtime diagnostic Pod disk I/O",
                )
        self.record_sample(
            lag_ms=lag_ms,
            cpu_percent=cpu_percent,
            pod_disk_io_bytes=pod_disk_io_bytes,
            sampled_at=sampled_at,
        )

    async def run_sampler_loop(self) -> None:
        """Sample event-loop lag and process CPU at a fixed interval."""
        planned_wakeup = self._monotonic_time() + _SAMPLE_INTERVAL_SECONDS
        while True:
            await self._sleep(
                max(0.0, planned_wakeup - self._monotonic_time()),
            )
            try:
                await self.sample_once(planned_wakeup=planned_wakeup)
            except asyncio.CancelledError:
                raise
            except Exception:  # pylint: disable=broad-except
                logger.exception("Runtime diagnostic sampler iteration failed")
            planned_wakeup += _SAMPLE_INTERVAL_SECONDS

    async def run_periodic_loop(self) -> None:
        """Emit the first delayed diagnostic, then one every 30 minutes."""
        initial_delay = _FIRST_DIAGNOSTIC_DELAY_SECONDS + self._jitter(
            0.0,
            _FIRST_DIAGNOSTIC_JITTER_SECONDS,
        )
        await self._sleep(initial_delay)
        while True:
            try:
                self.emit_diagnostic()
            except asyncio.CancelledError:
                raise
            except Exception:  # pylint: disable=broad-except
                logger.exception("Runtime diagnostic emission failed")
            await self._sleep(_DIAGNOSTIC_INTERVAL_SECONDS)

    async def start(self) -> None:
        """Emit registration and start background diagnostic tasks."""
        if self._running:
            return
        if not self.hostname:
            logger.error("Runtime diagnostic disabled: HOSTNAME is missing")
            return
        self._running = True
        self.emit_registered()
        self.prime_process_cpu()
        self._tasks = [
            asyncio.create_task(
                self.run_sampler_loop(),
                name="runtime-diagnostic-sampler",
            ),
            asyncio.create_task(
                self.run_periodic_loop(),
                name="runtime-diagnostic-emitter",
            ),
        ]

    async def stop(self) -> None:
        """Stop background tasks and emit graceful deregistration."""
        if not self._running:
            return
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self.emit_deregistered()

    def _base_payload(self, event_type: str) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "event_type": event_type,
            "hostname": self.hostname,
            "event_at_ms": int(self._wall_time() * 1000),
        }

    def _process_metrics(self) -> dict[str, object]:
        metrics: dict[str, object] = {
            "process_rss_bytes": None,
            "process_vms_bytes": None,
            "process_thread_count": None,
            "process_open_fd_count": None,
            "process_uptime_seconds": None,
        }
        try:
            memory = self._process.memory_info()
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Failed to collect runtime diagnostic process memory",
            )
        else:
            for field, attribute in (
                ("process_rss_bytes", "rss"),
                ("process_vms_bytes", "vms"),
            ):
                try:
                    metrics[field] = int(getattr(memory, attribute))
                except Exception:  # pylint: disable=broad-except
                    logger.exception(
                        "Failed to collect runtime diagnostic metric %s",
                        field,
                    )

        collectors = {
            "process_thread_count": lambda: int(self._process.num_threads()),
            "process_open_fd_count": lambda: int(self._process.num_fds()),
            "process_uptime_seconds": lambda: max(
                0,
                int(self._wall_time() - self._process.create_time()),
            ),
        }
        for field, collect in collectors.items():
            try:
                metrics[field] = collect()
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "Failed to collect runtime diagnostic metric %s",
                    field,
                )
        return metrics

    def _storage_metrics(self) -> dict[str, object]:
        empty: dict[str, object] = {
            "storage_total_bytes": None,
            "storage_used_bytes": None,
            "storage_free_bytes": None,
            "storage_used_percent": None,
        }
        try:
            usage = self._disk_usage(_STORAGE_PATH)
            return {
                "storage_total_bytes": int(usage.total),
                "storage_used_bytes": int(usage.used),
                "storage_free_bytes": int(usage.free),
                "storage_used_percent": float(usage.percent),
            }
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Failed to collect runtime diagnostic storage metrics",
            )
            return empty

    def _pod_metrics(self) -> dict[str, object]:
        try:
            pod_open_fd_count = self._pod_open_fd_count()
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Failed to collect runtime diagnostic Pod open file descriptors",
            )
            pod_open_fd_count = None

        disk_metrics: dict[str, object] = {
            "pod_disk_read_bytes_per_second": None,
            "pod_disk_read_bytes_per_second_peak": None,
            "pod_disk_write_bytes_per_second": None,
            "pod_disk_write_bytes_per_second_peak": None,
        }
        if self._pod_disk_io_valid:
            disk_metrics.update(
                {
                    "pod_disk_read_bytes_per_second": (
                        self._pod_disk_read_bytes_per_second
                    ),
                    "pod_disk_read_bytes_per_second_peak": (
                        self._pod_disk_read_bytes_per_second_peak
                    ),
                    "pod_disk_write_bytes_per_second": (
                        self._pod_disk_write_bytes_per_second
                    ),
                    "pod_disk_write_bytes_per_second_peak": (
                        self._pod_disk_write_bytes_per_second_peak
                    ),
                },
            )
        return {"pod_open_fd_count": pod_open_fd_count, **disk_metrics}

    def build_diagnostic_payload(self) -> dict[str, object]:
        """Build the current flat diagnostic-flow payload."""
        lag_samples = self._event_loop_lag_samples
        cpu_samples = self._process_cpu_samples
        payload = self._base_payload("diagnostic_flow")
        payload.update(
            {
                "sse_active_connections": self._sse_active_connections,
                "sse_peak_connections": self._sse_peak_connections,
                "event_loop_lag_avg_ms": (
                    sum(lag_samples) / len(lag_samples)
                    if lag_samples
                    else None
                ),
                "event_loop_lag_p95_ms": _percentile(lag_samples, 0.95),
                "event_loop_lag_max_ms": (
                    max(lag_samples) if lag_samples else None
                ),
                "event_loop_blocked_count": self._event_loop_blocked_count,
                "process_cpu_avg_percent": (
                    sum(cpu_samples) / len(cpu_samples)
                    if cpu_samples
                    else None
                ),
                "process_cpu_max_percent": (
                    max(cpu_samples) if cpu_samples else None
                ),
            },
        )
        payload.update(self._process_metrics())
        payload.update(self._pod_metrics())
        payload.update(self._storage_metrics())
        return payload

    def _emit(self, payload: dict[str, object]) -> None:
        self._log_sink(
            _LOG_PREFIX
            + json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

    def emit_registered(self) -> None:
        """Emit one Runtime Instance registration event."""
        self._emit(self._base_payload("instance_registered"))

    def emit_diagnostic(self) -> None:
        """Emit one diagnostic-flow event and rotate its metric window."""
        self._emit(self.build_diagnostic_payload())
        self.rotate_window()

    def emit_deregistered(self) -> None:
        """Emit one Runtime Instance deregistration event."""
        self._emit(self._base_payload("instance_deregistered"))
