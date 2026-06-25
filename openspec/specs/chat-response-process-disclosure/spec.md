# chat-response-process-disclosure Specification

## Purpose
Define how completed Conversation Workspace assistant responses summarize and disclose process content while keeping final answers directly visible.

## Requirements
### Requirement: Completed responses disclose process content by default
The Conversation Workspace SHALL group completed assistant response process content into a manual disclosure while leaving final answer content visible by default.

#### Scenario: Completed response with process and final answer
- **WHEN** the main chat page renders a completed assistant runtime response that contains process content followed by final answer content
- **THEN** the process content is collapsed behind a visible disclosure control by default
- **AND** the final answer content remains directly visible without requiring the disclosure to be opened

#### Scenario: Completed response with history-loaded process and final answer
- **WHEN** the main chat page loads a historical completed assistant runtime response that contains process content and final answer content
- **THEN** the process content is collapsed behind a visible disclosure control by default
- **AND** the final answer content remains directly visible

### Requirement: Process disclosure preserves manual access
The Conversation Workspace SHALL allow users to manually expand and collapse grouped process content for the currently mounted page.

#### Scenario: User expands process disclosure
- **WHEN** a user activates the process disclosure control for a completed assistant response
- **THEN** the previously grouped process content is shown in place above the final answer
- **AND** the disclosure control indicates the expanded state

#### Scenario: User collapses expanded process disclosure
- **WHEN** a user activates an expanded process disclosure control
- **THEN** the grouped process content is hidden again
- **AND** the final answer remains visible

#### Scenario: Toggle state is local
- **WHEN** a user expands a completed response process disclosure and then reloads or remounts the chat page
- **THEN** the response follows the default completed-response disclosure state
- **AND** no backend or persisted user setting is required to remember the previous expanded state

### Requirement: Active and actionable states remain visible
The Conversation Workspace SHALL keep active or user-actionable response states directly visible instead of hiding them as completed process history.

#### Scenario: Response is still generating
- **WHEN** the main chat page renders an assistant runtime response that is still generating or contains running process content
- **THEN** the active process content remains visible or expanded by default
- **AND** the UI does not require the user to open a completed-process disclosure to see current progress

#### Scenario: Response waits for approval
- **WHEN** an assistant runtime response contains an approval request that requires user action
- **THEN** the approval request remains directly visible
- **AND** the approval request is not hidden inside the completed-process disclosure

#### Scenario: Error response has no final answer
- **WHEN** an assistant runtime response fails or contains an error and has no final answer content
- **THEN** the error remains directly visible
- **AND** the error is not hidden inside the completed-process disclosure

### Requirement: Failed process is summarized when an answer exists
The Conversation Workspace SHALL keep completed failed process details recoverable while making their presence visible in the collapsed disclosure row when a final answer exists.

#### Scenario: Completed response has final answer and failed process
- **WHEN** a completed assistant response contains final answer content and one or more failed process items
- **THEN** the final answer remains directly visible
- **AND** the process disclosure label indicates that failed process content exists
- **AND** opening the disclosure shows the failed process details

### Requirement: Final answer fallback remains visible
The Conversation Workspace SHALL preserve existing final-answer fallback behavior for completed responses whose trailing answer text is represented as reasoning.

#### Scenario: Trailing reasoning is used as fallback answer
- **WHEN** the response fallback logic identifies trailing reasoning text as the completed answer body
- **THEN** that fallback answer text remains directly visible outside the process disclosure
- **AND** it is not hidden solely because its source message type is reasoning

### Requirement: Process disclosure summary reflects available process metadata
The Conversation Workspace SHALL summarize folded process content using metadata that can be derived from the rendered response without requiring backend contract changes.

#### Scenario: Process summary shows step count
- **WHEN** process content is grouped into a disclosure
- **THEN** the disclosure summary indicates the number of grouped process steps

#### Scenario: Process summary shows tool call count
- **WHEN** grouped process content contains one or more visible tool-call rows
- **THEN** the disclosure summary indicates the number of visible tool calls
- **AND** tools intentionally hidden from the process view are not counted

#### Scenario: Process summary shows duration from message timestamps
- **WHEN** the response contains at least two messages with parseable message-level timestamps
- **THEN** the disclosure summary indicates the elapsed time between the first and last parseable message timestamp
- **AND** sub-second elapsed time is shown as less than one second

#### Scenario: Process summary omits unreliable duration
- **WHEN** fewer than two parseable message-level timestamps are available
- **THEN** the disclosure summary does not show total duration
- **AND** response-level timestamps are not used as a fallback for this summary duration

### Requirement: Disclosure control follows Conversation Workspace UI rules
The process disclosure control SHALL be compact, keyboard-accessible, and consistent with the Conversation Workspace visual hierarchy.

#### Scenario: Disclosure control renders
- **WHEN** a process disclosure control is shown
- **THEN** it has a visible expand or collapse affordance
- **AND** it communicates its expanded state to assistive technology
- **AND** hover and focus states do not shift surrounding layout

#### Scenario: User prefers reduced motion
- **WHEN** the user environment requests reduced motion
- **THEN** process disclosure expansion and collapse avoid non-essential motion
