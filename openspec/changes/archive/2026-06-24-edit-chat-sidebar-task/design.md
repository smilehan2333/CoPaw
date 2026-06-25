## Context

The chat sidebar "我的任务" list is rendered by `ChatTaskList` and uses `TaskActionMenu` for task operations. `Chat/index.tsx` owns task fetching and the existing pause, run, resume, and delete handlers. Run Center scheduled-task editing already has the authoritative field set, validation, form hydration, and payload normalization in the CronJobs page, `JobDrawer`, and `helpers`.

The repository design rules require changed Console UI to follow `console/DESIGN.md`. This change touches the Conversation Workspace task list and introduces a new overlay, so the overlay should be redesigned deliberately while preserving the existing Conversation Workspace emphasis color and task-sidebar behavior.

## Goals / Non-Goals

**Goals:**

- Add an edit action to the chat sidebar task action menu.
- Let users edit the same task properties exposed by Run Center scheduled-task editing.
- Submit edits through the same cronjob update API contract and payload normalization as Run Center.
- Present the chat-side editor as a polished modal aligned with frontend-design and `console/DESIGN.md`.
- Keep the change scoped to the chat-side edit workflow plus any shared form extraction needed to avoid duplicate logic.

**Non-Goals:**

- Redesign the Run Center scheduled-task page or its existing Drawer.
- Change cronjob API routes, request shapes, server behavior, permissions, or task execution semantics.
- Add new task fields beyond the existing Run Center scheduled-task edit surface.
- Change the global Conversation Workspace visual system outside the new modal and edit menu item.

## Decisions

1. **Reuse the Run Center edit form logic through a shared form component.**
   - Rationale: The edit field set and payload semantics must remain consistent with Run Center.
   - Alternative considered: Copy `JobDrawer` form fields into chat. That would be faster initially but risks field drift and duplicate validation.

2. **Use a chat-side Modal, not the existing Run Center Drawer.**
   - Rationale: The user requested a popup/modal and a redesigned style for this entry point. A modal keeps the edit task focused without visually importing the older Run Center Drawer treatment into the Conversation Workspace.
   - Alternative considered: Reuse `JobDrawer` directly. That would preserve behavior but would not satisfy the redesigned popup requirement and would carry old page-level styling into chat.

3. **Keep Run Center UI unchanged while extracting shared internals.**
   - Rationale: The accepted scope is chat-side editing. Changing the Run Center visual surface would expand verification and risk without being required.
   - Alternative considered: Redesign both Run Center and chat editors together. That is broader and should be a separate UI migration.

4. **Save through `cronJobApi.replaceCronJob` and refresh task data after success.**
   - Rationale: Existing handlers refresh jobs after mutations, and the sidebar should reflect updated name, schedule, enabled state, next-run metadata, and pause state from the server.
   - Alternative considered: Optimistically patch every edited field locally. That is more fragile because server-side schedule/state normalization can affect displayed metadata.

## Risks / Trade-offs

- Shared form extraction could accidentally alter Run Center behavior -> keep extraction mechanical, preserve existing props and tests, and verify Run Center edit tests/build.
- The form has many fields for a modal -> use a wide, scrollable, dense Modal with clear sections and a sticky footer rather than hiding fields or changing the API contract.
- Editing a selected/current task could update its display while a conversation is open -> refresh jobs after success and preserve existing task navigation/session behavior.
- Long IDs, JSON input, model labels, and Chinese labels could overflow -> apply explicit wrapping/truncation and modal body scroll constraints per `console/DESIGN.md`.
