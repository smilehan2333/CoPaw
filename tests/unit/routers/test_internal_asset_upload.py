# -*- coding: utf-8 -*-
"""公开 asset 文件上传接口测试。"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import swe.app._app as app_module
from swe.app.routers import internal as internal_module
from swe.app.routers.internal import public_router, router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.include_router(public_router)
    return TestClient(app)


def _set_working_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        internal_module,
        "WORKING_DIR",
        tmp_path,
        raising=False,
    )


def _post_upload(
    client: TestClient,
    file_name: str,
    content: bytes,
):
    if file_name:
        return client.post(
            "/assets/upload",
            files={"file": (file_name, content, "application/octet-stream")},
        )

    boundary = "empty-filename-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename=""\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    body += content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    request_headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    return client.post(
        "/assets/upload",
        content=body,
        headers=request_headers,
    )


def test_internal_asset_upload_route_is_not_exposed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()

    response = client.post(
        "/internal/assets/upload",
        files={
            "file": (
                "sample.bin",
                b"content",
                "application/octet-stream",
            ),
        },
    )

    assert response.status_code == 404
    assert not (tmp_path / "asset" / "sample.bin").exists()


def test_public_asset_upload_saves_binary_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()
    content = b"\xff\x00raw-bytes"

    response = client.post(
        "/assets/upload",
        files={
            "file": (
                "sample.bin",
                content,
                "application/octet-stream",
            ),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "file_name": "sample.bin",
        "asset_path": "asset/sample.bin",
        "size": len(content),
    }
    assert (tmp_path / "asset" / "sample.bin").read_bytes() == content


def test_public_asset_upload_saves_file_without_internal_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(
        internal_module,
        "_INTERNAL_TOKEN",
        "secret-token",
        raising=False,
    )
    client = _build_client()

    response = client.post(
        "/assets/upload",
        files={
            "file": (
                "public.bin",
                b"public-content",
                "application/octet-stream",
            ),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "file_name": "public.bin",
        "asset_path": "asset/public.bin",
        "size": len(b"public-content"),
    }
    assert (tmp_path / "asset" / "public.bin").read_bytes() == (
        b"public-content"
    )


def test_main_app_public_asset_upload_is_exposed_without_internal_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(
        internal_module,
        "_INTERNAL_TOKEN",
        "secret-token",
        raising=False,
    )

    with TestClient(
        app_module.app,
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/assets/upload",
            files={
                "file": (
                    "app-public.bin",
                    b"app-public-content",
                    "application/octet-stream",
                ),
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "file_name": "app-public.bin",
        "asset_path": "asset/app-public.bin",
        "size": len(b"app-public-content"),
    }
    assert (tmp_path / "asset" / "app-public.bin").read_bytes() == (
        b"app-public-content"
    )


@pytest.mark.parametrize(
    "file_name",
    [
        "../escape.bin",
        "/tmp/escape.bin",
        "nested/escape.bin",
        "nested\\escape.bin",
        "",
        ".",
        "..",
    ],
)
def test_public_asset_upload_rejects_invalid_file_names(
    monkeypatch,
    tmp_path: Path,
    file_name: str,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()
    outside_file = tmp_path.parent / "escape.bin"
    outside_file.write_bytes(b"original")

    response = _post_upload(client, file_name, b"changed")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid file_name"
    assert outside_file.read_bytes() == b"original"


def test_public_asset_upload_overwrites_matching_file_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_working_dir(monkeypatch, tmp_path)
    asset_dir = tmp_path / "asset"
    asset_dir.mkdir(parents=True)
    target = asset_dir / "replace.bin"
    target.write_bytes(b"old")
    client = _build_client()

    response = client.post(
        "/assets/upload",
        files={
            "file": (
                "replace.bin",
                b"new-content",
                "application/octet-stream",
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["size"] == len(b"new-content")
    assert target.read_bytes() == b"new-content"


def test_public_asset_upload_accepts_template_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """上传时传递 template_flag 表单字段应正常工作。"""
    _set_working_dir(monkeypatch, tmp_path)
    client = _build_client()
    content = b"flagged-content"

    response = client.post(
        "/assets/upload",
        files={"file": ("flagged.bin", content, "application/octet-stream")},
        data={"template_flag": "main-template-1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "file_name": "flagged.bin",
        "asset_path": "asset/flagged.bin",
        "size": len(content),
    }
    assert (tmp_path / "asset" / "flagged.bin").read_bytes() == content
