## 1. Shared Task Edit Form

- [x] 1.1 Run GitNexus impact analysis for symbols that will be edited.
- [x] 1.2 Extract the Run Center scheduled-task form fields from `JobDrawer` into a shared form body component without changing field names or validation behavior.
- [x] 1.3 Keep `JobDrawer` using the shared form body so the Run Center edit/create flow remains behaviorally unchanged.
- [x] 1.4 Preserve `buildCronJobFormValues`, `buildCronJobSubmitPayload`, execution model options, notification delay, skill ID, and JSON validation semantics.

## 2. Chat Sidebar Edit Flow

- [x] 2.1 Add an edit action to `TaskActionMenu` with a clear icon, label, description, and event propagation handling.
- [x] 2.2 Thread `onTaskEdit` from `Chat/index.tsx` through `ChatTaskList` into `TaskActionMenu`.
- [x] 2.3 Add chat-page state for the editing task, form instance, saving state, and modal open/close behavior.
- [x] 2.4 On save, normalize values through the shared CronJobs helper, call `cronJobApi.replaceCronJob`, show success/error feedback, close on success, and refresh jobs.

## 3. Redesigned Modal UI

- [x] 3.1 Build a chat-side task edit modal using the shared form body and a frontend-design treatment aligned with `console/DESIGN.md`.
- [x] 3.2 Provide stable modal dimensions, scroll behavior, visible labels, keyboard/focus behavior, loading state, and footer actions.
- [x] 3.3 Ensure long task IDs, Chinese task names, JSON input, model labels, and compact desktop widths do not overlap or create page-level horizontal overflow.

## 4. Tests And Verification

- [x] 4.1 Update `ChatTaskList` tests to cover the edit menu action and confirm it does not trigger task item navigation.
- [x] 4.2 Add or update chat edit-flow tests for opening the modal, submitting through `replaceCronJob`, validation failure, and refresh-on-success behavior where practical.
- [x] 4.3 Run relevant frontend tests for Chat task list and CronJobs helpers/components.
- [x] 4.4 Run frontend lint/type/build checks required by the repository for this Console change.
- [x] 4.5 Perform UI verification at 1280x720, 1440x900, and 1920x1080; embedded `hideMenu=true` verification was blocked by the Playwright usage limit.
- [x] 4.6 Run GitNexus `detect_changes()` before any commit or final handoff.
