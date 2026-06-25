# -*- coding: utf-8 -*-
"""Live presentation frames for running tool output."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterator, Literal

ToolOutputSource = Literal["stdout", "stderr", "message"]
ToolOutputFrame = dict[str, Any]
ToolOutputEmitter = Callable[[ToolOutputFrame], Awaitable[None]]

LIVE_TOOL_OUTPUT_MAX_BYTES = 64 * 1024
LIVE_TOOL_OUTPUT_MAX_LINES = 2000
LIVE_TOOL_OUTPUT_OMISSION_TEXT = "\n[早期实时输出已省略]\n"

_LIVE_OUTPUT_TOOL_ALLOWLIST = frozenset({"execute_shell_command"})


@dataclass
class _ToolOutputInvocation:
    tool_call_id: str
    tool_name: str
    sequence: int = 0
    emitted_bytes: int = 0
    emitted_lines: int = 0
    truncated: bool = False


_emitter_var: ContextVar[ToolOutputEmitter | None] = ContextVar(
    "tool_output_frame_emitter",
    default=None,
)
_invocation_var: ContextVar[_ToolOutputInvocation | None] = ContextVar(
    "tool_output_frame_invocation",
    default=None,
)


@contextmanager
def bind_tool_output_emitter(
    emitter: ToolOutputEmitter,
) -> Iterator[None]:
    """Bind the live output frame emitter for the current execution context."""
    token = _emitter_var.set(emitter)
    try:
        yield
    finally:
        _emitter_var.reset(token)


@contextmanager
def tool_output_invocation(
    *,
    tool_call_id: str,
    tool_name: str,
) -> Iterator[None]:
    """Bind the currently executing tool invocation for live output frames."""
    token = _invocation_var.set(
        _ToolOutputInvocation(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        ),
    )
    try:
        yield
    finally:
        _invocation_var.reset(token)


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + int(not text.endswith("\n"))


def _bounded_text(
    state: _ToolOutputInvocation,
    text: str,
) -> tuple[str, bool]:
    if state.truncated:
        return "", False

    remaining_bytes = LIVE_TOOL_OUTPUT_MAX_BYTES - state.emitted_bytes
    remaining_lines = LIVE_TOOL_OUTPUT_MAX_LINES - state.emitted_lines
    if remaining_bytes <= 0 or remaining_lines <= 0:
        state.truncated = True
        return LIVE_TOOL_OUTPUT_OMISSION_TEXT, True

    encoded = text.encode("utf-8", errors="replace")
    truncated = False
    if len(encoded) > remaining_bytes:
        encoded = encoded[:remaining_bytes]
        text = encoded.decode("utf-8", errors="replace")
        truncated = True

    lines = text.splitlines(keepends=True)
    if len(lines) > remaining_lines:
        text = "".join(lines[:remaining_lines])
        truncated = True

    if truncated:
        state.truncated = True
        text += LIVE_TOOL_OUTPUT_OMISSION_TEXT

    return text, truncated


async def emit_tool_output_text(
    source: ToolOutputSource,
    text: str,
) -> None:
    """Emit a guarded live output frame when the current context supports it."""
    if not text:
        return

    emitter = _emitter_var.get()
    state = _invocation_var.get()
    if emitter is None or state is None:
        return
    if state.tool_name not in _LIVE_OUTPUT_TOOL_ALLOWLIST:
        return

    frame_text, truncated = _bounded_text(state, text)
    if not frame_text:
        return

    state.sequence += 1
    state.emitted_bytes += len(frame_text.encode("utf-8", errors="replace"))
    state.emitted_lines += _line_count(frame_text)

    await emitter(
        {
            "object": "tool_output_frame",
            "tool_call_id": state.tool_call_id,
            "tool_name": state.tool_name,
            "sequence": state.sequence,
            "source": source,
            "text": frame_text,
            "truncated": truncated,
        },
    )
