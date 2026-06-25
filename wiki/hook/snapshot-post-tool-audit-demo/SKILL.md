---
name: snapshot-post-tool-audit-demo
description: "Use this skill when you need a PostToolUse command hook example that enables includeConversationSnapshot and writes an audit summary from both tool_response and recent conversation context."
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.0"
  swe:
    uses_tools:
      - execute_shell_command
---

# Snapshot PostTool Audit Demo

这个样例演示 skill 级 `PostToolUse + command handler`，并在单个 handler 上打开 `includeConversationSnapshot`。它适合客户需要把“当前工具结果”和“最近对话上下文”一起用于审计或摘要。

## 覆盖点

- 事件：`PostToolUse`
- handler 类型：`command`
- 快照开关：`includeConversationSnapshot`
- 目的：基于 `tool_response` 和 `conversation_snapshot_meta` 注入审计摘要

## 关键说明

- `tool_response` 是当前工具调用的业务结果，应优先读取。
- `conversation_snapshot` 是最近对话裁剪，不是完整 transcript。
- 快照是 handler 级开关，只影响当前 handler。
- `PostToolUse` 已经发生在工具执行成功之后，不能撤销工具调用。

## 行为说明

脚本会返回 `additionalContext`，包含：

- 当前事件名
- 工具名和 `tool_use_id`
- 工具结果短摘要
- 快照包含消息数、截断数和限制数

## 目录内容

1. `hooks/hooks.json`
2. `scripts/write_snapshot_audit.py`
3. 当前 `SKILL.md`
