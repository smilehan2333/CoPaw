# -*- coding: utf-8 -*-
"""Tests for tracing user info batch backfill API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from monitor.app.routers.tracing import (
    BatchUpdateTracingUserInfoRequest,
    batch_update_tracing_user_info,
)


@pytest.mark.asyncio
async def test_batch_update_tracing_user_info_backfills_missing_bbk_id(
    monkeypatch,
):
    """仅缺 bbk_id 时，也应该进入回填批次并更新 traces / spans。"""
    db = SimpleNamespace(
        is_connected=True,
        fetch_all=AsyncMock(return_value=[{"user_id": "user-1"}]),
        fetch_one=AsyncMock(return_value={"cnt": 2}),
        execute_many=AsyncMock(side_effect=[1, 1]),
    )

    monkeypatch.setattr(
        "monitor.app.routers.tracing.get_db_connection",
        lambda: db,
    )
    monkeypatch.setattr(
        "monitor.app.routers.tracing._fetch_user_info_for_user",
        AsyncMock(return_value=("Alice", "3301")),
    )

    request = SimpleNamespace(headers={})
    body = BatchUpdateTracingUserInfoRequest(batch_size=10)

    response = await batch_update_tracing_user_info(request, body)

    first_query = db.fetch_all.await_args.args[0]
    assert "bbk_id IS NULL" in first_query

    trace_query, trace_params = db.execute_many.await_args_list[0].args
    span_query, span_params = db.execute_many.await_args_list[1].args

    assert "bbk_id IS NULL" in trace_query
    assert "bbk_id IS NULL" in span_query
    assert trace_params == [("Alice", "3301", "user-1")]
    assert span_params == [("Alice", "3301", "user-1")]
    assert response.total == 2
    assert response.traces_updated == 1
    assert response.spans_updated == 1
