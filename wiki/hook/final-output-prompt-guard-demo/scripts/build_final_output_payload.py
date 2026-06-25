# -*- coding: utf-8 -*-
"""生成最终输出规范检查 demo 的最小 BeforeStop HookContext 样本。"""

from __future__ import annotations

import argparse
import json


def build_payload(*, passing: bool) -> dict[str, object]:
    """构造用于调试 prompt 判断规则的结束前检查示例。"""
    base: dict[str, object] = {
        "session_id": "demo-session",
        "transcript_path": "/tmp/demo-session.json",
        "cwd": "/workspace/project",
        "workspace_dir": "/workspace/project",
        "hook_event_name": "BeforeStop",
        "tenant_id": "default",
        "effective_tenant_id": "default",
        "user_id": "user-1",
        "agent_id": "demo-agent",
        "channel": "console",
        "prompt": "请修改登录校验逻辑，并在最终回复里说明改了什么、跑了哪些测试、还有哪些限制。",
        "tool_name": "execute_shell_command",
        "tool_input": {
            "command": "venv/bin/python -m pytest tests/unit/auth/test_login.py",
        },
    }
    if passing:
        base["tool_response"] = "3 passed in 0.42s"
        base["assistant_response"] = (
            "已调整登录校验逻辑，覆盖空 token 和过期 token 两类分支。"
            "验证：已运行 `venv/bin/python -m pytest tests/unit/auth/test_login.py`，"
            "结果为 3 passed。限制：尚未运行完整回归测试。"
        )
    else:
        base["assistant_response"] = "登录校验已经修好，测试都通过了。"
    return base


def main() -> int:
    """把调试 payload 打印到 stdout。"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        choices=("pass", "block"),
        default="block",
        help="选择生成合规样本还是应被阻断的样本。",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            build_payload(passing=args.case == "pass"),
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
