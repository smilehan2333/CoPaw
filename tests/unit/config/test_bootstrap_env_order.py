# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from swe.env_defaults import load_env_defaults
from swe.envs import store


def test_import_swe_loads_dev_defaults_before_constant(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    env["SWE_ENV"] = "dev"
    env["SWE_WORKING_DIR"] = str(tmp_path / ".swe")
    env["SWE_SECRET_DIR"] = str(tmp_path / ".swe.secret")
    env.pop("SWE_OPENAPI_DOCS", None)
    env.pop("SWE_LOG_LEVEL", None)

    script = """
import json
import os
import swe
import swe.constant as constant

print(json.dumps({
    "env_docs": os.environ.get("SWE_OPENAPI_DOCS"),
    "env_log_level": os.environ.get("SWE_LOG_LEVEL"),
    "docs_enabled": constant.DOCS_ENABLED,
    "has_file_log_enabled": hasattr(constant, "FILE_LOG_ENABLED"),
}))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
    )

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {
        "env_docs": "true",
        "env_log_level": "debug",
        "docs_enabled": True,
        "has_file_log_enabled": False,
    }


def test_persisted_envs_override_preloaded_empty_defaults(
    tmp_path,
    monkeypatch,
):
    """持久化环境变量应覆盖已注入的空默认值。"""
    envs_path = tmp_path / "envs.json"
    envs_path.write_text(
        json.dumps(
            {"SWE_CRON_WPLUS_TOKEN_SECRET": "persisted-secret"},
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "_ENVS_JSON", envs_path)
    monkeypatch.delenv("SWE_CRON_WPLUS_TOKEN_SECRET", raising=False)

    load_env_defaults("dev")
    assert os.environ["SWE_CRON_WPLUS_TOKEN_SECRET"] == ""

    store.load_envs_into_environ()

    assert os.environ["SWE_CRON_WPLUS_TOKEN_SECRET"] == "persisted-secret"


def test_persisted_envs_do_not_override_explicit_process_env(
    tmp_path,
    monkeypatch,
):
    """显式进程环境变量应优先于持久化 env。"""
    envs_path = tmp_path / "envs.json"
    envs_path.write_text(
        json.dumps(
            {"SWE_CRON_WPLUS_TOKEN_SECRET": "persisted-secret"},
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "_ENVS_JSON", envs_path)
    monkeypatch.setenv("SWE_CRON_WPLUS_TOKEN_SECRET", "process-secret")

    store.load_envs_into_environ()

    assert os.environ["SWE_CRON_WPLUS_TOKEN_SECRET"] == "process-secret"


def test_import_swe_loads_wplus_secrets_before_constant(tmp_path):
    """导入期常量应读取持久化 WPLUS secret，而不是空默认值。"""
    repo_root = Path(__file__).resolve().parents[3]
    working_dir = tmp_path / ".swe"
    secret_dir = tmp_path / ".swe.secret"
    secret_dir.mkdir()
    persisted = {
        "SWE_CRON_WPLUS_TOKEN_SECRET": "token-from-envs",
        "SWE_CRON_WPLUS_INFO_SECRTET": "info-from-envs",
        "SWE_CRON_WPLUS_PRIVATE_KEY": "key-from-envs",
    }
    (secret_dir / "envs.json").write_text(
        json.dumps(persisted),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    env["SWE_ENV"] = "dev"
    env["SWE_WORKING_DIR"] = str(working_dir)
    env["SWE_SECRET_DIR"] = str(secret_dir)
    for key in persisted:
        env.pop(key, None)

    script = """
import json
import os
import swe
import swe.constant as constant

print(json.dumps({
    "env_token": os.environ.get("SWE_CRON_WPLUS_TOKEN_SECRET"),
    "env_info": os.environ.get("SWE_CRON_WPLUS_INFO_SECRTET"),
    "env_key": os.environ.get("SWE_CRON_WPLUS_PRIVATE_KEY"),
    "const_token": constant.CRON_WPLUS_TOKEN_SECRET,
    "const_info": constant.CRON_WPLUS_INFO_SECRTET,
    "const_key": constant.CRON_WPLUS_PRIVATE_KEY,
}))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
    )

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {
        "env_token": "token-from-envs",
        "env_info": "info-from-envs",
        "env_key": "key-from-envs",
        "const_token": "token-from-envs",
        "const_info": "info-from-envs",
        "const_key": "key-from-envs",
    }
