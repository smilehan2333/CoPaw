# Tenant PreToolUse HTTP Policy Demo

这个样例演示租户级 `PreToolUse + http handler`，适合客户已经有统一策略中心，希望在工具执行前做远端审批、拒绝或放行。

## 覆盖点

- 配置层级：租户级
- 事件：`PreToolUse`
- handler 类型：`http`
- 目的：把工具名和工具输入发给远端策略服务，由策略服务返回 `allow` / `deny` / `ask`

## 文件

1. `config/config.json`
2. `scripts/pre_tool_policy_receiver.py`
3. 当前 `README.md`

## 安装位置

把 `config/config.json` 的内容合并到：

```text
~/.swe/<tenant_id>/config.json
```

租户级配置必须写成：

```json
{
  "hooks": {
    "enabled": true,
    "events": {}
  }
}
```

不要直接复制 Skill 级 `hooks/hooks.json` 的根结构。

## 启动本地策略服务

在 demo 目录下运行：

```bash
python scripts/pre_tool_policy_receiver.py --host 127.0.0.1 --port 9100
```

然后触发 `execute_shell_command` 工具调用。策略服务会演示：

- `rm -rf`：返回 `deny`
- `git push`：返回 `ask`
- `ls`：返回 `allow`，并通过 `updatedInput` 改成 `ls -la`
- 其他命令：返回 `allow`

## 迁移到客户环境时需要改什么

- 把 `matcher.tools` 改成客户实际工具名
- 把 `url` 改成客户策略服务地址
- 把 `headerSecretRefs.Authorization` 指向客户租户环境里的密钥名
- 按客户风险偏好决定 `failPolicy` 是 `allow` 还是 `block`
- 确认策略服务返回 `hookSpecificOutput.permissionDecision`，不要只返回顶层 `decision: "allow"`

## 典型策略响应

```json
{
  "hookSpecificOutput": {
    "permissionDecision": "ask",
    "permissionDecisionReason": "该命令会影响远端仓库，请先审批"
  }
}
```

`ask` 只在 `PreToolUse` 上会接入审批流程。用户同意后，原工具调用会再次经过 `PreToolUse`，所以生产策略服务通常需要记录已经审批过的操作，或在配置里使用 `once: true`。
