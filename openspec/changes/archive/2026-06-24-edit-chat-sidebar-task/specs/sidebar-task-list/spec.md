## ADDED Requirements

### Requirement: Task item edit action
The sidebar task action menu SHALL provide an edit action for task items that expose task operations. Selecting the edit action SHALL open a task edit modal for that task without triggering task navigation.

#### Scenario: Open task editor from sidebar action menu
- **WHEN** the user opens a task item's action menu in "我的任务" and selects "编辑"
- **THEN** the system opens a task edit modal for that task
- **AND** the task item click navigation handler is not invoked

#### Scenario: Preserve existing task actions
- **WHEN** the edit action is added to a task item's action menu
- **THEN** existing stop, run, resume, and delete actions remain available according to the task's existing action eligibility

### Requirement: Chat sidebar task edit modal behavior
The task edit modal opened from "我的任务" SHALL expose the same editable task content, validation, and submit semantics as Run Center scheduled-task editing. Saving SHALL update the existing cron job through the cronjob replace API and refresh the sidebar task list after a successful update.

#### Scenario: Modal uses existing task values
- **WHEN** the edit modal opens for a sidebar task
- **THEN** the form fields are populated from that task using the same value mapping as Run Center scheduled-task editing

#### Scenario: Save task edit
- **WHEN** the user changes valid task fields and saves
- **THEN** the system submits the normalized cron job payload to the existing cronjob update API for that task ID
- **AND** the sidebar task list is refreshed after the update succeeds
- **AND** the modal closes after the successful save

#### Scenario: Validation prevents invalid save
- **WHEN** the user enters invalid task data such as malformed request JSON or missing required fields
- **THEN** the system prevents submission and keeps the modal open with validation feedback

#### Scenario: Cancel task edit
- **WHEN** the user cancels or closes the task edit modal
- **THEN** the modal closes without updating the cron job

### Requirement: Chat task editor visual treatment
The task edit modal opened from "我的任务" SHALL follow `console/DESIGN.md` and frontend-design guidance for a light, operational Console overlay while preserving the existing Conversation Workspace emphasis color.

#### Scenario: Modal layout is usable at desktop sizes
- **WHEN** the modal is displayed at supported desktop viewport sizes
- **THEN** labels, fields, footer actions, long task IDs, and JSON input remain readable without incoherent overlap or page-level horizontal overflow

#### Scenario: Save state is visible
- **WHEN** the task edit save request is in progress
- **THEN** the save control displays an in-progress state and prevents duplicate submissions
