---
name: conditional-pre-tool-use-demo
description: "Use this skill when you need a PreToolUse command hook example that demonstrates the hook-level if expression, so the handler only runs for matching tool input such as risky shell commands."
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.0"
  swe:
    uses_tools:
      - execute_shell_command
---

# Conditional PreToolUse Demo

这个样例演示 skill 级 `PreToolUse + command handler + if`。它适合客户想减少 hook 误触发，只在工具输入满足某个轻量条件时才执行脚本。

## 覆盖点

- 事件：`PreToolUse`
- handler 类型：`command`
- 条件过滤：`if`
- 目的：只在 shell 命令包含高风险关键词时执行 handler

## 关键说明

- `if` 表达式在 handler 执行前判断；结果为假时不会启动脚本。
- 示例条件是：

```text
tool_name == 'execute_shell_command' and ('curl' in tool_input['command'] or 'rm -rf' in tool_input['command'])
```

- 条件语法建议保持简单，只用字段读取、`==`、`in`、`and`、`or`。
- 条件写错时通常表现为 handler 没命中，所以生产配置应从简单表达式开始验证。

## 行为说明

- 命令包含 `rm -rf`：返回 `deny`
- 命令包含 `curl` 且 URL 不是公司允许域名：返回 `ask`
- 其他命中条件的命令：返回 `allow`
- 未命中 `if` 条件的命令：脚本不会执行

## 目录内容

1. `hooks/hooks.json`
2. `scripts/check_conditional_shell.py`
3. 当前 `SKILL.md`
