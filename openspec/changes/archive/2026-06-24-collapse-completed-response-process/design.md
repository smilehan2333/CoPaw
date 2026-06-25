## Context

The main Conversation Workspace renders assistant runtime responses through `AgentScopeRuntimeResponseCard`. That component currently maps merged response output directly into `Message`, `Tool`, `Reasoning`, `Error`, retry status, actions, and suggestions. Final body text is rendered by `Message`, while Thinking/reasoning and tool calls are separate response items that appear before or between final answer content.

The current behavior preserves transparency but makes completed responses visually heavy: process cards remain fully visible after the answer is done. The existing `reasoningFallback` helper also protects provider cases where final body text arrives as trailing reasoning, so any grouping logic must keep that fallback visible as answer content.

This change is a presentation-only Conversation Workspace change. It follows `console/DESIGN.md`: preserve the chat theme and `#3769FC` emphasis, keep final answer content as the visual priority, avoid broad management-theme migration, and preserve all runtime contracts.

## Goals / Non-Goals

**Goals:**

- Collapse completed response process content by default while keeping the final answer visible.
- Preserve active and actionable states, including generating responses, running tools, approval requests, and no-answer errors.
- Keep process details manually recoverable in place, above the final answer.
- Maintain accessible disclosure behavior with stable hover/focus states and reduced-motion support.
- Cover live responses and history-loaded completed responses through the same presentation rules.

**Non-Goals:**

- No backend API, SSE, persistence, or message schema changes.
- No change to tool-status derivation, hidden-tool filtering, live tool output semantics, or model-visible memory.
- No persistent user preference for expanded/collapsed state.
- No migration of analytics read-only chat surfaces, task run group cards, or the broader Conversation Workspace design.
- No global `console/DESIGN.md` rule change unless implementation reveals a reusable visual rule beyond this response component.

## Decisions

### Group at the response-rendering layer

Implement grouping in or directly below `AgentScopeRuntimeResponseCard`, after `AgentScopeRuntimeResponseBuilder.mergeToolMessages()` and before rendering individual response items.

Rationale:

- The response card is where final body messages, reasoning, tool calls, approval requests, errors, actions, and suggestions are visible together.
- Grouping lower inside `Thinking`, `ToolCall`, or Markdown would only collapse individual cards and would not produce the requested single completed-process disclosure.
- Grouping higher at the bubble/list layer would lose access to response message types and status semantics.

Alternative considered: set each `Thinking` and `ToolCall` card to closed by default. Rejected because it still leaves multiple process rows visible and does not communicate one response-level execution process.

### Classify visible items as answer, process, or direct attention

Classify response output into three presentation buckets:

- Answer: `MESSAGE` content, media/file content, refusal content, and `reasoningFallback` Markdown.
- Process: completed reasoning, completed tool/MCP/plugin calls, retry/progress presentation, and failed tool calls when a final answer exists.
- Direct attention: approval requests, generating/running items, run-level errors without a final answer, and failures that are the only visible outcome.

Rationale:

- The user asked to hide previous process after output completes, not to hide actionable states or final results.
- Approval requests are not historical process; they require user action.
- Errors with no answer are the answer-equivalent outcome and must remain visible.

Alternative considered: collapse every non-message output after response completion. Rejected because it would hide approvals and no-answer errors.

### Default collapse only when the response is complete or history-idle

Default the process disclosure to collapsed when the response is terminal or history-loaded idle with no generating content. Keep it expanded or directly visible while a response is in progress.

Rationale:

- During generation, process visibility reassures users that work is happening.
- After completion, the final answer becomes the primary reading target.
- History-loaded completed responses should match newly completed responses for scanability.

State is local to the mounted page. User toggles are remembered only while the component remains mounted and are not written to backend state, local storage, or user settings.

### Use a quiet in-place disclosure component

Render a compact disclosure row above the final answer, using existing AgentScope/Ant theme tokens and the Conversation Workspace visual direction.

Target presentation:

- Label examples: `执行过程 · 3 步 · 已完成`, `执行过程 · 正在执行`, `执行过程 · 4 步 · 含 1 个失败`, `执行过程 · 已取消`.
- Height around 28-32px, 12px text, neutral border or subtle fill, visible arrow, no hover-only primary affordance.
- Expand/collapse animation around 150-220ms and disabled or reduced under `prefers-reduced-motion`.
- `button` semantics or equivalent keyboard-accessible control with `aria-expanded`, `aria-controls`, and a clear accessible name.

Rationale:

- The row should be findable without competing with the final answer.
- Keeping it above the answer preserves the existing chronology and matches the user's screenshot.

### Preserve actions and suggestions after response content

Keep response actions and suggestions in their current post-content position. The process disclosure wraps only process output, not response-level actions or follow-up suggestions.

Rationale:

- Actions and suggestions operate on the completed answer and should stay discoverable.
- Moving them into process disclosure would make normal answer operations harder to find.

## Risks / Trade-offs

- [Risk] Misclassifying final body text as process could hide the answer. -> Mitigation: preserve and test `reasoningFallback` rendering outside the process disclosure.
- [Risk] Hiding failures could reduce debuggability. -> Mitigation: show failure counts/status in the disclosure row when a final answer exists, and keep no-answer errors directly visible.
- [Risk] Auto-collapse during active streaming could make the UI look idle. -> Mitigation: never default-collapse generating/running process content.
- [Risk] The compact row may be too subtle for users who need auditability. -> Mitigation: keep the disclosure row always visible, keyboard-focusable, and above the answer.
- [Risk] Browser screenshots may reveal layout shifts or clipping in embedded containers. -> Mitigation: verify required desktop sizes and `hideMenu=true`, with long tool names and Chinese text.

## Migration Plan

This is a frontend-only incremental change. Implement behind the normal component code path without data migration. Rollback is the removal of the response-level grouping/disclosure component, which restores the current direct rendering order.

## Open Questions

None. The owner confirmed process boundaries, failure/approval behavior, disclosure position, local-only toggle state, visual direction, and first-version scope during discussion.
