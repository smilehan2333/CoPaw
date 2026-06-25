---
name: before-stop-history-http-guard-demo
description: "Use this skill when you need a BeforeStop command hook example that reads the full saved conversation history and asks an external policy service whether to block or allow the final agent output."
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.0"
---

# BeforeStop History HTTP Guard Demo

这个样例演示 skill 级 `BeforeStop + command handler`。它和 prompt 版最终输出检查不同：
脚本会读取 `HookContext.transcript_path` 指向的完整会话保存文件，再把完整历史和
当前候选最终输出一起发给外部接口判定。

## 覆盖点

- 事件：`BeforeStop`
- handler 类型：`command`
- 目的：外部策略服务基于完整历史决定最终输出是 `allow` 还是 `block`

## 外部接口配置

脚本从环境变量读取接口地址：

```bash
export FINAL_OUTPUT_GUARD_URL="https://policy.example.com/hooks/final-output"
```

可选认证：

```bash
export FINAL_OUTPUT_GUARD_AUTH_TOKEN="..."
```

如果设置了 token，脚本会发送：

```text
Authorization: Bearer <token>
```

## 请求体

脚本会向外部接口 POST：

```json
{
  "hookContext": {
    "hook_event_name": "BeforeStop",
    "prompt": "...",
    "assistant_response": "...",
    "transcript_path": "..."
  },
  "transcript": {
    "memory": {
      "messages": []
    }
  }
}
```

`transcript` 是会话文件的完整 JSON 内容，不是摘要。

## 响应体

外部接口返回严格 JSON：

```json
{
  "decision": "block",
  "reason": "最终输出遗漏用户要求的验证结果"
}
```

支持的 `decision`：

- `allow`
- `block`

`BeforeStop` 不支持 `additionalContext`，所以阻断说明必须放在顶层 `reason`。

## 失败策略

- 读不到完整历史：保守返回 `block`
- 外部接口不可用、超时或响应格式错误：保守返回 `block`
- `hooks/hooks.json` 中 `failPolicy` 也设置为 `block`

## 目录内容

1. `hooks/hooks.json`
2. `scripts/before_stop_history_http_guard.py`
3. 当前 `SKILL.md`
