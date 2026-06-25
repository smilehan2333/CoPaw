# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

MEDIA_BLOCK_TYPES = {
    "audio",
    "file",
    "image",
    "input_audio",
    "input_image",
    "video",
}
REASONING_BLOCK_TYPES = {"reasoning", "thinking"}
MEDIA_REFERENCE_KEYS = {
    "type",
    "id",
    "name",
    "filename",
    "media_type",
    "mime_type",
    "url",
    "file_url",
    "path",
    "size",
    "width",
    "height",
    "content_omitted",
}
INLINE_MEDIA_KEYS = {
    "base64",
    "bytes",
    "data",
    "file_data",
    "content",
}
ALLOWED_ROLES = {"user", "assistant", "system"}
ALLOWED_BLOCK_KEYS = {
    "text": {"type", "text"},
    "tool_use": {"type", "id", "name", "input"},
    "tool_result": {"type", "id", "name", "output"},
}
_OMIT = object()


async def capture_conversation_snapshot(memory: Any) -> dict[str, Any] | None:
    """Capture current memory messages in the hook snapshot wire shape."""
    if memory is None:
        return None

    messages = await _read_memory_messages(memory)
    if messages is None:
        return None

    normalized, meta = normalize_conversation_snapshot_messages(messages)
    return {
        "messages": normalized,
        "meta": meta,
    }


def build_handler_conversation_snapshot(
    candidate: dict[str, Any] | None,
    *,
    limit: int,
) -> dict[str, Any]:
    """Build a per-handler bounded conversation snapshot payload."""
    if candidate is None:
        return {
            "conversation_snapshot": [],
            "conversation_snapshot_meta": {
                "included_messages": 0,
                "omitted_messages": 0,
                "limit": limit,
                "unavailable": True,
                "unavailable_reason": "agent_memory_unavailable",
            },
        }

    messages, normalized_meta = normalize_conversation_snapshot_messages(
        candidate.get("messages") or [],
    )
    candidate_meta = candidate.get("meta") or {}
    total = len(messages)
    bounded = messages[-limit:] if total > limit else list(messages)
    meta: dict[str, Any] = {
        "included_messages": len(bounded),
        "omitted_messages": max(0, total - len(bounded)),
        "limit": limit,
        "reasoning_omitted": bool(
            normalized_meta.get("reasoning_omitted")
            or candidate_meta.get("reasoning_omitted"),
        ),
        "media_content_omitted": bool(
            normalized_meta.get("media_content_omitted")
            or candidate_meta.get("media_content_omitted"),
        ),
    }
    return {
        "conversation_snapshot": bounded,
        "conversation_snapshot_meta": meta,
    }


def normalize_conversation_snapshot_messages(
    messages: Iterable[Any],
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    normalized: list[dict[str, Any]] = []
    reasoning_omitted = False
    media_content_omitted = False

    for message in messages:
        item, item_meta = _normalize_message(message)
        reasoning_omitted = reasoning_omitted or item_meta["reasoning_omitted"]
        media_content_omitted = (
            media_content_omitted or item_meta["media_content_omitted"]
        )
        if item is None:
            continue
        normalized.append(item)

    return normalized, {
        "reasoning_omitted": reasoning_omitted,
        "media_content_omitted": media_content_omitted,
    }


async def _read_memory_messages(memory: Any) -> list[Any] | None:
    get_memory = getattr(memory, "get_memory", None)
    if callable(get_memory):
        try:
            messages = await get_memory(prepend_summary=False)
            if isinstance(messages, list):
                return messages
        except TypeError:
            messages = await get_memory()
            if isinstance(messages, list):
                return messages

    content = getattr(memory, "content", None)
    if isinstance(content, list):
        content_messages: list[Any] = []
        for entry in content:
            if isinstance(entry, tuple) and entry:
                content_messages.append(entry[0])
            elif isinstance(entry, list) and entry:
                content_messages.append(entry[0])
            else:
                content_messages.append(entry)
        return content_messages
    return None


def _normalize_message(
    message: Any,
) -> tuple[dict[str, Any] | None, dict[str, bool]]:
    if isinstance(message, dict):
        raw = dict(message)
    elif hasattr(message, "to_dict") and callable(message.to_dict):
        raw = message.to_dict()
    else:
        raw = {
            "role": getattr(message, "role", None),
            "name": getattr(message, "name", None),
            "content": getattr(message, "content", None),
            "metadata": getattr(message, "metadata", None),
            "timestamp": getattr(message, "timestamp", None),
        }

    role = raw.get("role")
    if role not in ALLOWED_ROLES:
        return None, {
            "reasoning_omitted": False,
            "media_content_omitted": False,
        }
    content = raw.get("content")
    normalized_content, meta = _normalize_content(content, role=str(role))
    if normalized_content is None:
        return None, meta

    item: dict[str, Any] = {
        "role": role,
        "content": normalized_content,
    }
    return item, meta


def _normalize_content(
    content: Any,
    *,
    role: str,
) -> tuple[Any, dict[str, bool]]:
    if isinstance(content, str):
        return _normalize_string_content(content, role)
    if not isinstance(content, list):
        return None, _snapshot_meta()

    blocks: list[dict[str, Any]] = []
    meta = _snapshot_meta()
    for block in content:
        normalized_block, block_meta = _normalize_content_block(block, role)
        _merge_snapshot_meta(meta, block_meta)
        if normalized_block is not _OMIT:
            blocks.append(normalized_block)

    if not blocks:
        return None, meta
    return blocks, meta


def _normalize_string_content(
    content: str,
    role: str,
) -> tuple[Any, dict[str, bool]]:
    if role == "system":
        return None, _snapshot_meta()
    return [{"type": "text", "text": content}], _snapshot_meta()


def _normalize_content_block(
    block: Any,
    role: str,
) -> tuple[Any, dict[str, bool]]:
    raw = _block_to_dict(block)
    if raw is None:
        return _OMIT, _snapshot_meta()

    block_type = str(raw.get("type") or "text")
    if block_type in REASONING_BLOCK_TYPES:
        return _OMIT, _snapshot_meta(reasoning_omitted=True)
    if role == "system" and block_type != "tool_result":
        return _OMIT, _snapshot_meta(
            media_content_omitted=block_type in MEDIA_BLOCK_TYPES,
        )
    if block_type in MEDIA_BLOCK_TYPES:
        return _media_reference_block(raw), _snapshot_meta(
            media_content_omitted=True,
        )
    if block_type not in ALLOWED_BLOCK_KEYS:
        return _OMIT, _snapshot_meta()
    return _allowlisted_block(raw, block_type)


def _snapshot_meta(
    *,
    reasoning_omitted: bool = False,
    media_content_omitted: bool = False,
) -> dict[str, bool]:
    return {
        "reasoning_omitted": reasoning_omitted,
        "media_content_omitted": media_content_omitted,
    }


def _merge_snapshot_meta(
    target: dict[str, bool],
    incoming: dict[str, bool],
) -> None:
    target["reasoning_omitted"] = (
        target["reasoning_omitted"] or incoming["reasoning_omitted"]
    )
    target["media_content_omitted"] = (
        target["media_content_omitted"] or incoming["media_content_omitted"]
    )


def _block_to_dict(block: Any) -> dict[str, Any] | None:
    if isinstance(block, dict):
        return dict(block)
    model_dump = getattr(block, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json", exclude_none=True)
        return dumped if isinstance(dumped, dict) else None
    if hasattr(block, "to_dict") and callable(block.to_dict):
        dumped = block.to_dict()
        return dumped if isinstance(dumped, dict) else None
    return None


def _media_reference_block(block: dict[str, Any]) -> dict[str, Any]:
    omitted = bool(block.get("content_omitted"))
    reference: dict[str, Any] = {}
    for key, value in block.items():
        if key in INLINE_MEDIA_KEYS:
            omitted = True
            continue
        if key not in MEDIA_REFERENCE_KEYS:
            continue
        if isinstance(value, str) and value.startswith("data:"):
            omitted = True
            continue
        reference[key] = value
    if "type" not in reference:
        reference["type"] = block.get("type")
    if omitted:
        reference["content_omitted"] = True
    return reference


def _allowlisted_block(
    block: dict[str, Any],
    block_type: str,
) -> tuple[dict[str, Any], dict[str, bool]]:
    allowed = ALLOWED_BLOCK_KEYS[block_type]
    result: dict[str, Any] = {}
    meta = _snapshot_meta()
    for key, value in block.items():
        if key not in allowed:
            continue
        if key not in {"input", "output"}:
            result[key] = value
            continue
        sanitized, nested_meta = _sanitize_nested_snapshot_value(value)
        _merge_snapshot_meta(meta, nested_meta)
        if sanitized is not _OMIT:
            result[key] = sanitized
    return result, meta


def _sanitize_nested_snapshot_value(value: Any) -> tuple[Any, dict[str, bool]]:
    if isinstance(value, dict):
        typed_snapshot = _sanitize_typed_snapshot_dict(value)
        if typed_snapshot is not None:
            return typed_snapshot
        return _sanitize_snapshot_dict(value)
    if isinstance(value, list):
        return _sanitize_snapshot_list(value)
    return _sanitize_snapshot_scalar(value)


def _sanitize_typed_snapshot_dict(
    value: dict[str, Any],
) -> tuple[Any, dict[str, bool]] | None:
    value_type = value.get("type")
    if value_type in REASONING_BLOCK_TYPES:
        return _OMIT, _snapshot_meta(reasoning_omitted=True)
    if value_type in MEDIA_BLOCK_TYPES:
        return _media_reference_block(value), _snapshot_meta(
            media_content_omitted=True,
        )
    return None


def _sanitize_snapshot_dict(
    value: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    result: dict[str, Any] = {}
    meta = _snapshot_meta()
    for key, nested_value in value.items():
        sanitized, nested_meta = _sanitize_nested_snapshot_value(nested_value)
        _merge_snapshot_meta(meta, nested_meta)
        if sanitized is not _OMIT:
            result[key] = sanitized
    return result, meta


def _sanitize_snapshot_list(
    value: list[Any],
) -> tuple[list[Any], dict[str, bool]]:
    items: list[Any] = []
    meta = _snapshot_meta()
    for nested_value in value:
        sanitized, nested_meta = _sanitize_nested_snapshot_value(nested_value)
        _merge_snapshot_meta(meta, nested_meta)
        if sanitized is not _OMIT:
            items.append(sanitized)
    return items, meta


def _sanitize_snapshot_scalar(value: Any) -> tuple[Any, dict[str, bool]]:
    if isinstance(value, str) and value.startswith("data:"):
        return _OMIT, _snapshot_meta(media_content_omitted=True)
    if isinstance(value, bytes | bytearray):
        return _OMIT, _snapshot_meta(media_content_omitted=True)
    return value, _snapshot_meta()
