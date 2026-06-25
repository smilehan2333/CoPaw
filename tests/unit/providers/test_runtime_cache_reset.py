# -*- coding: utf-8 -*-
"""运行态模型缓存失效回归测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from swe.providers import provider_manager as provider_manager_module
from swe.providers.provider_manager import ProviderManager


def test_reset_instance_cache_resets_scope_bound_model_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []

    monkeypatch.setattr(
        provider_manager_module,
        "reset_scope_bound_model_caches",
        lambda: observed.append("reset"),
    )
    ProviderManager._instances["tenant-a"] = object()
    ProviderManager._instance = object()

    ProviderManager.reset_instance_cache()

    assert observed == ["reset"]
    assert ProviderManager._instances == {}
    assert ProviderManager._instance is None


def test_refresh_if_stale_resets_scope_bound_model_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []
    manager = object.__new__(ProviderManager)
    manager._record_mtimes = lambda: observed.append("record")
    manager._apply_builtin_refresh = lambda changed: observed.append("builtin")
    manager._apply_custom_refresh = (
        lambda changed, new, removed: observed.append("custom")
    )
    manager._apply_active_model_refresh = lambda: observed.append("active")
    manager._detect_changed_builtins = lambda: ["openai"]
    manager._detect_custom_changes = lambda: ([], [], [])
    manager._detect_active_model_change = lambda: False

    monkeypatch.setattr(
        provider_manager_module,
        "reset_scope_bound_model_caches",
        lambda: observed.append("reset"),
    )

    manager._refresh_if_stale()

    assert observed == ["builtin", "custom", "reset", "record"]


@pytest.mark.asyncio
async def test_activate_model_resets_scope_bound_model_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, Any, Any] | str] = []
    provider = SimpleNamespace(
        has_model=lambda model_id: True,
        models=[],
        extra_models=[],
    )
    manager = object.__new__(ProviderManager)
    manager.get_provider = lambda provider_id: provider
    manager.save_active_model = lambda active_model: observed.append(
        ("save", active_model.provider_id, active_model.model),
    )
    manager.maybe_probe_multimodal = (
        lambda provider_id, model_id: observed.append(
            ("probe", provider_id, model_id),
        )
    )

    monkeypatch.setattr(
        provider_manager_module,
        "reset_scope_bound_model_caches",
        lambda: observed.append("reset"),
    )

    await manager.activate_model("openai", "gpt-5.4")

    assert observed == [
        ("save", "openai", "gpt-5.4"),
        "reset",
        ("probe", "openai", "gpt-5.4"),
    ]
