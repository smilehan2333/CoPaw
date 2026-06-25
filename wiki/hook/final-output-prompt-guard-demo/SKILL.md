---
name: final-output-prompt-guard-demo
description: "Use this skill when you need a BeforeStop prompt hook example that reviews the agent's final output against an expected response standard, blocks non-compliant final answers, and allows compliant ones."
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.0"
---

# Final Output Prompt Guard Demo

这个样例演示 skill 级 `BeforeStop + prompt handler`，用于在 Agent 准备结束前，
通过提示词检查最终输出是否符合预期规范。

## 覆盖点

- 事件：`BeforeStop`
- handler 类型：`prompt`
- 目的：检查 `assistant_response` 是否满足最终答复规范；不符合返回 `block`，符合返回 `allow`

## 适用场景

- 最终回复必须说明完成了什么、如何验证、还有哪些限制
- 不允许把未验证的结果写成确定事实
- 不允许遗漏用户明确要求的输出项
- 不允许用含糊的“已完成”“都好了”代替可核查说明

## 关键说明

- `BeforeStop` 上的 prompt 只能返回 `allow` 或 `block`
- prompt handler 的模型输出必须是严格 JSON 对象，只包含 `decision` 和 `reason`
- 返回 `block` 后，系统会在同一次请求里继续尝试修正最终输出
- 这个样例只基于当前 `HookContext` 可见字段判断，不能替代完整 transcript 审计

## 目录内容

1. `hooks/hooks.json`
2. `scripts/build_final_output_payload.py`
3. 当前 `SKILL.md`

## 调试脚本

在 demo 目录下运行：

```bash
python scripts/build_final_output_payload.py
```

脚本会输出一份默认不合规的 `BeforeStop` HookContext 样本。你也可以生成合规样本：

```bash
python scripts/build_final_output_payload.py --case pass
```
