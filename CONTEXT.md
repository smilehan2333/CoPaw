# Swe Agent Runtime

This context defines the domain language for Swe's agent orchestration runtime, especially how the main agent coordinates SubAgent work.

## Language

**SubAgent Definition**:
A named, versioned worker profile that describes what kind of delegated work a SubAgent can perform. One **SubAgent Definition** can be used by many **SubAgent Runs**.
_Avoid_: custom subagent, subagent template, agent config

**SubAgent Run**:
A single observable execution instance created when the main agent delegates work to a SubAgent Definition. A **SubAgent Run** is not a new SubAgent Definition.
_Avoid_: create subagent, custom subagent, subagent profile

**Delegation Run**:
Alias for **SubAgent Run** when emphasizing the parent-to-worker handoff rather than the worker identity.
_Avoid_: subagent creation

**Main Agent**:
The user-facing agent that owns global task understanding, user interaction, mode decisions, and final responses.
_Avoid_: parent bot, orchestrator bot

**Plan Mode**:
A user-visible planning state where the Main Agent itself runs under reduced planning permissions and interacts with the user through planning cards before execution continues.
_Avoid_: dry run, planning prompt

**Proposed Plan**:
A planning artifact presented by the Main Agent for user review before continuing work. A Proposed Plan contains a plan id, title, summary, steps, risks, verification items, open questions, and confidence.
_Avoid_: permission request, execution unlock

**Plan Review Decision**:
The user's response to a Proposed Plan: `revise`, `execute`, or `exit_plan`. `revise` keeps Plan Mode active for replanning, `execute` accepts the persisted Proposed Plan and continues in normal mode, and `exit_plan` closes Plan Mode without starting a Main Agent execution run by default.
_Avoid_: tool approval, permission grant

**Plan Interaction Card**:
A structured chat UI card used by the Main Agent to ask for planning clarification or present a Proposed Plan. A Plan Interaction Card is user-facing and is not emitted directly by a SubAgent.
_Avoid_: subagent question card, free-form prompt hack

**Planning Clarification Card**:
A Plan Interaction Card that asks the user for missing planning information using single choice, multiple choice, or text input.
_Avoid_: generic form, survey

**Plan Interaction Response**:
The user's structured answer to a Plan Interaction Card, submitted as the next normal chat turn with metadata that identifies the card and selected or entered value.
_Avoid_: hidden plan API update, out-of-band form submission

**Plan Interaction Tool**:
A built-in Main Agent tool that emits Plan Interaction Cards through validated structured metadata.
_Avoid_: markdown JSON card, frontend text parser

**Plan Clarification Tool**:
The Plan Interaction Tool used by the Main Agent to ask the user a single planning clarification question.
_Avoid_: generic question tool, subagent prompt

**Proposed Plan Tool**:
The Plan Interaction Tool used by the Main Agent to present a Proposed Plan for `revise`, `execute`, or `exit_plan` review.
_Avoid_: final answer tool, permission approval tool

**Plan Delegation**:
An optional Main Agent action in Plan Mode that creates a SubAgent Run through the normal delegation mechanism. Plan Delegation is allowed but is never automatic or required by Plan Mode.
_Avoid_: default plan subagent, automatic plan researcher

**Planning Readonly Policy**:
The reduced permission policy applied to the Main Agent in Plan Mode. It allows repository reading, searching, current-time lookup, readonly shell commands, and readonly SubAgent delegation while forbidding workspace mutation, tests, deployment, migration, and progress/static-copy side effects.
_Avoid_: full readonly mode, approval mode

**Explicit Plan Entry**:
A user-visible action that starts Plan Mode for a turn or session. Plan Mode is not entered silently by Main Agent inference.
_Avoid_: automatic plan detection, implicit planning

**Plan Mode State**:
The chat-session state indicating whether future turns in that chat should run in Plan Mode. One chat session has at most one current Plan Mode State.
_Avoid_: one-shot plan flag, global plan switch

**Scheduled Job**:
A recurring task definition owned by a tenant and executed by the runtime at configured times. One **Scheduled Job** can have many **Scheduled Runs**.
_Avoid_: cron config, timer task

**Scheduled Run**:
A single execution of a **Scheduled Job**, whether triggered by schedule or manually.
_Avoid_: cron call, job instance

**Scheduled Run Boundary**:
A runtime boundary that starts scheduled work outside an incoming user HTTP request. It includes **Scheduled Job**, heartbeat, and dream execution, but not cron management API requests.
_Avoid_: cron entry, cron API, scheduler callback

**Execution Model Slot**:
An optional model selection pinned to a **Scheduled Job**. If absent, each **Scheduled Run** uses the **Tenant Default Model** at execution time.
_Avoid_: model params, cron model

**Execution Model Fallback**:
The behavior where a **Scheduled Run** uses the current **Tenant Default Model** when its configured **Execution Model Slot** cannot be used. The fallback is silent in the user interface but must remain visible in operational records.
_Avoid_: hard failure, invisible fallback

**Tenant Provider Configuration**:
The tenant-scoped set of LLM provider definitions and model choices available for model selection. One **Tenant Provider Configuration** contains many provider entries and identifies at most one **Tenant Default Model**.
_Avoid_: model cache, global provider list, system model config

**Tenant Default Model**:
The active LLM selection for a tenant, used by agent work when no narrower **Execution Model Slot** is specified.
_Avoid_: global model, system default model

**Empty Model Output**:
A model-call outcome where the provider call succeeds but returns no usable assistant content for the runtime to continue or complete agent work. Text, tool-use, structured content, and reasoning content are all usable model content; empty strings, whitespace-only text, empty lists, and missing content are not. **Empty Model Output** is scoped to model-call handling, not to a whole Scheduled Run or chat turn that merely ends with no visible text.
_Avoid_: output_len=0, blank reply, empty cron output

**Source System Configuration**:
A source-scoped runtime configuration surface for behavior shared by requests from the same external source. It is not a tenant configuration and does not describe user, organization, or workspace identity.
_Avoid_: system feature configuration, tenant config, user config

**Runtime Request Identity**:
The tenant and source context that determines which runtime configuration and model selection a request observes. One **Runtime Request Identity** resolves to one **Tenant Provider Configuration** view for provider and active-model reads.
_Avoid_: cache key, auth header set, iframe context

**Mandatory Console Channel**:
The built-in **Console Channel** is a runtime invariant that is always treated as enabled for every agent and tenant, including when no explicit channel entry has been saved yet. Users may configure its other fields, but persisted, imported, or interactive configuration must not disable it.
_Avoid_: optional console, disabled console, console toggle

**Channel Management Constraint**:
A system-managed channel rule that remains visible in channel management and tells clients which channel state is enforced rather than user-editable. A **Channel Management Constraint** may lock one field while leaving the rest of the channel configurable.
_Avoid_: frontend-only hardcode, hidden channel rule, implicit UI behavior

**Console Output Suppression**:
A runtime-only behavior that temporarily suppresses terminal printing in a specific execution path. **Console Output Suppression** does not change **Mandatory Console Channel** state and is not part of channel management.
_Avoid_: disabled console channel, channel off, console config

**Historical Tool Result Compaction**:
A conversation-history cleanup behavior that shortens previously stored tool results so the Main Agent can continue within context limits. It is separate from truncating the first result returned by a tool call.
_Avoid_: tool output truncation, file read truncation, live tool truncation

**File Read Truncation**:
A source-scoped limit on text returned by file-reading tools during the same turn that reads the file. It is separate from **Historical Tool Result Compaction**.
_Avoid_: file compaction, historical tool result compaction

**Tool Output Controls**:
The user-facing grouping for source-scoped controls over historical tool-result compaction and file-read output truncation.
_Avoid_: tool result compression configuration

**Tool Call Status**:
The user-visible lifecycle state of one user-visible tool invocation during a Main Agent run. A **Tool Call Status** describes an individual tool invocation as running, successful, or failed; failed means the tool itself failed, not that the user stopped or cancelled the overall Main Agent run. The start of a tool invocation carries the running status, and the tool's returned output carries the successful or failed terminal status.
_Avoid_: tool event status, frontend tool result, trace status

**Tool Output Frame**:
A live, user-visible presentation update for textual output produced while one tool invocation is still running. A **Tool Output Frame** belongs to exactly one **Tool Call Status** lifecycle, preserves its output source when known, is ordered only within that tool invocation, is not visible to the Main Agent as model context, and is not itself the final tool result remembered by the Main Agent.
_Avoid_: partial tool result, durable output chunk, tool memory frame, streaming object result

**Live Tool Output Area**:
The user-visible region inside a tool card where **Tool Output Frames** for that tool invocation are rendered during execution. A **Live Tool Output Area** is part of the tool presentation, not a separate assistant message in the conversation, and the final tool result becomes the card's authoritative output when it arrives.
_Avoid_: log chat message, separate output bubble, global tool log

**Terminal Tool Result Precedence**:
The rule that a successful or failed final tool result replaces the **Live Tool Output Area** as the authoritative tool-card output. If a tool is cancelled without a final result, the card may keep the last live output as cancellation context.
_Avoid_: live output as final result, partial result precedence

**Live Tool Output Guard**:
The narrow runtime protection applied before **Tool Output Frames** are sent for live presentation. A **Live Tool Output Guard** controls live output eligibility, live display limits, live replay limits, source preservation, and required redaction for real-time frames without replacing the existing final tool-result rules.
_Avoid_: tool output policy, final result policy, historical compaction policy

**Live Stream Replay**:
The best-effort restoration of live presentation events for a Main Agent run that is still active when the user reconnects. **Live Stream Replay** may include **Tool Output Frames** from the active run, but it is not historical recovery after the run has ended.
_Avoid_: chat history replay, durable tool log, completed-run output restore

**Tool Error Summary**:
A user-visible, bounded explanation attached to a failed **Tool Call Status**. A **Tool Error Summary** is not an audit record, diagnostic log, or full raw tool failure.
_Avoid_: raw tool error, tool failure log, audit error

**Tool Execution Error**:
An explicit runtime exception raised by a tool or tool-adjacent runtime path to declare that the tool invocation itself failed. A **Tool Execution Error** carries canonical failure semantics and is not just an arbitrary Python exception or plain-text output string.
_Avoid_: generic exception, plain-text tool failure, error string

**Structured Tool Failure Result**:
A persisted `tool_result` failure payload encoded in the MCP-style shape with `isError=true` and failure content blocks. A **Structured Tool Failure Result** is the canonical terminal output for failed tool invocations across local tools, MCP tools, and runtime-generated failures.
_Avoid_: plain-text failure output, ad-hoc error JSON, inferred tool failure

**MCP Availability Failure**:
A failure that prevents an enabled MCP client from becoming usable by an Agent, including failure to connect or discover its available capabilities. An **MCP Availability Failure** is distinct from an individual MCP tool invocation returning a **Structured Tool Failure Result**.
_Avoid_: MCP tool failure, optional MCP skip, successful connection log

**Hook Telemetry Event**:
A structured observability record for one Hook Runtime boundary, used to analyze hook behavior without changing the hook's runtime decision semantics. A **Hook Telemetry Event** includes the boundary-level outcome and the handler-level details that explain it, and is emitted in a log-collection-friendly shape rather than persisted as a Trace Span.
_Avoid_: debug log, audit record, raw hook payload, trace span

**Hook Telemetry Log Message**:
A single-line structured application log message with a stable hook telemetry prefix and a JSON payload. **Hook Telemetry Log Message** is a normal operational signal, not an exceptional alert, and does not imply changing the global log formatter.
_Avoid_: global JSON logging, unstructured hook log, trace span, warning log

**Hook Telemetry Emission Boundary**:
The rule that a **Hook Telemetry Log Message** is emitted only when at least one hook handler actually runs for a Hook Runtime boundary.
_Avoid_: unmatched hook boundary log, resolver miss telemetry

**Hook Telemetry Correlation**:
The relationship between a **Hook Telemetry Log Message** and the request or trace that caused it. **Hook Telemetry Correlation** should include a trace identifier when one is available, but a missing trace identifier does not make the telemetry event invalid.
_Avoid_: mandatory trace span linkage, uncorrelated hook log

**Hook Telemetry Schema**:
The versioned JSON shape inside a **Hook Telemetry Log Message**. The schema records correlation fields, boundary-level outcome fields, and handler-level details while excluding raw hook payloads by default.
_Avoid_: ad-hoc log fields, raw payload schema, trace span schema

**Application Log Output Pipeline**:
The operational path that carries Swe application log records from runtime emission to process-visible outputs. An **Application Log Output Pipeline** transports ordinary and structured log records without changing their domain meaning or schema.
_Avoid_: telemetry schema, audit log, business operation log, tool output frame

**Hook Boundary Outcome**:
The merged result of one Hook Runtime boundary after all matching handlers have been resolved and combined.
_Avoid_: handler result, raw hook output, final log line

**Hook Handler Detail**:
The observable result of one hook handler within a **Hook Telemetry Event**, kept so slow, failed, blocking, or input-mutating handlers can be diagnosed. **Hook Handler Detail** stores structured metadata and redacted, bounded previews rather than full handler input or output.
_Avoid_: hook boundary outcome, raw handler payload

**Hook Payload Preview**:
A redacted and size-bounded representation of hook-adjacent text or structured data used for diagnosis without retaining the original payload.
_Avoid_: raw prompt, raw tool input, raw tool output, full updated input

**Current Tool Response**:
The successful output produced by the current tool invocation for the active `PostToolUse` boundary. A **Current Tool Response** is the tool's business output, not the full persisted `tool_result` block and not a **Hook Conversation Snapshot**.
_Avoid_: full tool result block, conversation snapshot, AgentScope acting return value

**Hook Conversation Snapshot**:
A bounded hook-facing snapshot of the current session's message list at one Hook Runtime boundary, including normal user, assistant, tool-call, and tool-result messages while excluding reasoning content. A **Hook Conversation Snapshot** is not the saved transcript file and is not the full Agent state.
_Avoid_: full context, transcript contents, agent state dump, reasoning trace

**Session Skill Freshness**:
The cross-turn behavior that determines when a chat session starts using updated skill content. In this context, **Session Skill Freshness** means skill changes take effect on the next turn, not during an in-flight turn.
_Avoid_: skill hot reload, mid-turn skill reload, live skill patch

**Skill Directory Revision**:
The content identity of one skill across its full directory tree, including `SKILL.md`, scripts, references, and other skill-owned files. A **Skill Directory Revision** changes when any tracked file in that skill directory changes.
_Avoid_: SKILL.md version, single-file skill update, prompt-only skill change

**Skill Directory Freshness Token**:
A lightweight change marker for one skill directory, derived from a stable digest of each tracked file's relative path, `mtime_ns`, and size rather than strict content hashing. In this context, next-turn skill freshness checks compare the stored **Skill Directory Freshness Token** to the current one and accept heuristic rather than exact change detection.
_Avoid_: strict content revision, canonical content identity, cryptographic signature

**Session Associated Skill Set**:
The set of skills that a chat session has already depended on through explicit declaration, detector activation, or direct skill-file reading. **Session Skill Freshness** applies only to this **Session Associated Skill Set**, not to every enabled skill.
_Avoid_: all enabled skills, global active skills, workspace skill set

**Session Skill Snapshot**:
A session-state record that stores the session's **Session Associated Skill Set** together with each skill's last known **Skill Directory Freshness Token**. The **Session Skill Snapshot** is the persisted basis for cross-turn freshness checks.
_Avoid_: trace-derived skill history, transient detector state, prompt-only cache

**Skill Freshness Refresh**:
The next-turn refresh step that rebuilds prompt state and requires the model to re-read the current `SKILL.md` when a stored **Session Skill Snapshot** no longer matches the latest **Skill Directory Freshness Token**.
_Avoid_: mid-turn reload, background hot patch, user-visible skill reset

**Skill Freshness Notice**:
An internal model-facing notice added on the next turn after a **Skill Freshness Refresh**. A **Skill Freshness Notice** uses cautious wording such as detecting a skill-directory change, tells the model that current skill content supersedes assumptions formed from earlier turns, and requires the model to re-read the current `SKILL.md` before relying on that skill. It references the skill path instead of inlining the skill body, can explicitly name a directory switch, and is not exposed to the Console stream or persisted into chat history.
_Avoid_: user-visible message, persistent banner, historical chat message, silent refresh only

**Confirmed Skill Association**:
The point at which a skill becomes part of the session's durable dependency set because the runtime actually activated it, rather than merely suspecting it. Only a **Confirmed Skill Association** can add a skill to the **Session Associated Skill Set**.
_Avoid_: low-confidence guess, enabled-skill membership, possible skill match

**Market Skill Owner Set**:
The current set of users who own a market skill within one source, as resolved by market skill owner reverse lookup. A **Market Skill Owner Set** is based on current user skill state and is not a historical distribution audit; readiness workflows resolve this set server-side so the displayed owner list and checked user set share the same source of truth.
_Avoid_: assigned users, distribution history, skill install log

**Skill Readiness Skill Id**:
The `skill_id` value used to find readiness configuration and related scheduled jobs for a market skill. A **Skill Readiness Skill Id** normally comes from the market-provided skill id; before that id exists, the market skill's stable `skill_name` may be used as a fallback value while keeping the field name `skill_id`; allowed values use only letters, digits, underscore, hyphen, dot, and colon.
_Avoid_: skill_key, display name, version, historical distribution id

**Skill Readiness Configuration**:
A runtime configuration keyed by **Skill Readiness Skill Id** that declares which readiness checks apply to a market skill and what parameters those checks use. A **Skill Readiness Configuration** is stored as runtime configuration, not as a deployment-local YAML file; source identity belongs to readiness execution and result isolation rather than the base configuration key.
_Avoid_: static checklist, local YAML, global skill rule

**Skill Readiness Run**:
One asynchronous execution that checks the full **Market Skill Owner Set** for one **Skill Readiness Skill Id** within a specific source. A **Skill Readiness Run** uses `source_id` to resolve the user set, user runtime directories, scheduled jobs, credentials, and result isolation.
_Avoid_: configuration lookup, frontend scan, historical distribution audit

**Skill Readiness Run Progress**:
The observable progress counts for a **Skill Readiness Run**. `failed_users` means users whose readiness result is abnormal, not backend task failures.
_Avoid_: backend failure count, transport error count

**Skill Readiness Run Status**:
The lifecycle state of a **Skill Readiness Run** as shown to administrators. `partial` means some user results are available while non-fatal lookup or check failures prevented a fully complete run.
_Avoid_: backend process status, HTTP request status

**Skill Readiness User Result**:
The readiness outcome for one user inside a **Skill Readiness Run**. A **Skill Readiness User Result** is abnormal when any configured readiness check for that user fails.
_Avoid_: tenant health, backend task result, owner lookup row

**Skill Readiness Check Status**:
The normalized outcome of one readiness check. A check is `pass`, `fail`, or `skip`; technical errors are represented as `fail` with an explanatory message and details rather than a separate status.
_Avoid_: error status, exception category, backend failure class

**Skill Readiness Check Name**:
The stable strategy name of one readiness check inside configuration and results. New readiness check types extend this name registry and generic result payloads rather than adding per-check database columns or per-check APIs.
_Avoid_: KPI, metric column, hard-coded result field

**Profile Identity Block**:
The fixed user identity section appended to `PROFILE.md` through the agent initialization API, containing fields such as branch id, outlet organization id, position id, and customer manager id. A **Profile Identity Block** is distinct from free-form profile memories or general user preference notes.
_Avoid_: arbitrary profile content, memory note, full user info API payload

**Skill Readiness Job Binding**:
The relationship between a **Scheduled Job** and one or more **Skill Readiness Skill Id** values. A paused **Scheduled Job** still counts as a binding, while a disabled job does not count as executable for readiness checks; copied or broadcast jobs preserve the binding unless explicitly changed.
_Avoid_: skill_key binding, skill distribution record, cron tag

**Missing Associated Skill**:
An associated skill whose previously recorded directory can no longer be resolved at freshness-check time. In this context, a **Missing Associated Skill** does not trigger a refresh or notice by itself, and its snapshot entry is silently removed.
_Avoid_: failed refresh, implicit invalidation, required user repair

**Applied Skill Snapshot**:
The refreshed **Session Skill Snapshot** written immediately after a turn detects and applies a **Skill Freshness Refresh** and any one-turn **Skill Freshness Notice**. An **Applied Skill Snapshot** prevents the same freshness-token change from re-triggering on later turns.
_Avoid_: end-of-turn-only snapshot, pending snapshot, repeated refresh marker

**Session Skill Snapshot Record**:
One top-level session-state record, stored alongside other runner-managed state rather than inside agent memory state. In this context, the **Session Skill Snapshot** is a dedicated session-state key.
_Avoid_: agent memory field, embedded agent state, prompt state blob

**Session Skill Snapshot Entry**:
One persisted association record inside the **Session Skill Snapshot**, containing at least `skill_name`, `resolved_skill_dir`, and `freshness_token`. The entry tracks the concrete skill directory that the session previously depended on.
_Avoid_: name-only skill record, manifest-only reference, implicit directory lookup

**Immediate Skill Snapshot Capture**:
The persistence rule that writes a **Session Skill Snapshot Entry** as soon as a **Confirmed Skill Association** happens within the current turn. It does not wait for turn completion.
_Avoid_: end-of-turn batch write, delayed baseline capture, next-turn first write

**Associated Skill Directory Switch**:
The case where the same `skill_name` resolves to a different `resolved_skill_dir` than the one stored in the session snapshot. In this context, an **Associated Skill Directory Switch** counts as an effective skill change.
_Avoid_: name-only identity match, ignored source switch, path-agnostic reuse

**Associated Skill Withdrawal**:
The case where a previously associated skill is still present on disk but is no longer part of the current turn's effective skill set. In this context, an **Associated Skill Withdrawal** counts as an effective skill change, triggers refresh/notice, and removes the snapshot entry.
_Avoid_: silent disable drift, missing-skill ignore case, stale effective skill

**Aggregated Skill Freshness Notice**:
One per-turn **Skill Freshness Notice** that combines all effective associated-skill changes detected for that turn. It lists affected skills item-by-item instead of emitting separate notices per skill.
_Avoid_: per-skill notice spam, repeated freshness banners, fragmented model notice

**System Runtime Diagnostic**:
A periodic, Runtime Instance-scoped assessment of the Swe backend service's load, responsiveness, process resources, and storage capacity. It is broader than a liveness probe and does not execute an Agent Heartbeat.
_Avoid_: self-check, health endpoint, Agent Heartbeat

**Liveness Probe**:
A Runtime Instance signal that only proves the backend request-serving process can answer immediately. A **Liveness Probe** is not a dependency check and must not describe tenant, workspace, source configuration, database, Agent runtime, or scheduled work availability.
_Avoid_: readiness check, system self-check, health diagnostic

**Request Execution Load**:
The current load and responsiveness of the backend request-serving runtime within one Runtime Instance, distinct from tenant or business-runtime usage.
_Avoid_: Flask worker usage, ordinary HTTP throughput, request latency, tenant usage statistics, Agent Run count, LLM load

**Runtime Instance**:
One running Swe service container in a multi-instance deployment, independently from the business-facing instances used for user allocation.
_Avoid_: business instance, tenant, Supervisor process

**Diagnostic Run**:
One System Runtime Diagnostic collection performed by a Runtime Instance.
_Avoid_: latest-only snapshot, request-time probe, liveness response

**Diagnostic Flow Record**:
One append-only record containing the metrics collected by one Runtime Instance during one Diagnostic Run. It supports latest-state queries and historical trend analysis.
_Avoid_: EAV diagnostic item, JSON payload, LONGTEXT payload, diagnostic run ID

**Runtime Diagnostic Log**:
A machine-readable event emitted by Swe to report Runtime Instance lifecycle or a Diagnostic Flow Record for asynchronous downstream persistence.
_Avoid_: direct diagnostic database write, free-form diagnostic message, Kafka implementation in Swe

**Diagnostic Lease**:
A renewable period during which a Runtime Instance is considered present. Graceful deregistration ends it immediately; expiry makes an abnormally terminated Runtime Instance ineffective.
_Avoid_: permanent active flag, shutdown-only invalidation

## Flagged Ambiguities

**"Create SubAgent"**:
Resolved to mean creating a **SubAgent Run**, not creating a new **SubAgent Definition**. User-defined SubAgent Definition CRUD/UI is outside the next stage.

**"Enter Plan Mode"**:
Resolved to require an **Explicit Plan Entry** such as a chat-window toggle or `/plan` command. Automatic silent switching is outside the next stage.

**"Plan Mode Toggle Scope"**:
Resolved as a persistent per-chat-session **Plan Mode State**, stored with the chat metadata rather than treated as a one-shot send option.

**"Plan Mode Permissions"**:
Resolved as a reduced-permission Main Agent mode. SubAgent runtime rules remain available as a separate delegation mechanism, but Plan Mode no longer depends on a default planning SubAgent.

**"Plan Approval"**:
Resolved as the `execute` **Plan Review Decision** on a **Proposed Plan**. `execute` accepts the persisted plan and can transition the chat out of Plan Mode into normal execution.

**"Execute Mode Transition"**:
Resolved to automatically close the current chat session's **Plan Mode State** before normal execution continues with the persisted Proposed Plan as accepted plan context.

**"Revise Mode Transition"**:
Resolved to keep Plan Mode active and submit the user's revision feedback as a Plan Interaction Response for replanning.

**"Exit Plan Mode Transition"**:
Resolved to automatically close Plan Mode without starting a Main Agent execution run by default, because Plan Mode is itself a special mode of the Main Agent rather than a separate worker.

**"Console Channel Toggle"**:
Resolved to the **Mandatory Console Channel** rule. Channel management may expose Console configuration, but it must not allow the effective Console enablement state to become false.

**"Console Channel vs Terminal Output"**:
Resolved as two different concepts. The always-on rule applies only to the managed **Console Channel** configuration, not to unrelated runtime terminal-output suppression behavior.

**"Plan SubAgent"**:
Resolved as outside the next Plan Mode design. The existing SubAgent runtime and delegation rules remain, but Plan Mode does not require an automatic built-in planning SubAgent.

**"Hook Instrumentation Log"**:
Resolved as a **Hook Telemetry Log Message** emitted for log collection and analysis, not a Trace Span persisted in tracing storage and not a global logging format change.

**"Plan Mode Delegation"**:
Resolved as allowed but optional. Plan Mode may expose `delegate_to_subagent`, but it does not auto-call `plan-researcher` or any other built-in SubAgent.

**"Plan Mode Tool Scope"**:
Resolved as the **Planning Readonly Policy**: `read_file`, `grep_search`, `glob_search`, `get_current_time`, readonly shell, and readonly `delegate_to_subagent` are allowed; `write_file`, `edit_file`, `copy_file_to_static`, `update_task_progress`, mutating shell, test commands, deployment commands, and migration commands are forbidden.

**"Plan Interaction Types"**:
Resolved to support only `single_choice`, `multi_choice`, `text_input`, and `plan_review` in the first version.

**"Plan Card Submission"**:
Resolved as a normal next chat turn carrying **Plan Interaction Response** metadata, not a separate plan-state API call.

**"Plan Card Emission"**:
Resolved as a **Plan Interaction Tool** call. The frontend must not infer planning cards from free-form assistant text JSON.

**"Plan Interaction Tool Shape"**:
Resolved as two built-in tools: `ask_plan_clarification` for clarification cards and `submit_proposed_plan` for final plan review cards.

**"Proposed Plan Fields"**:
Resolved as `plan_id`, `title`, `summary`, `steps[]`, `risks[]`, `verification[]`, `open_questions[]`, and `confidence` for the first version.

**"Scheduled Job Default Model"**:
Resolved as execution-time model resolution: if a **Scheduled Job** has no **Execution Model Slot**, each run uses the current **Tenant Default Model** rather than the default model that existed when the job was created.

**"Scheduled Job Model Override"**:
Resolved as an optional **Execution Model Slot** stored on a **Scheduled Job** only when the user explicitly selects a model for that job.

**"Invalid Scheduled Job Model"**:
Resolved as **Execution Model Fallback**: if a stored **Execution Model Slot** no longer resolves at execution time, the **Scheduled Run** falls back to the current **Tenant Default Model** without a user-facing error while retaining the original slot and fallback reason in logs and execution records.

**"Broadcast Scheduled Job Model"**:
Resolved to copy the **Execution Model Slot** only when the target tenant has the same provider and model. If the target tenant lacks that model, the copied **Scheduled Job** has no **Execution Model Slot**, uses the target tenant's **Tenant Default Model**, and reports a non-failing notice in the broadcast result.

**"Text Scheduled Job Model"**:
Resolved as no **Execution Model Slot**. Text **Scheduled Jobs** do not perform model execution, so any submitted model selection is ignored and the saved job has no **Execution Model Slot**.

**"System Feature Configuration"**:
Resolved as **Source System Configuration** in this context. The configuration is scoped by source, not by tenant or user.

**"Tool Result Compression Switch"**:
Resolved as controlling **Historical Tool Result Compaction** only. **File Read Truncation** needs an independent switch.

**"PostToolUse tool_response"**:
Resolved as **Current Tool Response**: the current tool invocation's business output. It must not mean the full persisted `tool_result` block, the AgentScope `_acting()` return value, or data recovered through **Hook Conversation Snapshot**.

**"Immediate Truncation Configuration Placement"**:
Resolved as sibling configuration under **Source System Configuration**, not nested inside the **Historical Tool Result Compaction** configuration.

**"Tool Exception Contract"**:
Resolved as **Tool Execution Error** for explicit tool-declared failure, with generic exceptions preserved only as a fallback path.

**"Canonical Failed Tool Output Shape"**:
Resolved as **Structured Tool Failure Result**, using the MCP-style `isError=true` result shape rather than plain-text failure strings.

**"Streaming Tool Output Scope"**:
Resolved as **Tool Output Frame** support for long-running tools with naturally incremental textual output. Ordinary one-shot tools should not split their final result into artificial frames.

**"Initial Live Tool Output Scope"**:
Resolved as shell-style terminal tools only. MCP, file-reading, search, browser, and structured business tools do not emit **Tool Output Frames** in the first version.

**"Live Tool Output Limit"**:
Resolved as a presentation and live-replay protection for the **Live Tool Output Area** only. When the final tool result arrives, the tool card's authoritative output follows the normal final-result rules rather than the live-output limit.

**"Live Tool Output Default Limit"**:
Resolved as 64KB or 2000 lines for the **Live Tool Output Area**, whichever is reached first. When the limit is exceeded, Swe keeps the most recent live output and shows an explicit omission marker.

**"Tool Output Frame Stream Shape"**:
Resolved as a dedicated presentation event for **Tool Output Frames**, not a final tool-output message and not a model-visible content delta.

**"Immediate Truncation Defaults"**:
Resolved as preserving existing runtime behavior when a source has no explicit override. File reads keep their current default limit.

**"Disable Immediate Truncation"**:
Resolved as preserving the full immediate output for that output category. It does not mean falling back to an Agent default threshold.

**"Immediate Truncation Limit Name"**:
Resolved as `max_bytes` for immediate truncation concepts. `old_max_bytes` and `recent_max_bytes` remain specific to **Historical Tool Result Compaction**.

**"Immediate Truncation Limit Bounds"**:
Resolved as integer byte limits with a default of 50000 and a minimum of 1000 for **File Read Truncation**. No source-level maximum is defined.

**"File Read Truncation Limit Scope"**:
Resolved as output-only. **File Read Truncation** uses `max_bytes` to limit the text returned to the model and conversation, and does not introduce a source-level limit for how much data is read from storage.

**"File Read Truncation Migration"**:
Resolved as compatibility-first. If a source has no explicit **File Read Truncation** configuration, file reads continue using the historical tool-result recent limit; once **File Read Truncation** is explicitly configured, it fully owns file-read immediate truncation.

**"File Read Truncation Safety Limit"**:
Resolved as no separate non-configurable hard limit for file-read immediate output. When file-read truncation is explicitly disabled, Swe should not silently impose another truncation threshold for that category.

**"File Read Internal Protection"**:
Resolved as outside **Source System Configuration**. Swe may keep an internal storage-read protection limit, but hitting it must be visible rather than silently treated as a complete file read.

**"Tool Output Controls UI"**:
Resolved as one user-facing group with two sections: **Historical Tool Result Compaction** and **File Read Truncation**.

**"Immediate Truncation Explicit Ownership"**:
Resolved as represented by retaining the immediate truncation configuration object, at least with its `enabled` field. Default-value pruning must not erase explicit ownership of **File Read Truncation**.

**"Cron Entry"**:
Resolved as **Scheduled Run Boundary** when discussing runtime behavior. Cron management API requests remain normal HTTP requests and are outside this term.

**"Skill Reload During A Session"**:
Resolved as **Session Skill Freshness** with next-turn scope. A skill file change must affect the next turn in the same chat session, not the currently running turn.

**"Skill Update Scope"**:
Resolved as **Skill Directory Revision**, not `SKILL.md`-only monitoring. Any tracked file change inside the skill directory counts as a skill update.

**"Skill Freshness Comparison"**:
Resolved as comparing **Skill Directory Freshness Token** values for this feature, not recomputing strict **Skill Directory Revision** values on every turn.

**"Skill Freshness Token Scope"**:
Resolved as a stable digest of each tracked file's relative path, `mtime_ns`, and size across the skill directory tree, not just the root directory and `SKILL.md`.

**"Associated Skills To Monitor"**:
Resolved as the session's **Session Associated Skill Set** only. Skills that the session never associated with are outside the monitoring scope.

**"Associated Skill Persistence"**:
Resolved as persisting a **Session Skill Snapshot** in session state, not reconstructing it from tracing or other runtime records.

**"Skill Update Handling"**:
Resolved as **Skill Freshness Refresh** plus a model-only **Skill Freshness Notice**. The notice is visible to the model for one turn, but is not exposed to the Console stream or persisted into chat history.

**"When A Skill Becomes Associated"**:
Resolved as **Confirmed Skill Association** only. Low-confidence inference without actual activation must not expand the **Session Associated Skill Set**.

**"Associated Skill Disappeared"**:
Resolved as **Missing Associated Skill** with ignore semantics. If an associated skill no longer exists at next-turn freshness check time, Swe continues the turn, treats that absence as no effective skill change for the first version, and silently removes the stale snapshot entry.

**"When To Update The Session Skill Snapshot"**:
Resolved as writing an **Applied Skill Snapshot** immediately after freshness detection and notice injection for the current turn, rather than waiting for turn completion.

**"Where The Session Skill Snapshot Lives"**:
Resolved as a top-level **Session Skill Snapshot Record** in session state, parallel to `hook_overlay`, not nested under `agent`.

**"What A Session Skill Snapshot Entry Stores"**:
Resolved as at least `skill_name`, `resolved_skill_dir`, and `freshness_token`, not just the skill name alone.

**"When To Persist A Newly Associated Skill"**:
Resolved as **Immediate Skill Snapshot Capture**. A newly confirmed associated skill must be written to the top-level session snapshot immediately in the same turn.

**"Associated Skill Directory Changed"**:
Resolved as **Associated Skill Directory Switch**. If a session-associated skill name resolves to a different directory on a later turn, Swe must treat that as a real change, trigger refresh/notice, and overwrite the stored snapshot entry.

**"Associated Skill Lost Enabled/Effective Status"**:
Resolved as **Associated Skill Withdrawal**. If a session-associated skill is no longer effective for the current turn, Swe must treat that as a real change, trigger refresh/notice, and remove the stored snapshot entry.

**"Multiple Skill Changes In One Turn"**:
Resolved as a single **Aggregated Skill Freshness Notice** that lists each affected skill and its change type within the same turn.

**"Immediate Truncation Raw Configuration Display"**:
Resolved as exposing absence for **File Read Truncation** as inheriting the historical recent tool-result limit until independently configured.

**"Tool Output Controls Scope"**:
Resolved as limited to the Source System Configuration page and runtime resolution for this change. The Agent configuration page keeps the existing historical tool-result compaction controls for now.

**"System Self-Check"**:
Resolved as **System Runtime Diagnostic**. The existing lightweight health endpoint remains a liveness probe, while the scheduled `HEARTBEAT.md` run remains an Agent Heartbeat.

**"Health Endpoint"**:
Resolved as **Liveness Probe** when referring to `/api/health/health`. It is not a readiness check and does not report dependency availability.

**"output_len=0"**:
Resolved as **Empty Model Output** only when discussing a successful model call that returns no usable assistant content. Scheduled Run or stream-level `output_len=0` remains an execution symptom and must not be treated as the canonical model-call concept.

**"Thinking-Only Model Output"**:
Resolved as not being **Empty Model Output**. Reasoning content is usable model content even when no user-visible final text is present.

**"Empty Model Output Retry Count"**:
Resolved as a fixed single retry for each model call. This retry is independent from normal transient-error LLM retry settings and still applies when normal LLM retry is disabled.

**"Streaming Empty Model Output"**:
Resolved at the whole-stream boundary. An individual empty stream chunk does not trigger an **Empty Model Output** retry; a completed stream that produced no usable model content triggers one full model-call retry.

**"Exhausted Empty Model Output Retry"**:
Resolved as an explicit model-call failure. If the fixed single retry also returns **Empty Model Output**, Swe raises a diagnostic error instead of treating the call as successfully completed.

**"Flask Worker Usage"**:
Resolved as **Request Execution Load**. Swe does not run Flask or a multi-worker web-server pool; the diagnostic reports the load and responsiveness of the single-worker Uvicorn/FastAPI backend instead of tenant-level workload statistics or Supervisor process state.

**"Diagnostic Instance"**:
Resolved as a **Runtime Instance**, meaning one running Swe service container. It is distinct from the business-facing instance records used for user allocation.

**"Logging System"**:
Resolved as the **Application Log Output Pipeline** when discussing asynchronous logging output. It does not mean changing **Hook Telemetry Log Message** schema, business operation logs, tracing storage, or **Tool Output Frames**.

## Example Dialogue

Developer: "When Plan Mode starts, should we create a SubAgent?"

Domain Expert: "No. Plan Mode does not create a SubAgent by default; it is a special mode of the Main Agent. The Main Agent may still choose Plan Delegation explicitly when readonly delegation is available."

Developer: "Can the Main Agent decide to use Plan Mode by itself?"

Domain Expert: "It can suggest Plan Mode later, but this stage only enters Plan Mode after an Explicit Plan Entry."

Developer: "If the user enables the Plan Mode toggle, does it affect only the next message?"

Domain Expert: "No. It persists as the current Plan Mode State for that chat session until the user turns it off."

Developer: "Does Plan Mode freeze all writes until the user executes a plan?"

Domain Expert: "Yes. In Plan Mode, the Main Agent itself is permission-limited until planning is completed."

Developer: "Does executing a plan unlock write tools?"

Domain Expert: "`execute` accepts the persisted Proposed Plan and can move the chat back to normal execution, where the Main Agent regains its normal permissions."
