## Why

Users can pause, run, resume, and delete scheduled tasks from the chat sidebar, but editing a task still requires leaving the conversation and finding the same task in Run Center. Adding edit access in "我的任务" keeps task maintenance in the workflow where users notice the task state.

## What Changes

- Add an edit action to each editable task item action menu in the chat sidebar "我的任务" section.
- Open a redesigned task edit modal from the chat sidebar action.
- Reuse the Run Center scheduled-task edit fields, validation, payload normalization, and cronjob update API behavior.
- Refresh the sidebar task list after a successful edit and preserve existing task navigation, pause, run, resume, and delete behavior.
- No breaking changes.

## Capabilities

### New Capabilities

### Modified Capabilities

- `sidebar-task-list`: Adds task editing from the chat sidebar task action menu.

## Impact

- Affected UI:
  - `console/src/pages/Chat/components/TaskActionMenu.tsx`
  - `console/src/pages/Chat/components/ChatTaskList/index.tsx`
  - `console/src/pages/Chat/index.tsx`
  - shared scheduled-task form/edit components under `console/src/pages/Control/CronJobs/`
- Affected API usage:
  - Reuses `PUT /cron/jobs/{id}` through `cronJobApi.replaceCronJob`.
  - Reuses existing cron job form helpers for field hydration and submit payload normalization.
- Design:
  - The new chat-side edit modal follows `console/DESIGN.md` and frontend-design guidance.
  - The Run Center scheduled-task page keeps its current Drawer presentation in this change.
