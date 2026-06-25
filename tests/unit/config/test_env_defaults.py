# -*- coding: utf-8 -*-
"""Tests for environment defaults loader."""

from __future__ import annotations

import os

import pytest

from swe.config.envs import (
    DEFAULT_ENV,
    VALID_ENVS,
    get_current_env,
    load_env_defaults,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove test-related env vars before each test."""
    test_vars = [
        "SWE_ENV",
        "SWE_LOG_LEVEL",
        "SWE_OPENAPI_DOCS",
        "SWE_FILE_LOG_ENABLED",
        "SWE_CORS_ORIGINS",
        "SWE_LLM_MAX_CONCURRENT",
        "SWE_LLM_MAX_QPM",
        "SWE_AUTH_ENABLED",
        "SWE_ENABLED_CHANNELS",
        "SWE_DISABLED_CHANNELS",
    ]
    for var in test_vars:
        monkeypatch.delenv(var, raising=False)


class TestEnvDefaultsLoader:
    """Tests for environment defaults loading."""

    def test_valid_envs_contains_dev_and_prd(self):
        """Valid environments should be dev and prd."""
        assert "dev" in VALID_ENVS
        assert "prd" in VALID_ENVS

    def test_default_env_is_dev(self):
        """默认环境应为 dev。"""
        assert DEFAULT_ENV == "dev"

    def test_get_current_env_defaults_to_dev(self, monkeypatch):
        """未设置 SWE_ENV 时应返回 dev。"""
        monkeypatch.delenv("SWE_ENV", raising=False)
        assert get_current_env() == "dev"

    def test_get_current_env_respects_swe_env(self, monkeypatch):
        """get_current_env should return value of SWE_ENV."""
        monkeypatch.setenv("SWE_ENV", "dev")
        assert get_current_env() == "dev"

    def test_load_dev_defaults(self, monkeypatch):
        """load_env_defaults should load dev.json values."""
        result = load_env_defaults("dev")

        assert "SWE_LOG_LEVEL" in result
        assert os.environ.get("SWE_LOG_LEVEL") == "debug"
        assert os.environ.get("SWE_OPENAPI_DOCS") == "true"
        assert "SWE_FILE_LOG_ENABLED" not in result
        assert os.environ.get("SWE_FILE_LOG_ENABLED") is None
        assert os.environ.get("SWE_AUTH_ENABLED") == "false"

    def test_load_prd_defaults(self, monkeypatch):
        """load_env_defaults should load prd.json values."""
        result = load_env_defaults("prd")

        assert "SWE_LOG_LEVEL" in result
        assert os.environ.get("SWE_LOG_LEVEL") == "info"
        assert os.environ.get("SWE_OPENAPI_DOCS") == "false"
        assert "SWE_FILE_LOG_ENABLED" not in result
        assert os.environ.get("SWE_FILE_LOG_ENABLED") is None

    def test_does_not_override_existing_env(self, monkeypatch):
        """load_env_defaults should not override existing env vars."""
        monkeypatch.setenv("SWE_LOG_LEVEL", "warning")

        result = load_env_defaults("dev")

        # Should not have set SWE_LOG_LEVEL since it already existed
        assert "SWE_LOG_LEVEL" not in result
        assert os.environ.get("SWE_LOG_LEVEL") == "warning"

    def test_invalid_env_falls_back_to_dev(self, monkeypatch):
        """非法 SWE_ENV 应回退到 dev。"""
        result = load_env_defaults("invalid")

        assert os.environ.get("SWE_LOG_LEVEL") == "debug"
        assert os.environ.get("SWE_OPENAPI_DOCS") == "true"

    def test_returns_empty_dict_when_all_vars_exist(self, monkeypatch):
        """load_env_defaults should return empty dict when all vars exist."""
        # Set all dev vars
        monkeypatch.setenv("SWE_LOG_LEVEL", "test")
        monkeypatch.setenv("SWE_OPENAPI_DOCS", "test")
        monkeypatch.setenv("SWE_CORS_ORIGINS", "test")
        monkeypatch.setenv("SWE_LLM_MAX_CONCURRENT", "test")
        monkeypatch.setenv("SWE_LLM_MAX_QPM", "test")
        monkeypatch.setenv("SWE_AUTH_ENABLED", "test")
        monkeypatch.setenv("SWE_ENABLED_CHANNELS", "test")
        monkeypatch.setenv("SWE_DISABLED_CHANNELS", "test")

        result = load_env_defaults("dev")

        assert result == {}
