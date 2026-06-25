---
name: hook-http-demo
description: "Use this skill when the user wants a concrete example of Swe skill-owned hook files, especially a PostToolUse HTTP hook that reads tool_response from an MCP tool call and sends it to a local HTTP endpoint for auditing or summarization. Trigger when the task is to demonstrate or scaffold hooks/hooks.json, a local receiver script, or a minimal skill directory that shows how skill-level hook runtime configuration works. Do NOT use for general hook design discussions that do not require creating example files."
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.0"
  swe:
    uses_tools:
      - execute_shell_command
---

> **重要：** 这个 skill 是一个最小样例，重点演示 `hooks/hooks.json`、`PostToolUse`、`tool_response`、可选的 `conversation_snapshot`，以及本地 HTTP 接收脚本如何配合。

# Hook HTTP Demo

这个样例 skill 提供三部分文件：

1. `hooks/hooks.json`
2. `scripts/post_tool_use_http_receiver.py`
3. 当前 `SKILL.md`

## 适用场景

- 需要演示 skill 级 hook 的目录结构
- 需要一个 `PostToolUse` 的 HTTP hook 样例
- 需要查看工具执行成功后如何消费 `tool_response`

## 关键限制

- skill 级 HTTP hook 的 URL 默认允许，不需要额外配置租户白名单
- skill 级 HTTP hook 不允许写明文 `headers`
- 当前 hook 上下文可以拿到 `tool_name`、`tool_input`、`tool_use_id`、`tool_response`
- 只有在单个 handler 上显式打开 `includeConversationSnapshot` 时，才会收到 `conversation_snapshot` 和 `conversation_snapshot_meta`
- 当前 hook 上下文默认**不包含** `mcp_server`，所以通常只能按 `tool_name` 匹配

## 样例说明

`hooks/hooks.json` 当前匹配的是工具名 `execute_shell_command`，用于演示 shell 工具执行后的 `PostToolUse` 场景；如果你的工具名不同，直接修改 `matcher.tools` 即可。

本样例把成功执行后的工具结果发送到：

```text
http://127.0.0.1:9000/hooks/mcp-posttool
```

对应的本地接收脚本是：

```text
scripts/post_tool_use_http_receiver.py
```

如果你希望这个 HTTP handler 同时拿到最近对话快照，可以把 `hooks/hooks.json` 里的 handler 改成：

```json
{
  "id": "mcp-posttool-http-receiver",
  "type": "http",
  "url": "http://127.0.0.1:9000/hooks/mcp-posttool",
  "includeConversationSnapshot": true,
  "conversationSnapshotLimit": 20,
  "timeout": 5,
  "failPolicy": "allow"
}
```

这个开关是 handler 级的：

- 不会影响同一事件里的其他 handler
- 不会替代 `tool_response`
- 快照来自当前 Agent 内存，不是去读 `transcript_path`

## 启动脚本

在 skill 目录内运行：

```bash
python scripts/post_tool_use_http_receiver.py --host 127.0.0.1 --port 9000
```

脚本会启动一个本地 HTTP 服务，接收 hook runtime 发来的 `HookContext` JSON，并返回：

```json
{
  "hookSpecificOutput": {
    "additionalContext": [
      "......"
    ]
  }
}
```

这些 `additionalContext` 会写入后续记忆，适合做审计摘要、诊断补充或工具结果压缩。

## 典型请求体

打开 `includeConversationSnapshot` 后，这个接收器拿到的请求体通常会同时包含：

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "execute_shell_command",
  "tool_input": {
    "command": "echo hello"
  },
  "tool_use_id": "toolu_123",
  "tool_response": "hello",
  "conversation_snapshot": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "帮我执行一个 echo 命令"
        }
      ]
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "text",
          "text": "我先执行这个命令。"
        },
        {
          "type": "tool_use",
          "id": "toolu_123",
          "name": "execute_shell_command",
          "input": {
            "command": "echo hello"
          }
        }
      ]
    }
  ],
  "conversation_snapshot_meta": {
    "included_messages": 2,
    "omitted_messages": 0,
    "limit": 20,
    "reasoning_omitted": true,
    "media_content_omitted": false
  }
}
```

推荐读取顺序：

1. 先读 `tool_response`，拿到这一次工具调用的最终业务结果。
2. 再读 `tool_input`，补齐本次工具参数。
3. 最后按需读 `conversation_snapshot`，理解这次工具调用前后的上下文。
