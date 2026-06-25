# -*- coding: utf-8 -*-
from __future__ import annotations

from swe.agents.hook_runtime.conversation_snapshot import (
    _normalize_content,
    _sanitize_nested_snapshot_value,
    build_handler_conversation_snapshot,
)


def test_conversation_snapshot_keeps_only_allowed_message_content() -> None:
    candidate = {
        "messages": [
            {
                "role": "system",
                "name": "system",
                "content": "internal instructions",
                "metadata": {"secret": "keep-out"},
                "timestamp": "2026-06-18T00:00:00Z",
            },
            {
                "role": "user",
                "name": "user",
                "content": "hello",
                "metadata": {"source": "console"},
                "timestamp": "2026-06-18T00:00:01Z",
            },
            {
                "role": "assistant",
                "name": "Friday",
                "content": [
                    {"type": "thinking", "thinking": "hidden"},
                    {"type": "text", "text": "visible"},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "read_file",
                        "input": {"path": "README.md"},
                        "extra": "drop",
                    },
                    {
                        "type": "custom_block",
                        "value": "drop",
                    },
                ],
                "metadata": {"debug": True},
                "timestamp": "2026-06-18T00:00:02Z",
            },
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": "internal tool instruction",
                    },
                    {
                        "type": "tool_result",
                        "id": "tool-1",
                        "name": "read_file",
                        "output": "ok",
                        "debug": "drop",
                    },
                ],
            },
        ],
    }

    payload = build_handler_conversation_snapshot(candidate, limit=50)

    assert payload["conversation_snapshot"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "hello"}],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "visible"},
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                },
            ],
        },
        {
            "role": "system",
            "content": [
                {
                    "type": "tool_result",
                    "id": "tool-1",
                    "name": "read_file",
                    "output": "ok",
                },
            ],
        },
    ]
    assert payload["conversation_snapshot_meta"] == {
        "included_messages": 3,
        "omitted_messages": 0,
        "limit": 50,
        "reasoning_omitted": True,
        "media_content_omitted": False,
    }


def test_conversation_snapshot_keeps_media_reference_only() -> None:
    payload = build_handler_conversation_snapshot(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "file_url": "file:///tmp/image.png",
                            "media_type": "image/png",
                            "data": "base64-payload",
                        },
                    ],
                },
            ],
        },
        limit=50,
    )

    assert payload["conversation_snapshot"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "file_url": "file:///tmp/image.png",
                    "media_type": "image/png",
                    "content_omitted": True,
                },
            ],
        },
    ]
    assert (
        payload["conversation_snapshot_meta"]["media_content_omitted"] is True
    )


def test_conversation_snapshot_reports_meta_when_message_is_fully_omitted() -> (
    None
):
    payload = build_handler_conversation_snapshot(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "hidden"},
                    ],
                },
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "image",
                            "data": "base64-payload",
                        },
                    ],
                },
            ],
        },
        limit=50,
    )

    assert payload["conversation_snapshot"] == []
    assert payload["conversation_snapshot_meta"]["reasoning_omitted"] is True
    assert (
        payload["conversation_snapshot_meta"]["media_content_omitted"] is True
    )


def test_conversation_snapshot_preserves_existing_media_omission_marker() -> (
    None
):
    payload = build_handler_conversation_snapshot(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "file_url": "file:///tmp/image.png",
                            "media_type": "image/png",
                            "content_omitted": True,
                        },
                    ],
                },
            ],
            "meta": {"media_content_omitted": True},
        },
        limit=50,
    )

    assert payload["conversation_snapshot"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "file_url": "file:///tmp/image.png",
                    "media_type": "image/png",
                    "content_omitted": True,
                },
            ],
        },
    ]


def test_conversation_snapshot_sanitizes_nested_tool_result_output() -> None:
    payload = build_handler_conversation_snapshot(
        {
            "messages": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "tool_result",
                            "id": "tool-1",
                            "name": "inspect",
                            "output": {
                                "summary": "ok",
                                "metadata": {"hidden": "kept"},
                                "image": {
                                    "type": "image",
                                    "media_type": "image/png",
                                    "data": "base64-payload",
                                },
                                "items": [
                                    {
                                        "type": "thinking",
                                        "thinking": "hidden chain",
                                    },
                                    {"value": "visible"},
                                ],
                            },
                        },
                    ],
                },
            ],
        },
        limit=50,
    )

    assert payload["conversation_snapshot"] == [
        {
            "role": "system",
            "content": [
                {
                    "type": "tool_result",
                    "id": "tool-1",
                    "name": "inspect",
                    "output": {
                        "summary": "ok",
                        "metadata": {"hidden": "kept"},
                        "image": {
                            "type": "image",
                            "media_type": "image/png",
                            "content_omitted": True,
                        },
                        "items": [{"value": "visible"}],
                    },
                },
            ],
        },
    ]
    assert payload["conversation_snapshot_meta"]["reasoning_omitted"] is True
    assert (
        payload["conversation_snapshot_meta"]["media_content_omitted"] is True
    )


def test_normalize_content_filters_system_and_media_blocks() -> None:
    normalized, meta = _normalize_content(
        [
            {"type": "text", "text": "drop for system"},
            {
                "type": "image",
                "file_url": "file:///tmp/image.png",
                "data": "base64-payload",
            },
            {"type": "thinking", "thinking": "hidden"},
            {
                "type": "tool_result",
                "id": "tool-1",
                "name": "inspect",
                "output": {"summary": "kept"},
                "debug": "drop",
            },
        ],
        role="system",
    )

    assert normalized == [
        {
            "type": "tool_result",
            "id": "tool-1",
            "name": "inspect",
            "output": {"summary": "kept"},
        },
    ]
    assert meta == {
        "reasoning_omitted": True,
        "media_content_omitted": True,
    }


def test_sanitize_nested_snapshot_value_omits_inline_media_scalars() -> None:
    sanitized, meta = _sanitize_nested_snapshot_value(
        {
            "items": [
                {"type": "reasoning", "thinking": "hidden"},
                {
                    "type": "image",
                    "url": "https://example.com/image.png",
                    "data": "base64-payload",
                },
                {
                    "payload": [
                        {"data_url": "data:image/png;base64,AAA"},
                        {"blob": b"raw-bytes"},
                        {"value": "visible"},
                    ],
                },
            ],
        },
    )

    assert sanitized == {
        "items": [
            {
                "type": "image",
                "url": "https://example.com/image.png",
                "content_omitted": True,
            },
            {
                "payload": [
                    {},
                    {},
                    {"value": "visible"},
                ],
            },
        ],
    }
    assert meta == {
        "reasoning_omitted": True,
        "media_content_omitted": True,
    }
