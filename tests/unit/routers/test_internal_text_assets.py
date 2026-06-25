# -*- coding: utf-8 -*-
"""Tests for internal text asset APIs."""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import swe.app._app as app_module
import swe.app.auth as auth_module
import swe.constant as constant_module
from swe.app.routers import internal as internal_module
from swe.app.routers.internal import public_router, router
from swe.config.context import encode_scope_id


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.include_router(public_router)
    app.state.multi_agent_manager = SimpleNamespace(
        reload_agent=AsyncMock(return_value=True),
    )
    return TestClient(app)


def _set_working_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        internal_module,
        "WORKING_DIR",
        tmp_path,
        raising=False,
    )


def _set_app_working_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        app_module,
        "WORKING_DIR",
        tmp_path,
        raising=False,
    )
    monkeypatch.setattr(
        constant_module,
        "WORKING_DIR",
        tmp_path,
        raising=False,
    )


def test_internal_text_asset_read_route_is_not_exposed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()

    response = client.get("/internal/assets/text/read?file_name=guide.txt")

    assert response.status_code == 404


def test_internal_text_asset_write_route_is_not_exposed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()

    response = client.post(
        "/internal/assets/text/write",
        json={
            "user_id": "alice",
            "source_id": "portal",
            "content": "<p>hello</p>",
        },
    )

    assert response.status_code == 404


def test_internal_text_asset_preview_path_creates_placeholder_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("FILE_URL", "https://files.example")
    client = _build_client()
    scope_id = encode_scope_id("alice", "portal")

    response = client.post(
        "/internal/assets/text/preview-path",
        json={"user_id": "alice", "source_id": "portal"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["scope_id"] == scope_id
    assert re.match(r"^alice-\d{17}\.html$", payload["file_name"])
    assert payload["public_url"] == (
        f"https://files.example/static/{scope_id}/default/"
        f"{payload['file_name']}"
    )
    assert payload["static_path"] == (
        f"/static/{scope_id}/default/{payload['file_name']}"
    )

    stored_file = (
        tmp_path
        / scope_id
        / "workspaces"
        / "default"
        / "static"
        / payload["file_name"]
    )
    placeholder_html = stored_file.read_text(encoding="utf-8")
    assert placeholder_html.startswith("<!doctype html>")
    assert "<title>文件正在生成中</title>" in placeholder_html
    assert "<h1>文件正在生成中</h1>" in placeholder_html
    assert "内容准备完成后，页面会自动展示最新预览。" in placeholder_html


def test_internal_text_asset_preview_path_recreates_named_placeholder_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("FILE_URL", "https://files.example")
    client = _build_client()
    scope_id = encode_scope_id("alice", "portal")
    static_dir = tmp_path / scope_id / "workspaces" / "default" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    existing_file = static_dir / "draft.html"
    existing_file.write_text("<main>old</main>", encoding="utf-8")

    response = client.post(
        "/internal/assets/text/preview-path",
        json={
            "user_id": "alice",
            "source_id": "portal",
            "file_name": "draft",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_name"] == "draft.html"
    assert payload["scope_id"] == scope_id
    assert payload["public_url"] == (
        f"https://files.example/static/{scope_id}/default/draft.html"
    )
    assert payload["static_path"] == f"/static/{scope_id}/default/draft.html"

    placeholder_html = existing_file.read_text(encoding="utf-8")
    assert "<main>old</main>" not in placeholder_html
    assert "<title>文件正在生成中</title>" in placeholder_html


def test_main_app_preview_path_returns_immediately_viewable_placeholder(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    _set_app_working_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("FILE_URL", "http://testserver")

    with TestClient(
        app_module.app,
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/internal/assets/text/preview-path",
            json={"user_id": "alice", "source_id": "portal"},
        )
        payload = response.json()
        static_response = client.get(payload["static_path"])

    assert response.status_code == 200
    assert static_response.status_code == 200
    assert "text/html" in static_response.headers["content-type"].lower()
    assert static_response.text.startswith("<!doctype html>")
    assert "文件正在生成中" in static_response.text
    assert "内容准备完成后，页面会自动展示最新预览。" in static_response.text


def test_public_text_asset_write_overwrites_preview_url_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("FILE_URL", "https://files.example")
    client = _build_client()
    preview = client.post(
        "/internal/assets/text/preview-path",
        json={"user_id": "alice", "source_id": "portal"},
    ).json()

    response = client.post(
        "/assets/text/write",
        json={
            "user_id": "alice",
            "source_id": "portal",
            "content": "<main>ready</main>",
            "preview_url": preview["public_url"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_name"] == preview["file_name"]
    assert payload["scope_id"] == preview["scope_id"]
    assert payload["public_url"] == preview["public_url"]
    stored_file = (
        tmp_path
        / preview["scope_id"]
        / "workspaces"
        / "default"
        / "static"
        / preview["file_name"]
    )
    assert stored_file.read_text(encoding="utf-8") == "<main>ready</main>"


def test_public_text_asset_write_overwrites_preview_static_path_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("FILE_URL", "https://files.example")
    client = _build_client()
    preview = client.post(
        "/internal/assets/text/preview-path",
        json={"user_id": "alice", "source_id": "portal"},
    ).json()

    response = client.post(
        "/assets/text/write",
        json={
            "user_id": "alice",
            "source_id": "portal",
            "content": "<main>ready</main>",
            "preview_url": preview["static_path"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_name"] == preview["file_name"]
    assert payload["public_url"] == preview["public_url"]
    assert (
        tmp_path
        / preview["scope_id"]
        / "workspaces"
        / "default"
        / "static"
        / preview["file_name"]
    ).read_text(encoding="utf-8") == "<main>ready</main>"


def test_public_text_asset_write_without_preview_target_creates_new_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    generated_names = iter(
        [
            "alice-preview.html",
            "alice-generated.html",
        ],
    )
    monkeypatch.setattr(
        internal_module,
        "_generate_text_asset_file_name",
        lambda _user_id: next(generated_names),
    )
    client = _build_client()
    preview = client.post(
        "/internal/assets/text/preview-path",
        json={"user_id": "alice", "source_id": "portal"},
    ).json()

    response = client.post(
        "/assets/text/write",
        json={
            "user_id": "alice",
            "source_id": "portal",
            "content": "<main>separate</main>",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_name"] != preview["file_name"]
    preview_file = (
        tmp_path
        / preview["scope_id"]
        / "workspaces"
        / "default"
        / "static"
        / preview["file_name"]
    )
    generated_file = preview_file.with_name(payload["file_name"])
    assert "文件正在生成中" in preview_file.read_text(encoding="utf-8")
    assert (
        generated_file.read_text(encoding="utf-8") == "<main>separate</main>"
    )


def test_public_text_asset_write_rejects_invalid_utf8_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()

    response = client.post(
        "/assets/text/write",
        content=(
            b'{"user_id":"alice","source_id":"portal",' b'"content":"\\ud800"}'
        ),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Content is not valid UTF-8"


def test_internal_text_asset_preview_path_rejects_invalid_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()

    response = client.post(
        "/internal/assets/text/preview-path",
        json={"user_id": "../alice", "source_id": "portal"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid user_id"


def test_public_text_asset_write_rejects_cross_scope_preview_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()
    preview = client.post(
        "/internal/assets/text/preview-path",
        json={"user_id": "alice", "source_id": "portal"},
    ).json()

    response = client.post(
        "/assets/text/write",
        json={
            "user_id": "bob",
            "source_id": "portal",
            "content": "<main>wrong</main>",
            "preview_url": preview["static_path"],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid preview target"
    preview_html = (
        tmp_path
        / preview["scope_id"]
        / "workspaces"
        / "default"
        / "static"
        / preview["file_name"]
    ).read_text(encoding="utf-8")
    assert "文件正在生成中" in preview_html


def test_public_text_asset_write_rejects_traversal_preview_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()
    scope_id = encode_scope_id("alice", "portal")

    response = client.post(
        "/assets/text/write",
        json={
            "user_id": "alice",
            "source_id": "portal",
            "content": "<main>wrong</main>",
            "preview_url": f"/static/{scope_id}/default/../escape.html",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid preview target"
    assert not (tmp_path / scope_id / "workspaces").exists()


def test_public_text_asset_write_rejects_non_html_preview_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()
    scope_id = encode_scope_id("alice", "portal")

    response = client.post(
        "/assets/text/write",
        json={
            "user_id": "alice",
            "source_id": "portal",
            "content": "<main>wrong</main>",
            "preview_url": f"/static/{scope_id}/default/preview.txt",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid preview target"
    assert not (tmp_path / scope_id / "workspaces").exists()


def test_public_text_asset_read_returns_utf8_content_without_internal_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    asset_dir = tmp_path / "asset"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "public.txt").write_text("public text", encoding="utf-8")
    client = _build_client()

    response = client.get("/assets/text/read?file_name=public.txt")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "file_name": "public.txt",
        "content": "public text",
    }


def test_public_text_asset_write_creates_scope_static_file_without_internal_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("FILE_URL", "https://files.example")
    client = _build_client()
    scope_id = encode_scope_id("guest", "portal")

    response = client.post(
        "/assets/text/write",
        json={
            "user_id": "guest",
            "source_id": "portal",
            "content": "<p>public write</p>",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope_id"] == scope_id
    assert payload["public_url"] == (
        f"https://files.example/static/{scope_id}/default/"
        f"{payload['file_name']}"
    )
    assert (
        tmp_path
        / scope_id
        / "workspaces"
        / "default"
        / "static"
        / payload["file_name"]
    ).read_text(encoding="utf-8") == "<p>public write</p>"


def test_main_app_public_text_asset_read_skips_tenant_headers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    _set_app_working_dir(monkeypatch, tmp_path)
    asset_dir = tmp_path / "asset"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "public.txt").write_text("public text", encoding="utf-8")

    with TestClient(
        app_module.app,
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/api/assets/text/read?file_name=public.txt")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "file_name": "public.txt",
        "content": "public text",
    }


def test_main_app_public_text_asset_write_skips_tenant_headers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    _set_app_working_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("FILE_URL", "https://files.example")
    scope_id = encode_scope_id("guest", "portal")

    with TestClient(
        app_module.app,
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/assets/text/write",
            json={
                "user_id": "guest",
                "source_id": "portal",
                "content": "<p>public write</p>",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope_id"] == scope_id
    assert payload["public_url"] == (
        f"https://files.example/static/{scope_id}/default/"
        f"{payload['file_name']}"
    )
    assert (
        tmp_path
        / scope_id
        / "workspaces"
        / "default"
        / "static"
        / payload["file_name"]
    ).read_text(encoding="utf-8") == "<p>public write</p>"


def test_main_app_static_html_returns_text_html_content_type(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_app_working_dir(monkeypatch, tmp_path)
    static_file = (
        tmp_path / "mimecheck" / "workspaces" / "default" / "static" / "x.html"
    )
    static_file.parent.mkdir(parents=True, exist_ok=True)
    static_file.write_text("<p>mime ok</p>", encoding="utf-8")

    with TestClient(
        app_module.app,
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/static/mimecheck/default/x.html")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"].lower()


def test_main_app_runtime_static_html_skips_gzip_when_requested(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_app_working_dir(monkeypatch, tmp_path)
    body = "<!doctype html><p>runtime static html stays plain</p>\n" * 200
    static_file = (
        tmp_path
        / "gzipscope"
        / "workspaces"
        / "default"
        / "static"
        / "report.html"
    )
    static_file.parent.mkdir(parents=True, exist_ok=True)
    static_file.write_bytes(body.encode("utf-8"))

    with TestClient(
        app_module.app,
        raise_server_exceptions=False,
    ) as client:
        response = client.get(
            "/static/gzipscope/default/report.html",
            headers={"Accept-Encoding": "gzip"},
        )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.text == body


def test_main_app_runtime_static_non_html_skips_gzip(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_app_working_dir(monkeypatch, tmp_path)
    body = "runtime static text stays plain\n" * 200
    static_file = (
        tmp_path
        / "gzipscope"
        / "workspaces"
        / "default"
        / "static"
        / "report.txt"
    )
    static_file.parent.mkdir(parents=True, exist_ok=True)
    static_file.write_bytes(body.encode("utf-8"))

    with TestClient(
        app_module.app,
        raise_server_exceptions=False,
    ) as client:
        response = client.get(
            "/static/gzipscope/default/report.txt",
            headers={"Accept-Encoding": "gzip"},
        )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.text == body


def test_main_app_console_static_file_skips_runtime_gzip(
    monkeypatch,
    tmp_path: Path,
) -> None:
    asset_dir = tmp_path / "console-assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    body = "console static stays plain\n" * 200
    (asset_dir / "app.txt").write_bytes(body.encode("utf-8"))
    monkeypatch.setattr(app_module, "_assets_dir", asset_dir, raising=False)

    with TestClient(
        app_module.app,
        raise_server_exceptions=False,
    ) as client:
        response = client.get(
            "/static/app.txt",
            headers={"Accept-Encoding": "gzip"},
        )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.text == body


def test_main_app_public_text_asset_read_skips_auth_when_enabled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    _set_app_working_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_module, "has_registered_users", lambda: True)
    asset_dir = tmp_path / "asset"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "public.txt").write_text("public text", encoding="utf-8")

    with TestClient(
        app_module.app,
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/api/assets/text/read?file_name=public.txt")

    assert response.status_code == 200
    assert response.json()["content"] == "public text"
