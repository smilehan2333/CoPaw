# -*- coding: utf-8 -*-
"""Regression tests for removing file-backed daemon log commands."""

from __future__ import annotations

from click.testing import CliRunner

from swe.app.channels.command_registry import CommandRegistry
from swe.app.runner import daemon_commands
from swe.cli.daemon_cmd import daemon_group


def test_daemon_logs_query_is_not_registered() -> None:
    assert "logs" not in daemon_commands.DAEMON_SUBCOMMANDS
    assert "logs" not in daemon_commands.DAEMON_SHORT_ALIASES
    assert daemon_commands.parse_daemon_query("/daemon logs") is None
    assert daemon_commands.parse_daemon_query("/logs") is None


def test_command_registry_no_longer_prioritizes_log_commands() -> None:
    registry = CommandRegistry()

    assert not registry.is_registered("/daemon logs")
    assert not registry.is_registered("/logs")
    assert not registry.is_control_command("/daemon logs")
    assert not registry.is_control_command("/logs")
    assert registry.get_priority_level("/daemon logs") == 20
    assert registry.get_priority_level("/logs") == 20


def test_cli_daemon_logs_command_is_removed() -> None:
    result = CliRunner().invoke(daemon_group, ["logs"])

    assert result.exit_code != 0
    assert "No such command 'logs'" in result.output
