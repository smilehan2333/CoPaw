# -*- coding: utf-8 -*-
"""Regression tests for the /models/active lightweight read path."""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import swe.providers.provider_manager as provider_manager_module
import swe.tenant_models.manager as tenant_models_manager_module
from swe.app.routers.providers import router as providers_router
from swe.config.context import encode_scope_id
from swe.providers.provider_manager import ProviderManager


def test_get_active_models_reads_active_file_without_manager_cold_start(
    monkeypatch,
    tmp_path,
) -> None:
    """GET /models/active should not cold-construct full ProviderManager."""
    secret_dir = tmp_path / ".swe.secret"
    scope_id = encode_scope_id("tenant-a", "source-a")
    providers_dir = secret_dir / scope_id / "providers"
    (providers_dir / "builtin").mkdir(parents=True)
    (providers_dir / "custom").mkdir()
    (providers_dir / "active_model.json").write_text(
        json.dumps({"provider_id": "openai", "model": "gpt-5"}),
        encoding="utf-8",
    )
    (providers_dir / "custom" / "slow-or-invalid.json").write_text(
        "{invalid-json",
        encoding="utf-8",
    )

    app = FastAPI()

    @app.middleware("http")
    async def add_tenant_id(request: Request, call_next):
        request.state.tenant_id = "tenant-a"
        request.state.source_id = "source-a"
        return await call_next(request)

    app.include_router(providers_router)
    client = TestClient(app)

    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    monkeypatch.setattr(
        ProviderManager,
        "get_instance",
        staticmethod(
            lambda _tenant_id=None: (_ for _ in ()).throw(
                AssertionError("ProviderManager cold start should be avoided"),
            ),
        ),
    )

    response = client.get("/models/active")

    assert response.status_code == 200
    assert response.json() == {
        "active_llm": {"provider_id": "openai", "model": "gpt-5"},
    }


def test_get_active_models_does_not_recover_legacy_tenant_models(
    monkeypatch,
    tmp_path,
) -> None:
    """GET /models/active only reads providers/active_model.json."""
    secret_dir = tmp_path / ".swe.secret"
    scope_id = encode_scope_id("tenant-a", "source-a")
    scope_dir = secret_dir / scope_id
    providers_dir = scope_dir / "providers"
    (providers_dir / "builtin").mkdir(parents=True)
    (providers_dir / "custom").mkdir()
    (scope_dir / "tenant_models.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "providers": [],
                "routing": {
                    "mode": "cloud_first",
                    "slots": {
                        "cloud": {
                            "provider_id": "legacy-openai",
                            "model": "gpt-legacy",
                        },
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    app = FastAPI()

    @app.middleware("http")
    async def add_tenant_id(request: Request, call_next):
        request.state.tenant_id = "tenant-a"
        request.state.source_id = "source-a"
        return await call_next(request)

    app.include_router(providers_router)
    client = TestClient(app)

    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    monkeypatch.setattr(tenant_models_manager_module, "SECRET_DIR", secret_dir)

    response = client.get("/models/active?scope=agent&agent_id=default")

    assert response.status_code == 200
    assert response.json() == {"active_llm": None}
    assert not (providers_dir / "active_model.json").exists()
