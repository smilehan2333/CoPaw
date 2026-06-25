# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError

from swe.agents.hook_runtime.models import HookEventName
from swe.config.config import AgentProfileConfig, Config


def test_root_and_agent_config_parse_hook_matcher_groups() -> None:
    hook_data = {
        "enabled": True,
        "events": {
            "PreToolUse": [
                {
                    "id": "shells",
                    "matcher": {"tools": ["execute_shell_command"]},
                    "hooks": [
                        {
                            "id": "audit",
                            "type": "command",
                            "argv": ["python", "hooks/audit.py"],
                            "if": "tool_name == 'execute_shell_command'",
                            "timeout": 2,
                            "statusMessage": "Checking command",
                            "once": True,
                            "failPolicy": "block",
                        },
                    ],
                },
            ],
        },
    }

    root = Config.model_validate({"hooks": hook_data})
    agent = AgentProfileConfig.model_validate(
        {
            "id": "agent-1",
            "name": "Agent",
            "hooks": hook_data,
        },
    )

    root_handler = root.hooks.events[HookEventName.PRE_TOOL_USE][0].hooks[0]
    agent_handler = agent.hooks.events[HookEventName.PRE_TOOL_USE][0].hooks[0]
    assert root.hooks.enabled is True
    assert root_handler.id == "audit"
    assert root_handler.fail_policy == "block"
    assert agent_handler.once is True


def test_config_parses_handler_conversation_snapshot_options() -> None:
    hook_data = {
        "enabled": True,
        "events": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "id": "prompt-policy",
                            "type": "prompt",
                            "prompt": "Review current conversation.",
                            "includeConversationSnapshot": True,
                            "conversationSnapshotLimit": 75,
                        },
                    ],
                },
            ],
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "id": "http-policy",
                            "type": "http",
                            "url": "https://hooks.example.test/policy",
                            "includeConversationSnapshot": True,
                        },
                    ],
                },
            ],
        },
    }

    root = Config.model_validate({"hooks": hook_data})
    agent = AgentProfileConfig.model_validate(
        {
            "id": "agent-1",
            "name": "Agent",
            "hooks": hook_data,
        },
    )

    root_prompt = root.hooks.events[HookEventName.USER_PROMPT_SUBMIT][0].hooks[
        0
    ]
    root_http = root.hooks.events[HookEventName.PRE_TOOL_USE][0].hooks[0]
    agent_prompt = agent.hooks.events[HookEventName.USER_PROMPT_SUBMIT][
        0
    ].hooks[0]
    assert root_prompt.include_conversation_snapshot is True
    assert root_prompt.conversation_snapshot_limit == 75
    assert root_http.include_conversation_snapshot is True
    assert root_http.conversation_snapshot_limit == 50
    assert agent_prompt.include_conversation_snapshot is True


def test_config_rejects_unsupported_mvp_hook_handler_type() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "hooks": {
                    "enabled": True,
                    "events": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "id": "unsupported",
                                        "type": "agent",
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
        )


def test_config_parses_skill_hook_http_approved_urls() -> None:
    cfg = Config.model_validate(
        {
            "security": {
                "skill_hook_http": {
                    "approved_urls": [
                        "https://hooks.example.test/skill",
                    ],
                },
            },
        },
    )

    assert cfg.security.skill_hook_http.approved_urls == [
        "https://hooks.example.test/skill",
    ]


def test_root_and_agent_config_parse_prompt_hook_handlers() -> None:
    hook_data = {
        "enabled": True,
        "events": {
            "UserPromptSubmit": [
                {
                    "id": "prompts",
                    "hooks": [
                        {
                            "id": "policy",
                            "type": "prompt",
                            "prompt": "Reject requests that ask for secrets.",
                            "if": "prompt",
                            "timeout": 3,
                            "statusMessage": "Checking policy",
                            "once": True,
                        },
                    ],
                },
            ],
        },
    }

    root = Config.model_validate({"hooks": hook_data})
    agent = AgentProfileConfig.model_validate(
        {"id": "agent-1", "name": "Agent", "hooks": hook_data},
    )

    root_handler = root.hooks.events[HookEventName.USER_PROMPT_SUBMIT][
        0
    ].hooks[0]
    agent_handler = agent.hooks.events[HookEventName.USER_PROMPT_SUBMIT][
        0
    ].hooks[0]
    assert root_handler.type == "prompt"
    assert root_handler.prompt == "Reject requests that ask for secrets."
    assert root_handler.fail_policy == "block"
    assert agent_handler.once is True


@pytest.mark.parametrize("event_name", ["PostToolUse", "PostToolUseFailure"])
def test_prompt_hook_handler_rejects_non_blockable_events(
    event_name: str,
) -> None:
    with pytest.raises(ValidationError, match="blockable"):
        Config.model_validate(
            {
                "hooks": {
                    "enabled": True,
                    "events": {
                        event_name: [
                            {
                                "hooks": [
                                    {
                                        "id": "policy",
                                        "type": "prompt",
                                        "prompt": "Reject risky output.",
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
        )


@pytest.mark.parametrize(
    "handler_update",
    [
        {"prompt": "   "},
        {"model": "gpt-test"},
        {"provider": "openai"},
        {"providerId": "builtin"},
        {"baseUrl": "https://example.test"},
        {"promptFile": "policy.md"},
        {"template": "{{context}}"},
        {"unknown": True},
    ],
)
def test_prompt_hook_handler_rejects_empty_and_override_fields(
    handler_update: dict,
) -> None:
    handler = {
        "id": "policy",
        "type": "prompt",
        "prompt": "Reject risky requests.",
    }
    handler.update(handler_update)

    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "hooks": {
                    "enabled": True,
                    "events": {"PreToolUse": [{"hooks": [handler]}]},
                },
            },
        )
