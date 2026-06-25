# -*- coding: utf-8 -*-
"""技能拥有用户聚合。"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .models import SkillReadinessOwner

_DEFAULT_MARKET_BASE_URL = "http://127.0.0.1:8091/api"
_MARKETPLACE_SOURCE_PREFIX = "marketplace:"
_DEFAULT_OWNER_LOOKUP_CONCURRENCY = 20


class SourceUserProvider(Protocol):
    """按 source 查询当前用户集合的最小接口。"""

    async def list_source_users(self, source_id: str) -> list[SkillReadinessOwner]:
        """返回当前 source 下的用户。"""


class MarketSkillClient(Protocol):
    """按用户查询市场技能的最小接口。"""

    async def list_user_skills(
        self,
        source_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """返回用户创建和接收的市场技能。"""


@dataclass(slots=True)
class OwnerLookupResult:
    """拥有用户查询结果。"""

    owners: list[SkillReadinessOwner]
    total_users: int
    failed_users: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def failure_summary(self) -> str | None:
        if not self.failures:
            return None
        return "; ".join(self.failures[:5])

    def as_summary(self) -> dict[str, Any]:
        return {
            "total_users": self.total_users,
            "owner_users": len(self.owners),
            "failed_users": self.failed_users,
            "failure_summary": self.failure_summary,
        }


class TenantInitSourceUserProvider:
    """通过租户初始化来源表读取当前 source 用户。"""

    def __init__(self, store: Any | None = None):
        self.store = store

    async def list_source_users(self, source_id: str) -> list[SkillReadinessOwner]:
        store = self.store
        if store is None:
            from ..workspace.tenant_init_source_store import (
                get_tenant_init_source_store,
            )

            store = get_tenant_init_source_store()
        if store is None:
            raise RuntimeError("tenant init source store is unavailable")

        rows = await store.get_by_source(source_id, include_templates=False)
        return [
            SkillReadinessOwner(
                user_id=str(row["tenant_id"]),
                user_name=row.get("tenant_name"),
                bbk_id=row.get("bbk_id"),
            )
            for row in rows
            if row.get("tenant_id")
        ]


class HttpMarketSkillClient:
    """调用 market 服务的 mine/received 技能接口。"""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.base_url = (
            base_url
            or os.getenv("SWE_MARKET_API_BASE_URL")
            or os.getenv("MARKET_API_BASE_URL")
            or _DEFAULT_MARKET_BASE_URL
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("SWE_MARKET_API_TIMEOUT_SECONDS", "10"),
        )

    async def list_user_skills(
        self,
        source_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        headers = {
            "X-Source-Id": source_id,
            "X-User-Id": user_id,
            "X-Tenant-Id": user_id,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            mine, received = await _gather_market_skill_lists(
                client,
                self.base_url,
                headers,
            )
        return _dedupe_skills([*mine, *received])


async def _gather_market_skill_lists(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mine_response, received_response = await asyncio.gather(
        client.get(
            f"{base_url}/market/skills/mine",
            headers=headers,
        ),
        client.get(
            f"{base_url}/market/skills/received",
            headers=headers,
        ),
    )
    mine_response.raise_for_status()
    received_response.raise_for_status()
    return (
        _coerce_skill_list(mine_response.json()),
        _coerce_skill_list(received_response.json()),
    )


def _coerce_skill_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe_skills(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skill in skills:
        key = str(
            skill.get("skill_id")
            or skill.get("item_id")
            or skill.get("source")
            or skill.get("skill_name")
            or "",
        )
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(skill)
    return deduped


class SkillOwnerResolver:
    """聚合 source 用户和 market 技能拥有关系。"""

    def __init__(
        self,
        source_user_provider: SourceUserProvider | None = None,
        market_client: MarketSkillClient | None = None,
        lookup_concurrency: int | None = None,
    ):
        self.source_user_provider = (
            source_user_provider or TenantInitSourceUserProvider()
        )
        self.market_client = market_client or HttpMarketSkillClient()
        configured_concurrency = lookup_concurrency or int(
            os.getenv(
                "SWE_SKILL_READINESS_OWNER_LOOKUP_CONCURRENCY",
                str(_DEFAULT_OWNER_LOOKUP_CONCURRENCY),
            ),
        )
        self.lookup_concurrency = max(1, configured_concurrency)

    async def resolve_owners(
        self,
        source_id: str,
        skill_id: str,
    ) -> OwnerLookupResult:
        users = await self.source_user_provider.list_source_users(source_id)
        owners: dict[str, SkillReadinessOwner] = {}
        failures: list[str] = []
        semaphore = asyncio.Semaphore(self.lookup_concurrency)

        results = await asyncio.gather(
            *[
                self._lookup_one_user(source_id, skill_id, user, semaphore)
                for user in users
            ],
        )
        for user, error in results:
            if error is not None:
                failures.append(error)
            elif user is not None:
                owners[user.user_id] = user

        return OwnerLookupResult(
            owners=list(owners.values()),
            total_users=len(users),
            failed_users=len(failures),
            failures=failures,
        )

    async def _lookup_one_user(
        self,
        source_id: str,
        skill_id: str,
        user: SkillReadinessOwner,
        semaphore: asyncio.Semaphore,
    ) -> tuple[SkillReadinessOwner | None, str | None]:
        """有界并发查询单个用户技能，避免大量用户时串行等待。"""
        async with semaphore:
            try:
                skills = await self.market_client.list_user_skills(
                    source_id,
                    user.user_id,
                )
            except Exception as exc:  # noqa: BLE001
                return None, f"{user.user_id}: {exc}"

            matched_skill = _find_matching_skill(skills, skill_id)
            if matched_skill is not None:
                return _owner_with_skill(user, matched_skill), None
        return None, None


def _find_matching_skill(
    skills: list[dict[str, Any]],
    skill_id: str,
) -> dict[str, Any] | None:
    for skill in skills:
        if _skill_matches(skill, skill_id):
            return skill
    return None


def _owner_with_skill(
    user: SkillReadinessOwner,
    skill: dict[str, Any],
) -> SkillReadinessOwner:
    skill_version = _text_or_none(skill.get("version"))
    received_version = _text_or_none(skill.get("received_version"))
    installed_version = (
        _text_or_none(skill.get("installed_version"))
        or received_version
        or skill_version
    )
    market_version = (
        _text_or_none(skill.get("market_version"))
        or _text_or_none(skill.get("latest_version"))
        or skill_version
    )
    has_update = _bool_or_none(skill.get("has_update"))
    if has_update is None:
        has_update = bool(
            market_version
            and installed_version
            and market_version != installed_version,
        )
    return user.model_copy(
        update={
            "skill_name": _text_or_none(
                skill.get("skill_name") or skill.get("name"),
            ),
            "market_version": market_version,
            "installed_version": installed_version,
            "received_version": received_version,
            "enabled": _bool_or_none(skill.get("enabled")),
            "has_update": has_update,
        },
    )


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _skill_matches(skill: dict[str, Any], skill_id: str) -> bool:
    market_skill_id = str(skill.get("skill_id") or "").strip()
    if market_skill_id and market_skill_id == skill_id:
        return True

    item_id = str(skill.get("item_id") or "").strip()
    if item_id and item_id == skill_id:
        return True

    source = str(skill.get("source") or "").strip()
    if source.startswith(_MARKETPLACE_SOURCE_PREFIX):
        source_item_id = source[len(_MARKETPLACE_SOURCE_PREFIX) :]
        if source_item_id == skill_id:
            return True

    skill_name = str(skill.get("skill_name") or skill.get("name") or "").strip()
    return bool(skill_name and skill_name == skill_id)
