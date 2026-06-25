## Why

Completed assistant responses currently keep Thinking and tool/process cards fully visible above the final answer, which pushes the answer down and makes dense chat results harder to scan. The Conversation Workspace needs a quiet disclosure pattern that preserves process transparency while making the completed final answer the primary reading surface.

## What Changes

- Add a response-level process disclosure for completed assistant runtime responses in the main Conversation Workspace.
- Group non-final process output, including reasoning, tool calls, MCP/plugin calls, retry/progress presentation, and completed failed tool summaries, behind a manual disclosure row after the response is complete.
- Keep final answer content visible by default, including text, Markdown, media/file content, and the existing reasoning fallback for provider responses that misclassify final body text as reasoning.
- Keep active work visible: generating responses, running tools, approval requests, and run-level errors with no final answer remain directly visible.
- Preserve current API contracts, SSE events, message data structures, tool-result semantics, and hidden-tool behavior.

## Capabilities

### New Capabilities

- `chat-response-process-disclosure`: Defines how completed Conversation Workspace responses disclose execution process content while preserving final answer visibility and actionable states.

### Modified Capabilities

- None.

## Impact

- Affected frontend code is expected under `console/src/components/agentscope-chat/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/` and related local styles/tests.
- The change is UI presentation only and should not modify backend routes, request/response payloads, SSE frame formats, persisted chat history, tool status derivation, or model-visible memory.
- Verification will include unit tests for response grouping rules and browser review of the main chat surface at the required desktop sizes, including embedded `hideMenu=true` where applicable.
