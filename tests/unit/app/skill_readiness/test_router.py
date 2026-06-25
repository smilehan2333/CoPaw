# -*- coding: utf-8 -*-
"""技能可执行性 API 路由测试。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient

from swe.app.skill_readiness.models import (
    SkillReadinessOverview,
    SkillReadinessOwnerSummary,
    SkillReadinessResultsPage,
    SkillReadinessRunProgress,
    SkillReadinessStartRunResponse,
)
from swe.app.skill_readiness.router import router


class _Service:
    def __init__(self):
        self.overview_calls = []
        self.start_calls = []
        self.result_calls = []

    async def get_overview(self, source_id, skill_id):
        self.overview_calls.append((source_id, skill_id))
        return SkillReadinessOverview(
            skill_id=skill_id,
            config_found=False,
            startable=False,
            config_message="未查询到自检配置",
            owner_summary=SkillReadinessOwnerSummary(),
        )

    async def start_run(self, source_id, skill_id):
        self.start_calls.append((source_id, skill_id))
        return SkillReadinessStartRunResponse(
            run=SkillReadinessRunProgress(
                run_id="run-1",
                source_id=source_id,
                skill_id=skill_id,
                status="running",
            ),
        )

    async def get_results(self, run_id, **kwargs):
        self.result_calls.append((run_id, kwargs))
        return SkillReadinessResultsPage(
            run=SkillReadinessRunProgress(
                run_id=run_id,
                source_id=kwargs["source_id"],
                skill_id="skill-a",
                status="completed",
            ),
            items=[],
            total=0,
            page=kwargs["page"],
            page_size=kwargs["page_size"],
        )


def _client():
    app = FastAPI()
    service = _Service()
    app.state.skill_readiness_service = service
    app.include_router(router, prefix="/api")
    return TestClient(app), service


def test_overview_requires_manager_role():
    client, _ = _client()

    response = client.get(
        "/api/skill-readiness/skills/skill-a/overview",
        headers={"X-Source-Id": "source-a"},
    )

    assert response.status_code == 403


def test_overview_rejects_missing_source_context():
    client, _ = _client()

    response = client.get(
        "/api/skill-readiness/skills/skill-a/overview",
        headers={"X-User-Role": "manager"},
    )

    assert response.status_code == 400


def test_overview_rejects_invalid_skill_id():
    client, _ = _client()

    response = client.get(
        "/api/skill-readiness/skills/bad%20id/overview",
        headers={"X-User-Role": "manager", "X-Source-Id": "source-a"},
    )

    assert response.status_code == 400


def test_overview_rejects_slash_skill_id_with_api_error_shape():
    client, _ = _client()

    response = client.get(
        "/api/skill-readiness/skills/bad%2Fid/overview",
        headers={"X-User-Role": "manager", "X-Source-Id": "source-a"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid skill_id format"


def test_overview_uses_header_source_and_rejects_query_override():
    client, service = _client()

    ok_response = client.get(
        "/api/skill-readiness/skills/skill-a/overview",
        headers={"X-User-Role": "manager", "X-Source-Id": "source-a"},
    )
    bad_response = client.get(
        "/api/skill-readiness/skills/skill-a/overview?source_id=other",
        headers={"X-User-Role": "manager", "X-Source-Id": "source-a"},
    )

    assert ok_response.status_code == 200
    assert service.overview_calls == [("source-a", "skill-a")]
    assert bad_response.status_code == 400


def test_overview_accepts_chinese_skill_id():
    client, service = _client()
    skill_id = "存款到期客户评分"

    response = client.get(
        f"/api/skill-readiness/skills/{quote(skill_id)}/overview",
        headers={"X-User-Role": "manager", "X-Source-Id": "source-a"},
    )

    assert response.status_code == 200
    assert service.overview_calls == [("source-a", skill_id)]


def test_results_passes_check_failure_filter():
    client, service = _client()

    response = client.get(
        "/api/skill-readiness/runs/run-1/results"
        "?check_name=cron_auth_valid&check_status=fail",
        headers={"X-User-Role": "admin", "X-Source-Id": "source-a"},
    )

    assert response.status_code == 200
    assert service.result_calls[0][1]["check_name"] == "cron_auth_valid"
    assert service.result_calls[0][1]["check_status"] == "fail"
