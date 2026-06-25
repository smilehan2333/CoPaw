## 1. Pre-Implementation Checks

- [x] 1.1 Run GitNexus impact analysis for `AgentScopeRuntimeResponseCard` before editing the response renderer.
- [x] 1.2 Re-read the affected response renderer, reasoning fallback, tool rendering, and local style/test files to confirm no user changes conflict with the planned implementation.

## 2. Response Grouping

- [x] 2.1 Add response-item classification helpers for answer, process, and direct-attention output.
- [x] 2.2 Preserve existing `reasoningFallback` behavior so fallback answer text remains visible outside process disclosure.
- [x] 2.3 Render completed process items through a single disclosure group above final answer content.
- [x] 2.4 Keep generating, running, approval, and no-answer error states directly visible.
- [x] 2.5 Keep response actions and suggestions outside the process disclosure in their existing post-content position.

## 3. Disclosure UI

- [x] 3.1 Implement a compact Conversation Workspace process disclosure component using existing theme tokens and icon conventions.
- [x] 3.2 Add visible expanded/collapsed affordance, keyboard support, `aria-expanded`, and `aria-controls`.
- [x] 3.3 Add label/status summaries for completed, running, canceled, and failed-process cases.
- [x] 3.4 Add reduced-motion handling and stable hover/focus states that do not shift layout.

## 4. Tests

- [x] 4.1 Add unit tests for completed process plus final answer default collapse.
- [x] 4.2 Add unit tests for manual expand/collapse access.
- [x] 4.3 Add unit tests for generating/running process visibility.
- [x] 4.4 Add unit tests for approval request and no-answer error visibility.
- [x] 4.5 Add unit tests for failed-process disclosure summary when a final answer exists.
- [x] 4.6 Add unit tests proving fallback reasoning answer text remains visible outside the process disclosure.

## 5. Verification

- [x] 5.1 Run the relevant frontend test command for the changed response renderer tests.
- [x] 5.2 Run the relevant frontend lint/type/build checks required by the changed surface when feasible.
- [x] 5.3 Verify the main chat UI at `1280x720`, `1440x900`, and `1920x1080`.
- [x] 5.4 Verify embedded mode with `hideMenu=true` when supported by the chat route.
- [x] 5.5 Check completed, expanded, generating, failed-with-answer, no-answer-error, and approval states for clipping, overlap, horizontal overflow, and operation discoverability.
- [x] 5.6 Run `detect_changes()` before any commit to confirm the affected scope is expected.
