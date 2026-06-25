# Tool Output Frames Design

Date: 2026-06-17

## Summary

Swe will support live textual tool output for shell-style tools by streaming dedicated `Tool Output Frame` events to the frontend while the tool is still running. These frames are live presentation only: they are not model-visible context, not final tool results, and not durable chat history. When the terminal tool result arrives, the final result becomes the authoritative tool-card output.

The first version is scoped to `execute_shell_command`-style terminal tools. MCP tools, file reads, search tools, browser tools, and structured business tools do not emit Tool Output Frames in the first version.

## Goals

- Show real shell stdout/stderr incrementally in the frontend while a command is running.
- Preserve the existing final tool-result contract for model context, history rebuilding, summaries, and tool status.
- Let active-run reconnect replay buffered live frames where available.
- Prevent live output from growing without bound in the frontend or in the active stream replay buffer.

## Non-Goals

- Do not make Tool Output Frames visible to the Main Agent as model context.
- Do not persist Tool Output Frames as completed-run chat history.
- Do not split ordinary one-shot tool results into artificial live frames.
- Do not add MCP live output support in the first version.
- Do not replace existing Historical Tool Result Compaction or File Read Truncation behavior.

## Domain Terms

- **Tool Output Frame**: A live, user-visible presentation update for textual output produced while one tool invocation is still running.
- **Live Tool Output Area**: The temporary output area inside a tool card where Tool Output Frames are rendered.
- **Terminal Tool Result Precedence**: The final successful or failed tool result replaces live output as the authoritative tool-card output.
- **Live Tool Output Guard**: The narrow protection layer for live frame eligibility, limits, source preservation, and required redaction.
- **Live Stream Replay**: Best-effort active-run replay of live presentation events during reconnect, not completed-run history recovery.

## Event Shape

Use a dedicated SSE payload shape rather than reusing `PLUGIN_CALL_OUTPUT`, `MCP_CALL_OUTPUT`, or `object: "content"` deltas.

```json
{
  "object": "tool_output_frame",
  "tool_call_id": "call_xxx",
  "tool_name": "execute_shell_command",
  "sequence": 12,
  "source": "stdout",
  "text": "running test_user_flow.py\n",
  "truncated": false
}
```

Fields:

- `object`: Always `tool_output_frame`.
- `tool_call_id`: Stable identifier for the tool invocation. Frames without a matching visible tool call should be ignored by the frontend.
- `tool_name`: Tool name for guard/debug/display routing.
- `sequence`: Monotonic per tool invocation. Ordering is guaranteed only within one tool invocation, not globally across concurrent tools.
- `source`: `stdout`, `stderr`, or `message`.
- `text`: Text delta after live output guarding.
- `truncated`: True when a guard limit or omission marker was applied.

## Backend Flow

1. The agent emits the normal tool-call start message. The frontend creates the running tool card as it does today.
2. The shell tool starts the subprocess and reads stdout/stderr incrementally.
3. Each decoded text delta passes through `Live Tool Output Guard`.
4. Accepted deltas are emitted as `tool_output_frame` events through the live stream path.
5. The shell tool still accumulates stdout/stderr for the final `ToolResponse`.
6. On completion, the shell tool formats the final result through the existing `_format_shell_response()` path.
7. The normal terminal tool output message is emitted with existing `output`, `output_summary`, `tool_status`, and `tool_error` behavior.
8. The frontend replaces the live output with the final tool result.

## Shell Execution Changes

Current Unix shell execution uses `proc.communicate()` and returns output only after process completion. Replace that path with incremental readers:

- Spawn subprocess with stdout/stderr pipes.
- Create one async reader task per stream.
- Decode bytes into text safely.
- Emit guarded frames as text arrives.
- Accumulate stdout/stderr strings for final result formatting.
- Preserve timeout handling and process-group termination semantics.

Windows can remain non-live in the first implementation if incremental parity is risky. In that case, the guard should report no live support for Windows shell execution while preserving the current final result behavior.

## Live Tool Output Guard

The guard applies only to Tool Output Frames and does not replace final tool-result rules.

First-version rules:

- Eligibility: `execute_shell_command` only.
- Default live area limit: 64KB or 2000 lines, whichever is reached first.
- On limit exceed: keep the most recent live output and include an explicit omission marker.
- Preserve source when known: stdout/stderr/message.
- Do not emit frames for tools that cannot provide safe textual deltas.
- Do not allow live frames to expose more than the live guard permits, even if final results are later truncated differently.

## Frontend Flow

1. Extend runtime response handling to recognize `object: "tool_output_frame"`.
2. Locate the running tool card by `tool_call_id`.
3. Append the frame text to that card's live output state.
4. Display stdout/stderr in one ordered stream, preserving source with light styling or labels.
5. Enforce the same 64KB / 2000 line display limit client-side as defense in depth.
6. When final tool output arrives, replace the live output area with the existing final `outputData.output` display.
7. If a tool is cancelled without a final result, keep the last live output as cancellation context.

## Reconnect Semantics

Active runs use the existing TaskTracker replay model: reconnect attaches to the active run and receives buffered SSE events plus new events. Tool Output Frames participate in this active-run replay.

Completed runs do not restore Tool Output Frames. History rendering continues to rebuild from final tool records only.

The active replay buffer must be bounded because live frames are higher volume than ordinary chat events. When the replay limit is exceeded, replay should include an omission marker and the newest retained frames.

## Error And Terminal Behavior

- Success: final successful tool result replaces live output.
- Failure: final failed tool result replaces live output and drives failed status/error presentation.
- Cancellation with final result: final cancellation result wins.
- Cancellation without final result: the card may keep the last live output as cancellation context.

## Compatibility

Existing clients that do not understand `tool_output_frame` should ignore it. Existing final tool output messages remain unchanged, so history rendering and model continuation keep working.

Because Tool Output Frames use a dedicated presentation event, they do not change `PLUGIN_CALL_OUTPUT`, `MCP_CALL_OUTPUT`, `object: "content"` delta semantics, or saved chat history shape.

## Tests

Backend:

- Shell stdout produces ordered Tool Output Frames.
- Shell stderr produces ordered Tool Output Frames with `source: "stderr"`.
- stdout and stderr frames preserve per-tool sequence order.
- Final successful shell result is still returned through the existing ToolResponse path.
- Final failed shell result still raises the existing structured tool failure.
- Timeout still terminates the process group and emits a terminal failed result.
- Live output limit emits an omission marker and does not affect final result formatting.

Frontend:

- Running tool card displays live frames before final output arrives.
- Final output replaces live output on success.
- Final failed output replaces live output and shows failed status.
- Cancellation without final output preserves last live output.
- Unknown `tool_output_frame` for a missing tool call is ignored.
- Client-side live output limit keeps recent content and shows omission.

Reconnect:

- Reconnect during an active run replays buffered Tool Output Frames.
- Completed-run history does not show live frames, only final tool output.

## Open Implementation Questions

- Whether Windows shell execution should get live frames in the first implementation or remain final-result-only.
- The exact internal sink API between shell execution and the runner/channel stream.
- Whether omission markers should be emitted as normal `tool_output_frame` events or as a separate `message` source frame.
