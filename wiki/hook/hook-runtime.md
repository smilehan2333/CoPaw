# Hook Runtime 使用说明

Hook Runtime 用于在 Agent 的关键运行节点挂接自定义策略。你可以把它理解成一套“事件触发器”：

- 在用户输入进入 Agent 之前做检查
- 在工具调用前后追加策略
- 在回复准备结束时做完成度门禁
- 在需要时阻断、改写、补充上下文，或请求人工审批

本文面向普通使用者和管理员，重点回答 4 个问题：

1. hook 什么时候触发
2. 应该把配置写在哪里
3. handler 能返回什么
4. 返回结果会对当前会话产生什么实际影响

本文不展开内部类设计和源码细节，但所有说明都已按当前项目实现核对。

## 先看结论

如果你只想快速上手，先记住下面几条：

- `PreToolUse` 是最常用的事件：可以拒绝工具、要求审批、改写工具输入。
- `BeforeStop` 是“完成门禁”：候选回复已经生成后才触发；返回 `block` 会让 Agent 在同一次请求里继续做事，而不是立刻结束。
- `PostToolUse` 和 `PostToolUseFailure` 不能撤销已经发生的工具调用，它们更适合补充审计或诊断信息；普通工具执行路径会触发它们，但既有 Tool Guard 的预批准执行分支当前会绕过后置 hook。
- Skill 自带 hook 只有在该 Skill 在当前会话里被激活后才会生效。
- 多个 handler 会并发执行，不要依赖“前一个 handler 的输出给后一个 handler 使用”。

## 适合解决什么问题

- 在每次请求开始前注入项目约束、组织规则或环境说明
- 在用户输入进入 Agent 前检查敏感内容
- 在执行 shell、文件、网络类工具前做额外策略判断
- 对高风险工具调用弹出人工审批
- 在工具执行成功或失败后补充审计和诊断信息
- 在回复结束前要求先完成测试、构建或 lint
- 在回合结束时记录收尾信息，供下一轮对话继续使用

## 新人推荐阅读顺序

如果你是第一次配置 hook，建议按下面顺序阅读和落配置：

1. 先看“事件与真实生效时机”，确定你要拦的是哪一个阶段。
2. 再看“配置写在哪里”和“最小配置”，先把文件位置和 JSON 外形搭起来。
3. 然后看“`command` / `http` / `prompt`”三类 handler，选一种最适合你的执行方式。
4. 最后再看 “HookContext 里有哪些字段” 和 “handler 能返回什么”，决定脚本里读哪些入参、返回哪些结果。

如果只想尽快做出第一个可验证的 hook，最稳妥的起点通常是：

- `PreToolUse + command`
- 或 `UserPromptSubmit + http`

因为这两类最容易观察是否命中，也最容易验证返回效果。

## 事件与真实生效时机

下表是最重要的部分。配置 hook 时，先确认你要拦的是哪个阶段。

| 事件 | 什么时候触发 | 用户通常会看到什么 | 适合做什么 |
| --- | --- | --- | --- |
| `SessionStart` | 每次请求进入 Agent 主流程前 | 通常无明显提示；如果被阻断，会直接返回阻断原因 | 注入本轮初始上下文、记录开始事件 |
| `UserPromptSubmit` | 当前请求含有文本用户输入时，在 Agent 处理前 | 通常无明显提示；如果被阻断，会直接返回阻断原因 | 检查输入、设置会话标题、补充本轮上下文 |
| `PreToolUse` | 工具真正执行前 | 可能直接放行、拒绝、改写输入，或弹出审批卡片 | 工具审批、参数检查、命令改写 |
| `PostToolUse` | 工具成功返回后 | 用户不会看到单独弹窗，但后续推理会收到补充上下文 | 审计记录、补充工具结果说明 |
| `PostToolUseFailure` | 工具调用抛出失败后 | 工具失败仍然会失败；hook 只能补充诊断信息 | 记录错误、提示排查方向 |
| `BeforeStop` | 候选回复已经流出后、正式结束前 | 用户通常已经看到了候选回复；若返回 `block`，系统会继续同一任务 | 完成门禁、测试门禁、发布前检查 |
| `Stop` | 系统允许结束后、当前轮真正结束前 | 如果被阻断，用户会再看到一条阻断说明，本轮结束 | 最终审计、写入收尾上下文 |

实际请求路径里还有一个顺序细节：如果当前请求带有文本用户输入，`UserPromptSubmit` 会在 preflight 阶段先执行；之后系统装配 Agent 主流程时才执行 `SessionStart`。所以上表按生命周期概念排序，不表示所有请求里严格按表格顺序触发。

工具后置事件也有一个例外：普通工具成功或失败后会分别触发 `PostToolUse` / `PostToolUseFailure`；但如果工具走的是既有 Tool Guard 的预批准执行分支，当前实现会直接执行并返回，不进入这两个后置 hook。

### 关于 `BeforeStop` 和 `Stop`

这两个事件最容易混淆。

- `BeforeStop` 是“现在能不能结束”。如果返回 `block`，系统会自动继续当前任务，而不是直接结束。
- `Stop` 是“已经准备结束了，最后再做一次收尾”。如果返回阻断，当前轮会结束，但不会自动续跑。

还有一个很重要的用户可见差异：

- `BeforeStop` 触发时，候选回复通常已经被用户看到了。
- `Stop` 触发时，候选回复通常也已经被用户看到了；若 hook 阻断，系统会追加一条说明，而不是把前面的回复“撤回”。

## 配置写在哪里

Hook 可以配置在 3 个层级：

1. 租户级
2. Agent 级
3. Skill 级

普通场景优先用租户级。只有确实要针对某个 workspace 或某个 Skill 单独控制时，再使用后两者。

### 租户级

配置文件：

```text
~/.swe/<tenant_id>/config.json
```

例如：

```text
~/.swe/default/config.json
```

租户级 hook 写在根节点的 `hooks` 字段下。

### Agent 级

配置文件：

```text
~/.swe/<tenant_id>/workspaces/<workspace_id>/agent.json
```

Agent 级 hook 同样写在根节点的 `hooks` 字段下。

### Skill 级

配置文件：

```text
~/.swe/<tenant_id>/workspaces/<workspace_id>/skills/<skill_name>/hooks/hooks.json
```

Skill 级配置和前两者不同：

- 文件根对象直接就是 hook 配置
- 不需要再包一层 `hooks`
- 只有当这个 Skill 在当前会话里被激活后，里面的 hook 才会生效

## 最小配置

租户级或 Agent 级配置示例：

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "PreToolUse": [
        {
          "id": "shell-policy",
          "matcher": {
            "tools": ["execute_shell_command"]
          },
          "hooks": [
            {
              "id": "check-shell",
              "type": "command",
              "argv": ["python", "hooks/check_shell.py"],
              "timeout": 5,
              "failPolicy": "block"
            }
          ]
        }
      ]
    }
  }
}
```

Skill 级 `hooks/hooks.json` 示例：

```json
{
  "enabled": true,
  "events": {
    "PreToolUse": [
      {
        "id": "shell-policy",
        "matcher": {
          "tools": ["execute_shell_command"]
        },
        "hooks": [
          {
            "id": "check-shell",
            "type": "command",
            "argv": ["python", "scripts/check_shell.py"],
            "timeout": 5,
            "failPolicy": "block"
          }
        ]
      }
    ]
  }
}
```

## 配置结构

### 根字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `enabled` | 否 | 是否启用当前 hook 配置。默认 `false`。 |
| `events` | 否 | 事件配置，key 是事件名，value 是该事件下的匹配分组列表。省略时等同于没有可执行 hook。 |

### 分组字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `events.<event>[].id` | 否 | 分组 ID。建议填写，便于排查和去重。 |
| `events.<event>[].matcher` | 否 | 匹配条件。当前最常用的是 `matcher.tools`。 |
| `events.<event>[].hooks` | 否 | 该分组下的 handler 列表。省略或为空时该分组不会执行任何 handler。 |

### `matcher.tools`

`matcher.tools` 用于限制该分组只对指定工具名生效，按工具名精确匹配：

```json
{
  "matcher": {
    "tools": ["execute_shell_command", "read_file"]
  }
}
```

如果不写 `matcher`，或 `matcher.tools` 为空，则表示该事件下全部请求都可能命中该分组。

## Handler 通用字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | handler ID。应在同一配置来源内保持唯一且稳定；普通租户级 / Agent 级配置当前不会强制校验全局唯一，重复 ID 会让 `once`、覆盖和排查变得含糊。 |
| `type` | 是 | handler 类型，支持 `command`、`http`、`prompt`。 |
| `if` | 否 | 条件表达式；结果为假时跳过该 handler。 |
| `timeout` | 否 | 单个 handler 超时时间，单位秒，默认 `10`。 |
| `statusMessage` | 否 | 阻断或审批时显示给用户的提示文案。 |
| `once` | 否 | `true` 表示同一实际生效租户、同一用户、同一会话、同一事件、同一 handler ID 只执行一次。 |
| `includeConversationSnapshot` | 否 | `true` 时，仅该 handler 会额外收到 `conversation_snapshot` 和 `conversation_snapshot_meta`。默认 `false`。 |
| `conversationSnapshotLimit` | 否 | 快照最多携带多少条最近消息。默认 `50`，最大 `200`；仅在 `includeConversationSnapshot: true` 时生效。 |
| `failPolicy` | 否 | handler 自身执行失败时的处理策略，支持 `allow` 或 `block`。`command` / `http` 默认 `allow`，`prompt` 默认 `block`。 |

### `once: true` 的实际含义

`once: true` 不是“同一条命令只执行一次”，而是：

- 同一个实际生效租户
- 同一个用户
- 同一个会话
- 同一个事件
- 同一个 handler ID

只运行一次。跨轮次也会记住，直到该会话结束或会话状态被清空。

### `includeConversationSnapshot` 的实际语义

这是新增的 handler 级开关，不是全局开关。

- 只有显式写了 `includeConversationSnapshot: true` 的 handler，才会收到快照字段。
- 快照优先来自当前 Agent 的内存消息；runner 早期事件还没有可用 Agent 时，会尝试读取 session state 中保存的 memory。它不是去读 `transcript_path` 回放完整持久化记录。
- `conversationSnapshotLimit` 是“每个 handler 自己的截断上限”，所以不同 handler 可以拿到不同长度的快照。
- 当前事件本身仍然通过 `prompt`、`tool_input`、`tool_response`、`assistant_response`、`error` 等字段单独传入；快照不会重复制造一份“当前事件副本”。

配置示例：

```json
{
  "id": "post-tool-audit",
  "type": "http",
  "url": "http://127.0.0.1:9000/hooks/mcp-posttool",
  "includeConversationSnapshot": true,
  "conversationSnapshotLimit": 20,
  "timeout": 5,
  "failPolicy": "allow"
}
```

如果运行时当前拿不到 Agent 内存，handler 仍会继续执行，但会收到：

```json
{
  "conversation_snapshot": [],
  "conversation_snapshot_meta": {
    "included_messages": 0,
    "omitted_messages": 0,
    "limit": 50,
    "unavailable": true,
    "unavailable_reason": "agent_memory_unavailable"
  }
}
```

### `if` 表达式怎么写

`if` 适合做轻量过滤。当前实现支持的语法很简单，建议只用：

- `==`
- `!=`
- `in`
- `not in`
- `and`
- `or`
- `not`
- 字段取值，例如 `tool_name`
- 字典取值，例如 `tool_input["command"]`

示例：

```json
{
  "if": "tool_name == 'execute_shell_command' and 'rm -rf' in tool_input['command']"
}
```

注意：

- `if` 表达式写错时，handler 不会报出漂亮的配置提示，通常表现为“这个 handler 没有命中”。
- 因此建议先从最简单的条件开始验证。

## 三类 Handler

当前支持 3 类 handler：`command`、`http`、`prompt`。

### 1. `command` handler

`command` handler 会在当前 workspace 内执行本地命令。

- hook 上下文通过标准输入传入，格式为 JSON
- handler 的标准输出如果非空，必须是合法 JSON 对象
- 标准错误适合写调试日志和错误信息

配置示例：

```json
{
  "id": "check-shell",
  "type": "command",
  "argv": ["python", "hooks/check_shell.py"],
  "timeout": 5,
  "failPolicy": "block"
}
```

可用字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `argv` | 二选一 | 参数数组形式。推荐写法，尤其适合调用脚本。 |
| `command` | 二选一 | shell 命令字符串。普通租户级 / Agent 级 hook 可用；Skill 级 hook 禁用。 |
| `shell` | 否 | 使用 `command` 字符串时可指定 shell，支持 `sh`、`bash`、`zsh`、`cmd`、`powershell`。 |
| `cwd` | 否 | handler 执行目录。普通 hook 必须在当前 workspace 内；Skill hook 必须在 Skill 目录和 workspace 内。 |
| `env` | 否 | 追加给子进程的字面量环境变量。Skill 级 hook 禁用。 |

模型层里还会拒绝 `async` 和 `asyncRewake`，当前 command hook 不支持异步后台执行。

#### 建议做法

- 普通租户级 / Agent 级 hook：脚本放在当前 workspace 内，例如 `hooks/check_shell.py`
- Skill 级 hook：脚本放在 Skill 自己的 `scripts/` 目录内
- stdout 只输出最终 JSON；日志一律写 stderr

#### 退出码语义

| 退出码 | 含义 |
| --- | --- |
| `0` | 执行成功；stdout 可为空，或返回 JSON 对象 |
| `2` | 直接阻断当前事件 |
| 其他非零 | 视为 handler 失败，是否阻断由 `failPolicy` 决定 |

#### 路径限制

普通 `command` handler 受 workspace 边界约束：

- `cwd` 必须在当前 workspace 内
- `argv` 里出现的绝对路径，不能越出当前 workspace
- 如果使用 `command` 字符串，里面涉及的文件路径也会按 workspace 做边界校验

这意味着：

- 你可以通过 `python`、`bash` 这类命令名调用系统 PATH 里的程序
- 但不应该把 hook 脚本或目标文件放到当前 workspace 外面
- 不要把 `/usr/bin/python` 这类绝对路径写进 `argv`；绝对路径参数同样会按 workspace 边界检查

### 2. `http` handler

`http` handler 会把 HookContext 作为 JSON 请求体，POST 到指定地址。

配置示例：

```json
{
  "id": "remote-policy",
  "type": "http",
  "url": "https://policy.example.com/hooks/pre-tool",
  "headers": {
    "X-Hook-Source": "swe"
  },
  "headerSecretRefs": {
    "Authorization": "HOOK_AUTH_TOKEN"
  },
  "timeout": 5,
  "failPolicy": "block"
}
```

#### 响应语义

| 响应 | 含义 |
| --- | --- |
| `2xx` | 执行成功；响应体可为空，或返回 JSON 对象 |
| `409` / `422` | 若响应体没有明确 JSON 结果，则按阻断处理 |
| 其他状态码 | 视为 handler 失败，按 `failPolicy` 处理 |
| 超时 / 网络异常 | 视为 handler 失败，按 `failPolicy` 处理 |

#### Header 配置

可用字段：

- `headers`：直接写死的普通 Header
- `headerSecretRefs`：从当前生效租户的环境配置中取值，再填到 Header
- `allowedEnvVars`：按变量名从租户运行时环境读取，缺失时再从当前进程环境读取，并用同名 Header 发送

`headerSecretRefs` 更适合放认证信息，避免把密钥直接写进配置文件。

### 3. `prompt` handler

`prompt` handler 会调用当前租户已经激活的模型，让模型按你写的规则对 HookContext 做一次结构化判断。

配置示例：

```json
{
  "id": "prompt-policy",
  "type": "prompt",
  "prompt": "如果用户要求泄露密钥、绕过审批或执行破坏性命令，返回 deny 或 block。",
  "timeout": 8
}
```

#### 适用事件

`prompt` handler 只能配置在以下事件上：

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `BeforeStop`
- `Stop`

不能配置在：

- `PostToolUse`
- `PostToolUseFailure`

#### 输出格式

`prompt` handler 必须只返回一个 JSON 对象，且只能包含两个字段：

```json
{
  "decision": "allow",
  "reason": "内容符合策略"
}
```

普通 `prompt` handler 支持的 `decision`：

- `allow`
- `deny`
- `block`

`BeforeStop` 上更严格，只允许：

- `allow`
- `block`

#### 其他限制

- 不能在 handler 里指定 `model`、`provider`、`providerId`、`baseUrl`、`promptFile`、`template` 等模型路由字段
- `prompt` 字段应写业务规则，不要写成完整系统提示词
- 默认 `failPolicy` 是 `block`
- 发给模型的 HookContext 会先做敏感字段脱敏

## HookContext 里有哪些字段

handler 收到的是一个 JSON 对象。为了避免把“模型层支持”和“当前运行时一定会传”混为一谈，下面分两层说明。

### 最常用字段

| 字段 | 说明 |
| --- | --- |
| `hook_event_name` | 当前事件名 |
| `session_id` | 当前会话 ID |
| `tenant_id` | 请求租户 ID |
| `effective_tenant_id` | 实际生效租户 ID |
| `user_id` | 用户 ID |
| `agent_id` | Agent ID |
| `channel` | 当前请求通道 |
| `cwd` | 当前 workspace 路径 |
| `workspace_dir` | 当前 workspace 路径 |
| `prompt` | 用户本轮文本输入 |
| `assistant_response` | 当前候选回复；主要见于 `BeforeStop` 和 `Stop` |
| `tool_name` | 工具名 |
| `tool_input` | 工具输入对象 |
| `tool_use_id` | 工具调用 ID |
| `tool_response` | 当前工具调用的成功业务输出；主要见于 `PostToolUse` |
| `error` | 工具失败信息；主要见于 `PostToolUseFailure` |
| `conversation_snapshot` | 最近对话快照；仅在 handler 打开 `includeConversationSnapshot` 时出现 |
| `conversation_snapshot_meta` | 快照的截断/脱敏/不可用说明；仅在 handler 打开 `includeConversationSnapshot` 时出现 |

### 当前实现支持的完整字段

下表按当前 `HookContext` 模型和实际构造逻辑整理。

| 字段 | 当前运行时是否会注入 | 主要出现位置 / 说明 |
| --- | --- | --- |
| `session_id` | 是 | runner 事件、tool 事件都会传 |
| `transcript_path` | 是 | runner 事件、tool 事件都会传 |
| `cwd` | 是 | 当前 workspace 根路径 |
| `hook_event_name` | 是 | 全部事件都会传 |
| `tenant_id` | 是 | 全部事件都会传 |
| `effective_tenant_id` | 是 | 全部事件都会传 |
| `user_id` | 是 | 全部事件都会传 |
| `agent_id` | 是 | 全部事件都会传 |
| `channel` | 是 | 全部事件都会传 |
| `permission_mode` | 否 | 当前模型层支持，但当前 hook 构造逻辑未注入 |
| `effort` | 否 | 当前模型层支持，但当前 hook 构造逻辑未注入 |
| `agent_type` | 否 | 当前模型层支持，但当前 hook 构造逻辑未注入 |
| `source_id` | 部分 | runner 侧事件会传；正常请求路径下 tool 侧事件也会从请求上下文传入；缺失 request context 时可能为空 |
| `workspace_dir` | 是 | 全部事件都会传，通常与 `cwd` 相同 |
| `chat_id` | 部分 | 请求上下文里有 chat 时会传 |
| `turn_id` | 部分 | 请求上下文里有 turn 时会传 |
| `source` | 部分 | `SessionStart` 这类 runner 事件会传；当前主流程常见值是 `startup` / `resume` |
| `model` | 部分 | 当前主流程只在 `SessionStart` 传当前激活模型标签 |
| `prompt` | 部分 | `UserPromptSubmit`、`BeforeStop`、`Stop` 常见；tool 事件当前不传 |
| `tool_name` | 部分 | `PreToolUse` / `PostToolUse` / `PostToolUseFailure` 传 |
| `tool_input` | 部分 | `PreToolUse` / `PostToolUse` / `PostToolUseFailure` 传 |
| `tool_use_id` | 部分 | `PreToolUse` / `PostToolUse` / `PostToolUseFailure` 传 |
| `tool_response` | 部分 | 主要见于 `PostToolUse`，值为当前工具调用最终 `tool_result.output`；无法提取时省略 |
| `assistant_response` | 部分 | 主要见于 `BeforeStop` 和 `Stop` |
| `error` | 部分 | 主要见于 `PostToolUseFailure` |
| `conversation_snapshot` | 部分 | 仅对声明了 `includeConversationSnapshot: true` 的 handler 注入；值是当前 Agent 内存或 session state memory 里的最近若干条规范化消息 |
| `conversation_snapshot_meta` | 部分 | 与 `conversation_snapshot` 配套；包含 `included_messages`、`omitted_messages`、`limit` 以及可选的 `reasoning_omitted` / `media_content_omitted` / `unavailable` 信息 |

这张表的关键结论是：

- 如果你写的是 runner 侧 hook，例如 `SessionStart`、`UserPromptSubmit`、`BeforeStop`、`Stop`，重点看 `prompt`、`assistant_response`、`source`、`model`。
- 如果你写的是 tool 侧 hook，例如 `PreToolUse`、`PostToolUse`、`PostToolUseFailure`，重点看 `tool_name`、`tool_input`、`tool_use_id`、`tool_response`、`error`。其中 `tool_response` 是当前工具调用的业务输出，不是完整 `tool_result` 块，也不需要通过 `includeConversationSnapshot` 获取。
- 如果你要把“当前事件字段”与“最近对话上下文”一起送给外部策略，就同时使用事件字段和 `conversation_snapshot`，不要试图只从快照里反推当前事件。
- `permission_mode`、`effort`、`agent_type` 虽然在模型里有字段，但当前实现还没有把它们接进真实 hook payload，不要把它们当成当前可依赖入参。

### 两类典型 payload 样子

#### 1. `SessionStart` 常见 payload

```json
{
  "session_id": "session-1",
  "transcript_path": "/path/to/session-1.json",
  "cwd": "/workspace/project",
  "hook_event_name": "SessionStart",
  "tenant_id": "default",
  "effective_tenant_id": "default",
  "user_id": "user-1",
  "agent_id": "demo-agent",
  "channel": "console",
  "source_id": "console",
  "workspace_dir": "/workspace/project",
  "chat_id": "chat-1",
  "turn_id": "turn-1",
  "source": "startup",
  "model": "openai/gpt-5.4"
}
```

#### 2. `PostToolUse` 常见 payload

```json
{
  "session_id": "session-1",
  "transcript_path": "/path/to/session-1.json",
  "cwd": "/workspace/project",
  "hook_event_name": "PostToolUse",
  "tenant_id": "default",
  "effective_tenant_id": "default",
  "user_id": "user-1",
  "agent_id": "demo-agent",
  "channel": "console",
  "workspace_dir": "/workspace/project",
  "chat_id": "chat-1",
  "turn_id": "turn-1",
  "tool_name": "execute_shell_command",
  "tool_input": {
    "command": "echo hello"
  },
  "tool_use_id": "toolu_123",
  "tool_response": "hello"
}
```

`PostToolUse.tool_response` 表示当前工具调用的最终业务输出。运行时会从同一 `tool_use_id` 对应的终态 `tool_result.output` 提取该值；它不包含 live/intermediate chunks，不包含完整 `tool_result` 的 `type` / `id` / `name` 包装，也不复用 `Hook Conversation Snapshot`。如果运行时无法找到对应终态输出，会省略 `tool_response` 字段，但仍继续发送 `PostToolUse`。

#### 3. `PostToolUse` 同时带 `tool_response` 和会话快照

如果某个 handler 打开了 `includeConversationSnapshot`，它拿到的 payload 典型会像这样：

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
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "tool_result",
          "id": "toolu_123",
          "name": "execute_shell_command",
          "output": "hello"
        }
      ]
    }
  ],
  "conversation_snapshot_meta": {
    "included_messages": 3,
    "omitted_messages": 0,
    "limit": 20,
    "reasoning_omitted": true,
    "media_content_omitted": false
  }
}
```

这里要区分两层语义：

- `tool_response` 是“这一次工具调用最终产出的业务结果”，方便直接做审计、摘要或规则判断。
- `conversation_snapshot` 是“最近对话上下文的裁剪视图”，方便策略服务理解这次工具调用前后的语境。

不要把两者混用。最稳妥的做法是：规则判断优先读 `tool_response`，需要补上下文时再读快照。

例如 `execute_shell_command` 的工具输入字段是：

```json
{
  "tool_name": "execute_shell_command",
  "tool_input": {
    "command": "echo hello"
  }
}
```

不是 `cmd`。

## handler 能返回什么

这一节最容易误用。不同事件、不同 handler 类型，可用返回值并不完全相同。

### 1. 请求用户审批：`permissionDecision: "ask"`

典型用法：

```json
{
  "hookSpecificOutput": {
    "permissionDecision": "ask",
    "permissionDecisionReason": "该命令会修改文件，请确认"
  }
}
```

实际效果：

- 只有在 `PreToolUse` 上，当前系统才会把 `ask` 接到现有审批流程里
- 用户同意后，原工具调用会再次经过一次 `PreToolUse`
- 如果条件没变、又再次返回 `ask`，就会再次弹审批

建议：

- 需要审批的策略尽量配合 `once: true`
- 或者在外部策略服务里记录“该操作已经审批过”

还要注意一点：

- hook 返回 `allow` 并不会绕过系统原有的 Tool Guard
- 如果 Tool Guard 自己也要求审批，审批仍然会发生

### 2. 允许 / 拒绝工具执行

对于 `command` 和 `http` handler，真正用于工具许可控制的推荐写法是：

```json
{
  "hookSpecificOutput": {
    "permissionDecision": "allow",
    "permissionDecisionReason": "符合策略"
  }
}
```

或：

```json
{
  "hookSpecificOutput": {
    "permissionDecision": "deny",
    "permissionDecisionReason": "命令涉及危险路径"
  }
}
```

说明：

- `allow` / `deny` / `ask` 属于“权限型结果”
- 最适合放在 `PreToolUse`
- `deny` 会阻止当前工具执行
- 对普通 `command` / `http` handler，不建议把顶层 `decision: "allow"` 当作“放行工具”的写法；应优先使用 `permissionDecision`

### 3. 阻断当前事件：`decision: "block"`

配置示例：

```json
{
  "decision": "block",
  "reason": "blocked by tenant policy"
}
```

但要注意，不同事件上的实际效果不同：

- `SessionStart` / `UserPromptSubmit`
  会直接阻断本次请求，Agent 不再继续。
- `PreToolUse`
  会阻断当前工具执行。
- `PostToolUse`
  不会撤销已经执行完的工具；它更像是“补一条阻断说明给后续推理看”。
- `PostToolUseFailure`
  不会吞掉原始工具失败；原错误仍然会继续向上抛出。
- `BeforeStop`
  表示“现在还不能结束，请继续当前任务”。
- `Stop`
  会在当前轮末尾追加一条阻断说明，然后结束本轮，不会自动续跑。

### 4. 停止当前流程：`continue: false`

配置示例：

```json
{
  "continue": false,
  "stopReason": "stop requested by hook"
}
```

这个返回值适合明确要求“当前流程就到这里”。它与 `block` 的区别在于：

- `block` 更偏向“此处不允许继续，需要转到别的处理”
- `continue: false` 更偏向“直接停止当前流程”

注意：

- `SessionStart` / `UserPromptSubmit` / `PreToolUse` / `Stop` 上更有实际意义
- `PostToolUse` / `PostToolUseFailure` 上同样不能回滚已发生的工具结果，更多仍是写入说明
- `BeforeStop` 不支持这个字段
- 在 `BeforeStop` 上只能用 `allow` 或 `block`

### 5. 补充上下文：`additionalContext`

配置示例：

```json
{
  "hookSpecificOutput": {
    "additionalContext": "策略系统确认：该目录属于当前项目根目录"
  }
}
```

它的生效方式取决于事件：

- `SessionStart` / `UserPromptSubmit`
  会被追加到本轮 Agent 的初始上下文中
- `PostToolUse` / `PostToolUseFailure` / `Stop`
  会作为系统说明写入内存，供后续推理或下一轮继续使用
- `BeforeStop`
  不支持 `additionalContext`

实务上最常见的用法：

- 在 `UserPromptSubmit` 注入组织规则
- 在 `PostToolUse` 写入审计说明或结果摘要
- 在 `PostToolUseFailure` 写入排查提示

### 6. 改写工具输入：`updatedInput`

只有 `PreToolUse` 适合使用 `updatedInput`。

示例：

```json
{
  "hookSpecificOutput": {
    "permissionDecision": "allow",
    "updatedInput": {
      "command": "echo replaced-by-hook"
    }
  }
}
```

注意：

- `updatedInput` 会替换整个工具输入对象，不是局部 merge
- 同一个事件中只允许一个 handler 返回 `updatedInput`
- 如果多个 handler 同时返回 `updatedInput`，系统会直接阻断，避免结果不确定

### 7. 设置会话标题：`sessionTitle`

典型用法：

```json
{
  "hookSpecificOutput": {
    "sessionTitle": "Hook Demo Session"
  }
}
```

当前实际生效点是 `UserPromptSubmit`。

如果多个 handler 都返回了标题，系统只取第一个非空标题。

### 8. `systemMessage` 和 `suppressOutput`

这两个字段当前模型层会解析、结果合并层也会保留：

```json
{
  "systemMessage": "internal note",
  "suppressOutput": true
}
```

但要特别注意：

- 当前运行时还没有把它们接到用户可见流程里
- 也就是说，写了不代表当前前端或 Agent 主流程就会出现稳定可见效果

因此，在当前版本里应把它们视为“内部保留字段”，不要把业务能力建立在它们上面。

## 多个 hook 同时命中时，系统怎么处理

### 执行顺序

系统会先解析出命中的 handler，再统一并发执行。

配置来源顺序是：

1. 租户级
2. Agent 级
3. 当前会话里已加载的 Skill 级

但“执行”是并发的，“结果合并”按配置顺序。

这带来两个实际建议：

- 不要依赖 handler 之间的先后副作用
- 如果两个 handler 可能返回冲突结果，必须提前设计好职责边界

### 决策优先级

多个结果合并时，优先级大致如下：

```text
continue:false > block/deny > ask > allow > none
```

另外还有几条固定规则：

- `additionalContext` 按配置顺序收集
- `sessionTitle` 取第一个非空值
- `updatedInput` 只允许一个来源
- handler 自己执行失败时，按各自的 `failPolicy` 决定是否阻断

## Skill hook 的特殊规则

Skill hook 比普通租户级 / Agent 级 hook 更严格。

### 什么时候才会生效

Skill hook 不是一开始就全量加载，而是：

- 当前会话里某个 Skill 被激活后
- 该 Skill 自己的 `hooks/hooks.json` 才会被加载进本会话

加载后，它会继续在本会话里生效。

这意味着：

- 如果某次工具调用本身触发了一个 Skill 激活
- 那么这个 Skill 的后续事件，甚至同一工具调用的 `PostToolUse`，就可能已经命中 Skill hook

### Skill `command` handler 的额外限制

Skill 自带 `command` handler 必须满足：

- 必须使用 `argv`
- 不能使用 `command` 字符串
- 必须且只能有一个脚本路径参数
- 该脚本必须位于 Skill 自己的 `scripts/` 目录下
- 不能写字面量 `env`

也就是说，Skill 级 hook 更适合做“随 Skill 一起分发的小脚本策略”，而不是任意命令执行。

### Skill `http` handler 的额外限制

Skill 自带 `http` handler：

- 不允许写字面量 `headers`
- 不允许写 `allowedEnvVars`
- 可以使用 `headerSecretRefs`

当前实现里，Skill 自带 HTTP hook 默认允许加载；旧版文档里提到的“先配置 URL 白名单再允许 Skill HTTP hook”已经不是当前默认行为。

当前配置模型和 runner 里仍保留 `security.skill_hook_http.approved_urls` 读取逻辑，但默认加载路径不会把这个列表当作强制 allowlist 使用；只有内部调用者显式传入 callable 校验器时，loader 才会按校验器拒绝未批准 URL。

这也是当前实现里最需要谨慎处理的边界：

- HTTP handler 收到的是完整 HookContext 请求体，当前不会像 `prompt` handler 一样先做敏感字段脱敏。
- 如果 Skill 来源不可完全信任，Skill 自带 HTTP hook 可以把用户输入、工具输入、工具输出、候选回复和租户 / workspace 元数据发送到远端。
- `headerSecretRefs` 会从当前生效租户读取密钥并写入请求 Header，等同于允许该 hook 使用对应凭据访问远端服务。

修复或加固建议：

- 生产环境优先恢复 URL 白名单校验，至少对 Skill 自带 HTTP hook 执行域名 allowlist。
- 对 HTTP handler 的请求体增加与 `prompt` handler 一致的敏感字段脱敏，或提供显式 `redactPayload: true` / `sendFields` 白名单。
- 对 Skill `headerSecretRefs` 增加可引用密钥白名单，避免任意 Skill 读取租户级敏感 Header。
- 对外发 HTTP hook 增加审计日志，记录 handler ID、目标 URL、事件名和脱敏后的字段摘要。

## `BeforeStop` 完成门禁

如果你只准备做一个高级 hook，通常就是它。

### 它解决什么问题

典型用途：

- 代码修改后，要求先跑目标测试
- 发布前，要求先完成 build 或 lint
- 文档生成类任务，要求先自检输出是否齐全

### 它和普通阻断最大的区别

`BeforeStop` 返回 `block` 时，不是简单地“报错结束”，而是：

1. 给当前任务生成一条内部续跑指令
2. 让 Agent 在同一次请求里继续做事
3. 再次生成候选回复后，再次进入 `BeforeStop`

如果持续返回 `block`，系统会用预算保护当前请求，避免无限循环。

### 预算配置

预算配置属于 Agent 运行配置，通常写在当前 workspace 的 `agent.json` 里。

配置位置：

```json
{
  "running": {
    "hook_runtime": {
      "max_before_stop_turns": 2,
      "max_automatic_follow_up_turns": 4
    }
  }
}
```

含义：

- `max_before_stop_turns`
  `BeforeStop` 触发自动续跑的最大次数
- `max_automatic_follow_up_turns`
  自动续跑总预算；如果系统里还有别的自动续跑机制，会共享这个总预算

兼容字段仍然可读：

- `running.max_before_stop_turns`
- `running.max_automatic_follow_up_turns`

但如果同时配置了 `running.hook_runtime`，后者优先。

### 预算耗尽时会发生什么

系统不会无限循环。

预算耗尽后，会向用户明确输出一条“任务未完成”的消息，并带上最新阻断原因。

## 常见配置示例

下面的示例按运行生命周期排序。新人如果想建立完整心智模型，直接从上往下读最顺手。

### 示例 1：会话开始时注入启动约束

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "SessionStart": [
        {
          "id": "session-start-bootstrap",
          "hooks": [
            {
              "id": "bootstrap-context",
              "type": "http",
              "url": "https://policy.example.com/hooks/session-start",
              "timeout": 5,
              "failPolicy": "allow"
            }
          ]
        }
      ]
    }
  }
}
```

适合做：

- 注入本轮组织约束
- 追加 workspace 说明
- 对启动来源做额外审计

### 示例 2：用户输入进入前注入项目约束

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "UserPromptSubmit": [
        {
          "id": "prompt-context",
          "hooks": [
            {
              "id": "append-project-rules",
              "type": "http",
              "url": "https://policy.example.com/hooks/prompt",
              "timeout": 5,
              "failPolicy": "allow"
            }
          ]
        }
      ]
    }
  }
}
```

适合做：

- 补充组织规则
- 自动命名会话
- 对用户输入做预检查

### 示例 3：工具执行前检查 Shell 命令

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "PreToolUse": [
        {
          "id": "shell-policy",
          "matcher": {
            "tools": ["execute_shell_command"]
          },
          "hooks": [
            {
              "id": "check-shell",
              "type": "command",
              "argv": ["python", "hooks/check_shell.py"],
              "timeout": 5,
              "statusMessage": "正在检查命令策略",
              "failPolicy": "block"
            }
          ]
        }
      ]
    }
  }
}
```

适合做：

- 危险命令拦截
- 人工审批
- 参数标准化

### 示例 4：工具成功后写入审计摘要

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "PostToolUse": [
        {
          "id": "tool-audit-summary",
          "matcher": {
            "tools": ["execute_shell_command"]
          },
          "hooks": [
            {
              "id": "collect-success-summary",
              "type": "http",
              "url": "https://policy.example.com/hooks/post-tool",
              "timeout": 5,
              "failPolicy": "allow"
            }
          ]
        }
      ]
    }
  }
}
```

适合做：

- 记录工具执行结果摘要
- 把长输出压缩成后续推理可读的补充上下文
- 追加成功后的审计说明

### 示例 5：工具失败后补充诊断信息

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "PostToolUseFailure": [
        {
          "id": "failure-diagnostics",
          "hooks": [
            {
              "id": "collect-diagnostics",
              "type": "command",
              "argv": ["python", "hooks/collect_diagnostics.py"],
              "timeout": 10,
              "failPolicy": "allow"
            }
          ]
        }
      ]
    }
  }
}
```

这类 hook 的重点不是“挽回失败”，而是让后续推理更容易知道：

- 日志在哪
- 常见原因是什么
- 下一步该查什么

### 示例 6：停止前要求先完成测试

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "BeforeStop": [
        {
          "id": "completion-gate",
          "hooks": [
            {
              "id": "task-completion-check",
              "type": "prompt",
              "prompt": "如果候选回复没有说明已完成必要测试，返回 block，并明确指出还缺什么；如果检查已完成，返回 allow。",
              "timeout": 8,
              "failPolicy": "block"
            }
          ]
        }
      ]
    }
  }
}
```

### 示例 7：真正结束前追加收尾信息

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "Stop": [
        {
          "id": "final-stop-summary",
          "hooks": [
            {
              "id": "append-final-summary",
              "type": "command",
              "argv": ["python", "hooks/final_stop_summary.py"],
              "timeout": 5,
              "failPolicy": "allow"
            }
          ]
        }
      ]
    }
  }
}
```

适合做：

- 当前轮真正结束前写入收尾上下文
- 记录最终审计说明
- 在需要时用 `continue: false` 明确停止当前轮

## 验证方式

建议不要一上来就配很复杂的策略，而是按下面顺序逐步验证。

### 验证 1：确认 hook 已命中

先用一个最简单的 handler，返回固定 `additionalContext` 或固定 `block`，确认：

- 事件名写对了
- 文件路径写对了
- `enabled` 已打开

### 验证 2：确认工具名和字段名

如果你在 `PreToolUse` 上做策略，务必确认两件事：

- `matcher.tools` 里的工具名是否真实存在
- `tool_input` 里用的字段名是否和真实工具一致

例如 `execute_shell_command` 要看的是：

```json
{
  "command": "echo hello"
}
```

### 验证 3：确认审批是否会重复

如果使用 `ask`，要额外验证：

- 用户批准后是否会再次弹审批
- 改写输入后是否会重新触发审批

这一步通常可以尽早发现是否需要补 `once: true`。

## 常见问题

### 配置后完全没有生效

按顺序检查：

1. 配置是否写在实际使用的租户或 workspace 下
2. `enabled` 是否为 `true`
3. 事件名是否正确
4. `matcher.tools` 是否与真实工具名完全一致
5. `if` 表达式是否写错
6. `command` / `argv` 路径是否越出当前 workspace
7. 如果是 Skill hook，该 Skill 是否真的已经在当前会话里被激活

### `ask` 没弹审批

先看你是不是配在了 `PreToolUse` 上。

当前审批 UI 只对 `PreToolUse` 的 `permissionDecision: "ask"` 做接线。其他事件即使返回 `ask`，也不会走同样的人工审批流程。

### 批准后又重复审批

这是 `PreToolUse` 的常见现象。原因通常有两个：

1. handler 每次都会再次返回 `ask`
2. 批准后工具输入发生了变化，系统把它视为新的待审操作

处理建议：

- 优先加 `once: true`
- 或在外部策略里记录已审批状态

### `PostToolUse` 返回了 `block`，为什么工具还是执行了

这是当前设计使然。

`PostToolUse` 发生在工具成功返回之后，所以它不能回滚已经执行完的操作。它更适合：

- 补充审计信息
- 追加结果摘要
- 告诉后续推理“这一步虽然执行了，但有风险”

注意：普通工具成功路径会触发 `PostToolUse`；既有 Tool Guard 的预批准执行分支当前会绕过这个后置 hook，所以不要把它当作所有工具成功路径的强制审计点。

### `PostToolUseFailure` 返回了 `block`，为什么原错误还在

因为这个事件的职责是“补充失败诊断”，不是“吞掉原失败”。

当前实现里，工具失败后：

1. `PostToolUseFailure` 会运行
2. hook 可以写入诊断信息
3. 原始工具失败仍然会继续向上抛出

注意：这描述的是普通工具失败路径；既有 Tool Guard 的预批准执行分支当前不在后置 hook 的 `try` / `except` 包裹内，失败时也不会触发 `PostToolUseFailure`。

### command hook 报路径越界

普通 hook 请确保脚本和工作目录都在当前 workspace 内。

推荐写法：

```json
{
  "argv": ["python", "hooks/check_shell.py"]
}
```

Skill hook 则应改为放在 Skill 自己的 `scripts/` 目录里。

### handler 输出 JSON 解析失败

当 handler 以成功状态返回时：

- stdout 为空可以
- stdout 非空时必须是合法 JSON 对象

因此：

- 日志写 stderr
- 最终结果只写一份 JSON 到 stdout

### prompt hook 误判很多

优先缩小问题范围：

1. 先把 `prompt` 规则写得非常具体
2. 只针对单一事件启用
3. 配合 `matcher.tools` 或简单 `if` 限定命中范围
4. 观察 `reason` 是否能清楚解释判断依据

## 配置建议

- 安全策略优先用 `failPolicy: "block"`
- 审计、诊断、日志类 hook 优先用 `failPolicy: "allow"`
- 需要人工审批的 `PreToolUse` 尽量配合 `once: true`
- 能用 `matcher.tools` 缩小范围时，不要让所有工具都命中
- 不要依赖多个 handler 之间的顺序副作用，因为它们会并发执行
- `BeforeStop` 规则要尽量具体，否则容易把正常任务拖进反复续跑
- 不要把密钥明文写进配置；HTTP 认证优先用 `headerSecretRefs`
