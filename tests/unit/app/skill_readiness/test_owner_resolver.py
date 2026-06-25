# -*- coding: utf-8 -*-
"""技能可执行性 owner 聚合测试。"""

from __future__ import annotations

import pytest

from swe.app.skill_readiness.models import SkillReadinessOwner
from swe.app.skill_readiness.owner_resolver import SkillOwnerResolver


class _Users:
    async def list_source_users(self, source_id):
        assert source_id == "source-a"
        return [
            SkillReadinessOwner(
                user_id="alice",
                user_name="Alice",
                bbk_id="001",
            ),
            SkillReadinessOwner(user_id="bob"),
            SkillReadinessOwner(user_id="cathy"),
        ]


class _Market:
    async def list_user_skills(self, source_id, user_id):
        if user_id == "alice":
            return [
                {
                    "skill_id": "skill-a",
                    "skill_name": "same-name",
                    "version": "2.0.0",
                    "received_version": "1.0.0",
                    "enabled": True,
                    "has_update": True,
                },
            ]
        if user_id == "bob":
            return [
                {
                    "source": "marketplace:skill-a",
                    "skill_name": "x",
                    "version": "2.0.0",
                    "enabled": False,
                },
            ]
        raise RuntimeError("market down")


@pytest.mark.asyncio
async def test_owner_resolver_matches_skill_id_source_and_keeps_failures():
    resolver = SkillOwnerResolver(
        source_user_provider=_Users(),
        market_client=_Market(),
    )

    result = await resolver.resolve_owners("source-a", "skill-a")

    assert [owner.user_id for owner in result.owners] == ["alice", "bob"]
    alice, bob = result.owners
    assert alice.skill_name == "same-name"
    assert alice.market_version == "2.0.0"
    assert alice.installed_version == "1.0.0"
    assert alice.received_version == "1.0.0"
    assert alice.enabled is True
    assert alice.has_update is True
    assert bob.installed_version == "2.0.0"
    assert bob.enabled is False
    assert bob.has_update is False
    assert result.failed_users == 1
    assert "cathy" in (result.failure_summary or "")


class _NameMarket:
    async def list_user_skills(self, source_id, user_id):
        return [{"skill_name": "fallback-name"}]


@pytest.mark.asyncio
async def test_owner_resolver_falls_back_to_skill_name():
    resolver = SkillOwnerResolver(
        source_user_provider=_Users(),
        market_client=_NameMarket(),
    )

    result = await resolver.resolve_owners("source-a", "fallback-name")

    assert [owner.user_id for owner in result.owners] == [
        "alice",
        "bob",
        "cathy",
    ]
