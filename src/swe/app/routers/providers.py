# -*- coding: utf-8 -*-
"""API routes for LLM providers and models."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path as PathlibPath
from typing import List, Literal, Optional
from copy import deepcopy

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
)
from pydantic import BaseModel, Field

from ...config.context import (
    get_current_effective_tenant_id,
    resolve_scope_preferred_tenant_id,
    resolve_storage_tenant_id,
)
from ...config.utils import (
    get_tenant_storage_providers_dir,
    get_tenant_storage_working_dir,
    list_logical_tenant_ids,
)
from ...providers.models import ModelSlotConfig
from ...providers.provider import ProviderInfo, ModelInfo
from ...providers.provider_manager import ActiveModelsInfo, ProviderManager
from ..workspace.tenant_initializer import TenantInitializer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

_PROVIDER_API_SLOW_LOG_MS = 500

ChatModelName = Literal[
    "OpenAIChatModel",
    "KimiChatModel",
    "AnthropicChatModel",
    "GeminiChatModel",
]

# effective: agent-specific if set, otherwise global
# global: the global model only, ignoring any agent-specific setting
# agent: a specific agent's model only, error if not set
ActiveModelReadScope = Literal["effective", "global", "agent"]
ActiveModelWriteScope = Literal["global", "agent"]


def get_provider_manager(request: Request) -> ProviderManager:
    """Get the tenant-specific provider manager.

    Ensures tenant provider storage is initialized before returning the manager.
    This lazy-initializes provider storage on first provider API use.

    Args:
        request: FastAPI request object

    Returns:
        ProviderManager instance for the current tenant.

    Raises:
        HTTPException: If tenant ID is not available in request context.
    """
    started_at = time.perf_counter()
    resolve_started_at = started_at
    tenant_id = _get_effective_tenant_id(request)
    resolve_ms = int((time.perf_counter() - resolve_started_at) * 1000)

    if tenant_id is None:
        # For exempt routes or backward compatibility, use default tenant
        tenant_id = "default"
        logger.debug("No tenant ID in request, using default tenant")

    provider_tenant_id = ProviderManager._resolve_effective_provider_tenant_id(
        tenant_id,
    )
    cache_hit_before = provider_tenant_id in ProviderManager._instances
    root_path = ProviderManager._get_tenant_root_path(provider_tenant_id)
    logger.info(
        "provider_manager_dependency_start path=%s route_tenant_id=%s "
        "provider_tenant_id=%s source_id=%s scope_id=%s cache_hit_before=%s "
        "root_path=%s",
        request.url.path,
        tenant_id,
        provider_tenant_id,
        _request_source_id(request),
        getattr(request.state, "scope_id", None),
        cache_hit_before,
        root_path,
    )

    # Ensure tenant provider storage exists before accessing ProviderManager
    ensure_started_at = time.perf_counter()
    logger.info(
        "provider_storage_ensure_start path=%s route_tenant_id=%s "
        "provider_tenant_id=%s root_path=%s",
        request.url.path,
        tenant_id,
        provider_tenant_id,
        root_path,
    )
    ProviderManager.ensure_tenant_provider_storage(tenant_id)
    ensure_ms = int((time.perf_counter() - ensure_started_at) * 1000)
    logger.info(
        "provider_storage_ensure_done path=%s route_tenant_id=%s "
        "provider_tenant_id=%s duration_ms=%d root_path=%s",
        request.url.path,
        tenant_id,
        provider_tenant_id,
        ensure_ms,
        root_path,
    )

    # Return tenant-specific provider manager
    get_instance_started_at = time.perf_counter()
    logger.info(
        "provider_manager_get_instance_start path=%s route_tenant_id=%s "
        "provider_tenant_id=%s cache_hit_before=%s root_path=%s",
        request.url.path,
        tenant_id,
        provider_tenant_id,
        cache_hit_before,
        root_path,
    )
    manager = ProviderManager.get_instance(tenant_id)
    get_instance_ms = int(
        (time.perf_counter() - get_instance_started_at) * 1000,
    )
    logger.info(
        "provider_manager_get_instance_done path=%s route_tenant_id=%s "
        "provider_tenant_id=%s manager_tenant_id=%s duration_ms=%d "
        "cache_hit_after=%s root_path=%s",
        request.url.path,
        tenant_id,
        provider_tenant_id,
        manager.tenant_id,
        get_instance_ms,
        manager.tenant_id in ProviderManager._instances,
        root_path,
    )
    total_ms = int((time.perf_counter() - started_at) * 1000)

    if total_ms >= _PROVIDER_API_SLOW_LOG_MS:
        logger.info(
            "provider_manager_dependency_slow path=%s total_ms=%d "
            "resolve_ms=%d ensure_ms=%d get_instance_ms=%d "
            "route_tenant_id=%s provider_tenant_id=%s manager_tenant_id=%s "
            "source_id=%s scope_id=%s cache_hit_before=%s "
            "cache_hit_after=%s root_path=%s root_exists=%s",
            request.url.path,
            total_ms,
            resolve_ms,
            ensure_ms,
            get_instance_ms,
            tenant_id,
            provider_tenant_id,
            manager.tenant_id,
            _request_source_id(request),
            getattr(request.state, "scope_id", None),
            cache_hit_before,
            manager.tenant_id in ProviderManager._instances,
            root_path,
            root_path.exists(),
        )

    return manager


class ProviderConfigRequest(BaseModel):
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Chat model class name for protocol selection",
    )
    generate_kwargs: Optional[dict] = Field(
        default_factory=dict,
        description=(
            "Configuration in json format, will be expanded "
            "and passed to generation calls "
            "(e.g., openai.chat.completions, anthropic.messages)."
        ),
    )


class ModelSlotRequest(BaseModel):
    provider_id: str = Field(..., description="Provider to use")
    model: str = Field(..., description="Model identifier")
    scope: ActiveModelWriteScope = Field(
        ...,
        description="Whether to update the global model or a specific agent",
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="Target agent ID when scope is 'agent'",
    )


class CreateCustomProviderRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)
    default_base_url: str = Field(default="")
    api_key_prefix: str = Field(default="")
    chat_model: ChatModelName = Field(default="OpenAIChatModel")
    models: List[ModelInfo] = Field(default_factory=list)


class AddModelRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)


def _validate_model_slot(
    manager: ProviderManager,
    provider_id: str,
    model_id: str,
) -> None:
    """Validate that the provider and model exist without mutating state."""
    provider = manager.get_provider(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found.",
        )
    if not provider.has_model(model_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Model '{model_id}' not found in provider "
                f"'{provider_id}'."
            ),
        )


def _request_tenant_id(request: Request) -> str | None:
    return getattr(request.state, "tenant_id", None)


def _request_tenant_working_dir(request: Request):
    return get_tenant_storage_working_dir(_get_effective_tenant_id(request))


def _request_source_id(request: Request) -> str | None:
    return getattr(request.state, "source_id", None)


def _get_effective_tenant_id(request: Request) -> str | None:
    """从请求上下文获取 storage 语义的有效租户 ID。"""
    return resolve_storage_tenant_id(
        _request_tenant_id(request),
        _request_source_id(request),
        scope_id=getattr(request.state, "scope_id", None),
    )


def _distribute_providers_to_tenant(
    *,
    source_providers_dir: PathlibPath,
    target_tenant_id: str,
    source_working_dir: PathlibPath,
    source_id: str | None,
) -> ProvidersDistributionTenantResult:
    """分发 providers 目录到单个目标租户。

    Args:
        source_providers_dir: 源租户的 providers 目录路径。
        target_tenant_id: 目标租户 ID。
        source_working_dir: 源租户的工作目录父路径。
        source_id: 租户初始化使用的 source 标识。

    Returns:
        分发结果。
    """
    # 安全校验
    target_tenant_id = _validate_target_tenant_id(target_tenant_id)

    initializer = TenantInitializer(
        source_working_dir.parent,
        target_tenant_id,
        source_id=source_id,
    )
    was_bootstrapped = initializer.has_seeded_bootstrap()
    if not was_bootstrapped:
        initializer.ensure_seeded_bootstrap()

    target_providers_dir = get_tenant_storage_providers_dir(
        initializer.effective_tenant_id,
    )

    # Remove existing target directory if exists
    if target_providers_dir.exists():
        shutil.rmtree(target_providers_dir)

    # Copy entire providers directory
    shutil.copytree(source_providers_dir, target_providers_dir)

    return ProvidersDistributionTenantResult(
        tenant_id=target_tenant_id,
        success=True,
        bootstrapped=not was_bootstrapped,
    )


def _validate_target_tenant_id(tenant_id: str) -> str:
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if len(tenant_id) > 256:
        raise ValueError(f"Invalid tenant ID format: {tenant_id}")
    if ".." in tenant_id or "/" in tenant_id or "\\" in tenant_id:
        raise ValueError(f"Invalid tenant ID format: {tenant_id}")
    if any(ord(c) < 32 for c in tenant_id):
        raise ValueError(f"Invalid tenant ID format: {tenant_id}")
    return tenant_id


def _resolve_distribution_source(
    manager: ProviderManager,
) -> tuple[ModelSlotConfig, dict]:
    active_model = manager.get_active_model()
    if (
        active_model is None
        or not active_model.provider_id
        or not active_model.model
    ):
        raise HTTPException(
            status_code=400,
            detail="No active model configured for the current tenant",
        )

    provider = manager.get_provider(active_model.provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{active_model.provider_id}' not found.",
        )
    if not provider.has_model(active_model.model):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Model '{active_model.model}' not found in provider "
                f"'{active_model.provider_id}'."
            ),
        )

    return active_model, provider.model_dump()


async def _distribute_active_model_to_tenant(
    *,
    source_working_dir,
    target_tenant_id: str,
    provider_payload: dict,
    source_active_model: ModelSlotConfig,
    source_id: str | None,
) -> ActiveModelDistributionTenantResult:
    initializer = TenantInitializer(
        source_working_dir.parent,
        target_tenant_id,
        source_id=source_id,
    )
    was_bootstrapped = initializer.has_seeded_bootstrap()
    if not was_bootstrapped:
        initializer.ensure_seeded_bootstrap()

    ProviderManager.ensure_tenant_provider_storage(
        initializer.effective_tenant_id,
    )
    target_manager = ProviderManager.get_instance(
        initializer.effective_tenant_id,
    )
    target_manager.overwrite_provider_payload(provider_payload)
    await target_manager.activate_model(
        source_active_model.provider_id,
        source_active_model.model,
    )
    return ActiveModelDistributionTenantResult(
        tenant_id=target_tenant_id,
        success=True,
        bootstrapped=not was_bootstrapped,
        provider_updated=source_active_model.provider_id,
        active_llm_updated=ModelSlotConfig(
            provider_id=source_active_model.provider_id,
            model=source_active_model.model,
        ),
    )


# Agent-level model configuration is deprecated
# Models are now managed at tenant level via TenantModelConfig
# _load_agent_model function removed as agent-specific models are no longer supported


@router.get(
    "",
    response_model=List[ProviderInfo],
    summary="List all providers",
)
async def list_all_providers(
    manager: ProviderManager = Depends(get_provider_manager),
) -> List[ProviderInfo]:
    started_at = time.perf_counter()
    providers = await manager.list_provider_info()
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    if duration_ms >= _PROVIDER_API_SLOW_LOG_MS:
        logger.info(
            "provider_list_info_slow tenant_id=%s duration_ms=%d "
            "provider_count=%d custom_count=%d root_path=%s",
            manager.tenant_id,
            duration_ms,
            len(providers),
            len(manager.custom_providers),
            manager.root_path,
        )
    return providers


@router.put(
    "/{provider_id}/config",
    response_model=ProviderInfo,
    summary="Configure a provider",
)
async def configure_provider(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: ProviderConfigRequest = Body(...),
) -> ProviderInfo:
    ok = manager.update_provider(
        provider_id,
        {
            "api_key": body.api_key,
            "base_url": body.base_url,
            "chat_model": body.chat_model,
            "generate_kwargs": body.generate_kwargs,
        },
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found",
        )

    provider_info = await manager.get_provider_info(provider_id)
    if provider_info is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found after update",
        )
    return provider_info


@router.post(
    "/custom-providers",
    response_model=ProviderInfo,
    summary="Create a custom provider",
    status_code=201,
)
async def create_custom_provider_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    body: CreateCustomProviderRequest = Body(...),
) -> ProviderInfo:
    try:
        provider_info = await manager.add_custom_provider(
            ProviderInfo(
                id=body.id,
                name=body.name,
                base_url=body.default_base_url,
                api_key_prefix=body.api_key_prefix,
                chat_model=body.chat_model,
                extra_models=body.models,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return provider_info


class TestConnectionResponse(BaseModel):
    success: bool = Field(..., description="Whether the test passed")
    message: str = Field(..., description="Human-readable result message")


class TestProviderRequest(BaseModel):
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key to test",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional Base URL to test",
    )
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Optional chat model class to test protocol behavior",
    )


class TestModelRequest(BaseModel):
    model_id: str = Field(..., description="Model ID to test")


class DiscoverModelsRequest(BaseModel):
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key to use for discovery",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional Base URL to use for discovery",
    )
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Optional chat model class to use for discovery",
    )


class DiscoverModelsResponse(BaseModel):
    success: bool = Field(..., description="Whether discovery succeeded")
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="Discovered models",
    )
    message: str = Field(
        default="",
        description="Human-readable result message",
    )
    added_count: int = Field(
        default=0,
        description="How many new models were added into provider config",
    )


class DistributionTenantListResponse(BaseModel):
    tenant_ids: List[str] = Field(default_factory=list)


class ActiveModelDistributionRequest(BaseModel):
    target_tenant_ids: List[str] = Field(default_factory=list)
    overwrite: bool = Field(...)


class ActiveModelDistributionTenantResult(BaseModel):
    tenant_id: str = Field(...)
    success: bool = Field(...)
    bootstrapped: bool = Field(default=False)
    provider_updated: Optional[str] = Field(default=None)
    active_llm_updated: ModelSlotConfig | None = Field(default=None)
    error: Optional[str] = Field(default=None)


class ActiveModelDistributionResponse(BaseModel):
    source_active_llm: ModelSlotConfig
    results: List[ActiveModelDistributionTenantResult] = Field(
        default_factory=list,
    )


class ProvidersDistributionRequest(BaseModel):
    """Request body for distributing entire providers directory."""

    target_tenant_ids: List[str] = Field(
        default_factory=list,
        description="Target tenant IDs to distribute providers to",
    )
    overwrite: bool = Field(
        ...,
        description="Must be true for providers distribution",
    )


class ProvidersDistributionTenantResult(BaseModel):
    """Per-tenant providers distribution result."""

    tenant_id: str = Field(..., description="Target tenant ID")
    success: bool = Field(..., description="Whether distribution succeeded")
    bootstrapped: bool = Field(
        default=False,
        description="Whether the target tenant was bootstrapped during distribution",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if failed",
    )


class ProvidersDistributionResponse(BaseModel):
    """Response payload for providers distribution requests."""

    source_tenant_id: str = Field(..., description="Source tenant ID")
    results: List[ProvidersDistributionTenantResult] = Field(
        default_factory=list,
        description="Per-tenant distribution results",
    )


@router.post(
    "/{provider_id}/test",
    response_model=TestConnectionResponse,
    summary="Test provider connection",
)
async def test_provider(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: Optional[TestProviderRequest] = Body(default=None),
) -> TestConnectionResponse:
    """Test if a provider's URL and API key are valid."""
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider '{provider_id}' not found")
        # Ensure we don't accidentally modify provider config during test
        tmp_provider = deepcopy(provider)
        if body and body.api_key:
            tmp_provider.api_key = body.api_key
        if body and body.base_url:
            tmp_provider.base_url = body.base_url
        ok, msg = await tmp_provider.check_connection()
        return TestConnectionResponse(
            success=ok,
            message=(
                "Connection successful" if ok else f"Connection failed: {msg}"
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/discover",
    response_model=DiscoverModelsResponse,
    summary="Discover available models from provider",
)
async def discover_models(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: Optional[DiscoverModelsRequest] = Body(default=None),
) -> DiscoverModelsResponse:
    try:
        ok = manager.update_provider(
            provider_id,
            {
                "api_key": body.api_key if body else None,
                "base_url": body.base_url if body else None,
            },
        )
        if not ok:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found",
            )
        try:
            result = await manager.fetch_provider_models(
                provider_id,
            )
            success = True
        except Exception:
            result = []
            success = False
        return DiscoverModelsResponse(success=success, models=result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/models/test",
    response_model=TestConnectionResponse,
    summary="Test a specific model",
)
async def test_model(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: TestModelRequest = Body(...),
) -> TestConnectionResponse:
    """Test if a specific model works with the configured provider."""
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider '{provider_id}' not found")
        ok, msg = await provider.check_model_connection(model_id=body.model_id)
        return TestConnectionResponse(
            success=ok,
            message=(
                "Model connection successful"
                if ok
                else f"Model connection failed: {msg}"
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/custom-providers/{provider_id}",
    response_model=List[ProviderInfo],
    summary="Delete a custom provider",
)
async def delete_custom_provider_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
) -> List[ProviderInfo]:
    try:
        ok = manager.remove_custom_provider(provider_id)
        if not ok:
            raise ValueError(f"Custom Provider '{provider_id}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await manager.list_provider_info()


@router.post(
    "/{provider_id}/models",
    response_model=ProviderInfo,
    summary="Add a model to a provider",
    status_code=201,
)
async def add_model_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: AddModelRequest = Body(...),
) -> ProviderInfo:
    try:
        provider = await manager.add_model_to_provider(
            provider_id=provider_id,
            model_info=ModelInfo(id=body.id, name=body.name),
        )  # Validate provider exists and add model
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return provider


class ProbeMultimodalResponse(BaseModel):
    supports_image: bool = Field(
        default=False,
        description="Whether the model supports image input",
    )
    supports_video: bool = Field(
        default=False,
        description="Whether the model supports video input",
    )
    supports_multimodal: bool = Field(
        default=False,
        description="Whether the model supports any multimodal input",
    )
    image_message: str = Field(
        default="",
        description="Probe result message for image support",
    )
    video_message: str = Field(
        default="",
        description="Probe result message for video support",
    )


@router.post(
    "/{provider_id}/models/{model_id:path}/probe-multimodal",
    response_model=ProbeMultimodalResponse,
    summary="Probe model multimodal capability",
)
async def probe_model_multimodal(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProbeMultimodalResponse:
    """Probe image and video support by sending lightweight test requests."""
    result = await manager.probe_model_multimodal(provider_id, model_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return ProbeMultimodalResponse(**result)


@router.delete(
    "/{provider_id}/models/{model_id:path}",
    response_model=ProviderInfo,
    summary="Remove a model from a provider",
)
async def remove_model_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProviderInfo:
    try:
        provider = await manager.delete_model_from_provider(
            provider_id=provider_id,
            model_id=model_id,
        )  # Validate provider and model exist and delete
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return provider


@router.get(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Get effective active LLM",
)
async def get_active_models(
    request: Request,
    scope: ActiveModelReadScope = Query(default="effective"),
    _agent_id: Optional[str] = Query(default=None),  # Deprecated
) -> ActiveModelsInfo:
    """Get active model by scope.

    DEPRECATED: Agent-level model configuration is no longer supported.
    Models are now managed at tenant level.

    - effective: Returns tenant-level active model (agent-specific fallback removed)
    - global: ProviderManager global model (tenant-level model)
    - agent: DEPRECATED - treated as 'global' for backward compatibility
    """
    # Short-term compatibility: normalize legacy 'agent' scope to 'global'
    started_at = time.perf_counter()
    if scope == "agent":
        logger.warning(
            "Received deprecated scope='agent' for get_active_models. "
            "Treating as 'global'. Client should be updated to use scope='global'.",
        )

    # For 'effective' and 'global', return the tenant-level active model
    # Agent-level model fallback is removed as models are now tenant-scoped
    tenant_id = _get_effective_tenant_id(request) or "default"
    ProviderManager.ensure_tenant_provider_storage(tenant_id)
    provider_tenant_id = ProviderManager._resolve_effective_provider_tenant_id(
        tenant_id,
    )
    root_path = ProviderManager._get_tenant_root_path(provider_tenant_id)
    global_model = ProviderManager._read_active_model_from_root(
        root_path,
    )
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    if duration_ms >= _PROVIDER_API_SLOW_LOG_MS:
        logger.info(
            "provider_active_model_read_slow tenant_id=%s duration_ms=%d "
            "scope=%s root_path=%s",
            provider_tenant_id,
            duration_ms,
            scope,
            root_path,
        )
    return ActiveModelsInfo(active_llm=global_model)


@router.put(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Set active LLM",
)
async def set_active_model(
    _request: Request,  # Kept for future tenant context usage
    manager: ProviderManager = Depends(get_provider_manager),
    body: ModelSlotRequest = Body(...),
) -> ActiveModelsInfo:
    """Set active model by scope.

    Note: 'agent' scope is deprecated and will be treated as 'global'.
    Models are now managed at tenant level only.
    """
    # Short-term compatibility: normalize legacy 'agent' scope to 'global'
    effective_scope = body.scope
    if body.scope == "agent":
        logger.warning(
            "Received deprecated scope='agent' for set_active_model. "
            "Treating as 'global'. Client should be updated to use scope='global'.",
        )
        effective_scope = "global"

    if effective_scope == "global":
        try:
            await manager.activate_model(body.provider_id, body.model)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            message = str(exc)
            lower_msg = message.lower()
            if "provider" in lower_msg and "not found" in lower_msg:
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return ActiveModelsInfo(active_llm=manager.get_active_model())

    # Any other scope is not supported
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported scope: {body.scope}. Use 'global' for tenant-level model.",
    )


@router.get(
    "/distribution/tenants",
    response_model=DistributionTenantListResponse,
    summary="List discovered tenants for model distribution",
)
async def list_active_model_distribution_tenants(
    request: Request,
) -> DistributionTenantListResponse:
    return DistributionTenantListResponse(
        tenant_ids=await list_logical_tenant_ids(
            _request_source_id(request),
            source_filter=True,
            include_templates=True,
        ),
    )


@router.post(
    "/distribution/active-llm",
    response_model=ActiveModelDistributionResponse,
    summary="Distribute current tenant active model to target tenants",
)
async def distribute_active_model(
    request: Request,
    body: ActiveModelDistributionRequest = Body(...),
    manager: ProviderManager = Depends(get_provider_manager),
) -> ActiveModelDistributionResponse:
    if not body.overwrite:
        raise HTTPException(
            status_code=400,
            detail="overwrite=true is required for active-model distribution",
        )
    if not body.target_tenant_ids:
        raise HTTPException(
            status_code=400,
            detail="No target tenant IDs provided",
        )

    source_active_model, provider_payload = _resolve_distribution_source(
        manager,
    )
    source_working_dir = _request_tenant_working_dir(request)
    source_id = _request_source_id(request)
    results: list[ActiveModelDistributionTenantResult] = []
    for tenant_id in body.target_tenant_ids:
        try:
            validated_tenant_id = _validate_target_tenant_id(tenant_id)
            result = await _distribute_active_model_to_tenant(
                source_working_dir=source_working_dir,
                target_tenant_id=validated_tenant_id,
                provider_payload=provider_payload,
                source_active_model=source_active_model,
                source_id=source_id,
            )
            results.append(result)
        except Exception as exc:
            results.append(
                ActiveModelDistributionTenantResult(
                    tenant_id=str(tenant_id),
                    success=False,
                    error=str(exc),
                ),
            )

    return ActiveModelDistributionResponse(
        source_active_llm=source_active_model,
        results=results,
    )


@router.post(
    "/distribution/providers",
    response_model=ProvidersDistributionResponse,
    summary="Distribute entire providers directory to target tenants",
)
async def distribute_providers(
    request: Request,
    body: ProvidersDistributionRequest = Body(...),
) -> ProvidersDistributionResponse:
    """从当前租户全量分发 providers 目录到目标租户。

    该端点执行完全覆盖，包括 builtin/、custom/ 和 active_model.json。

    Args:
        request: FastAPI 请求对象。
        body: 分发请求，包含目标租户 ID 列表。

    Returns:
        每个目标租户的分发结果。

    Raises:
        HTTPException: 400 如果 overwrite 为 False、无目标租户、
            或源 providers 目录不存在。
    """
    if not body.overwrite:
        raise HTTPException(
            status_code=400,
            detail="overwrite=true is required for providers distribution",
        )
    if not body.target_tenant_ids:
        raise HTTPException(
            status_code=400,
            detail="No target tenant IDs provided",
        )

    # 获取源租户的有效租户 ID
    effective_tenant_id = _get_effective_tenant_id(request)
    if effective_tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="No tenant ID in request context",
        )

    # 获取源 providers 目录
    source_providers_dir = get_tenant_storage_providers_dir(
        effective_tenant_id,
    )
    if not source_providers_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Source providers directory not found for tenant '{effective_tenant_id}'",
        )

    source_working_dir = _request_tenant_working_dir(request)
    source_id = _request_source_id(request)

    results: list[ProvidersDistributionTenantResult] = []
    for tenant_id in body.target_tenant_ids:
        try:
            result = _distribute_providers_to_tenant(
                source_providers_dir=source_providers_dir,
                target_tenant_id=tenant_id,
                source_working_dir=source_working_dir,
                source_id=source_id,
            )
            results.append(result)
        except Exception as exc:
            results.append(
                ProvidersDistributionTenantResult(
                    tenant_id=str(tenant_id),
                    success=False,
                    error=str(exc),
                ),
            )

    return ProvidersDistributionResponse(
        source_tenant_id=effective_tenant_id,
        results=results,
    )


# ============================================================================
# Deprecated: Tenant Model Configuration Endpoints
# ============================================================================
# These endpoints are deprecated and will be removed in a future release.
# The /models endpoints should be used instead for all provider/model operations.

tenant_providers_router = APIRouter(
    prefix="/providers",
    tags=["tenant-providers (deprecated)"],
)


@tenant_providers_router.get(
    "",
    summary="Get tenant model configuration (DEPRECATED)",
    deprecated=True,
)
async def get_tenant_providers():
    """Get the current tenant's model configuration (DEPRECATED).

    This endpoint is deprecated. Use /models and /models/active instead.
    Returns the tenant-specific provider configuration from ProviderManager.

    Returns:
        JSON object containing:
        - tenant_id: Current tenant ID
        - providers: List of provider configurations
        - active_model: Currently active model slot

    Raises:
        HTTPException: 400 if tenant ID not set in context
    """
    # Get tenant ID from context
    tenant_id = get_current_effective_tenant_id()
    if tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="Tenant ID not set in context. Ensure request includes tenant identity.",
        )

    # Get tenant-specific provider manager (source of truth)
    ProviderManager.ensure_tenant_provider_storage(tenant_id)
    manager = ProviderManager.get_instance(tenant_id)

    # Get active model from ProviderManager
    active_model = manager.get_active_model()

    # Get provider info list
    provider_infos = await manager.list_provider_info()

    return {
        "tenant_id": tenant_id,
        "providers": [p.model_dump() for p in provider_infos],
        "active_model": active_model.model_dump() if active_model else None,
        "deprecated": True,
        "migration_note": "Use /models and /models/active endpoints instead.",
    }
