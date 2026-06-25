# sidebar-task-list Specification

## Purpose
Define the task and paginated chat-history sections shown in the chat sidebar, including their navigation and interaction behavior.

## Requirements

### Requirement: Task list section in sidebar
The sidebar SHALL display a "我的任务" section with a collapsible task list. The section header SHALL show the title "我的任务(N)" where N is the task count, along with a collapse/expand toggle icon. Task items SHALL be fetched from the cronjob API.

#### Scenario: Task section display
- **WHEN** the sidebar is visible and tasks exist
- **THEN** the "我的任务(N)" section is displayed with task items below

#### Scenario: Empty task list
- **WHEN** no tasks are configured
- **THEN** the "我的任务(0)" section is displayed with no items or an empty state message

### Requirement: Task item display
Each task item SHALL preserve its title, unread badge, selected state, paused/running state, latest completion metadata, next-run text, and available task actions in the sidebar list.

#### Scenario: Task with unread badge
- **WHEN** a task has unread updates
- **THEN** a red badge with the unread count is displayed with the task item

#### Scenario: Task state display
- **WHEN** a task is running, manually paused, or automatically paused
- **THEN** the corresponding state is displayed on that task item

#### Scenario: Task schedule metadata
- **WHEN** a task has next-run or latest completion metadata
- **THEN** that metadata remains available from the task item

### Requirement: Click task to trigger execution
Clicking an individual task from the sidebar SHALL preserve the existing task click behavior for the corresponding task, including resolving and opening the task chat/session target. Running a task immediately SHALL remain available through the task action menu.

#### Scenario: Click task item
- **WHEN** the user clicks an individual task item
- **THEN** the corresponding task target is opened using the existing task navigation behavior

#### Scenario: Run task action
- **WHEN** the user chooses the run action from a task item action menu
- **THEN** the corresponding cronjob run action is invoked through the existing task action handler

### Requirement: Task item edit action
The sidebar task action menu SHALL provide an edit action only for stopped task items that are disabled for scheduled execution. Selecting the edit action SHALL open a task edit modal for that task without triggering task navigation.

#### Scenario: Open task editor from sidebar action menu
- **WHEN** the user opens a stopped task item's action menu in "我的任务" and selects "编辑"
- **THEN** the system opens a task edit modal for that task
- **AND** the task item click navigation handler is not invoked

#### Scenario: Hide task editor while enabled
- **WHEN** a task is enabled for scheduled execution
- **THEN** its sidebar action menu does not offer the edit action

#### Scenario: Preserve existing task actions
- **WHEN** the edit action is added to a task item's action menu
- **THEN** existing stop, run, resume, and delete actions remain available according to the task's existing action eligibility
- **AND** destructive delete remains unavailable while the task is enabled for scheduled execution

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

### Requirement: History section in sidebar
The sidebar SHALL display a "历史记录" section with a collapsible normally rendered list below the task section. The Console SHALL initially request a bounded first page of chat history, SHALL append older pages when the user scrolls near the end of the loaded history, SHALL automatically continue when the loaded rows do not fill the scroll container, and SHALL NOT require the previous virtual-list implementation. The section count SHALL reflect the server-reported total while including newer local pending sessions. Each history item SHALL display a title (color #4F5060) and a timestamp (color #808191) in "YYYY-MM-DD HH:mm" format. Paginated list loading SHALL preserve existing chat navigation, message display, session identity, generating state, and chat operation behavior.

#### Scenario: History section displays the first page
- **WHEN** the sidebar becomes visible and historical chats exist
- **THEN** the Console requests and displays the first bounded page in newest-first order
- **AND** each visible item shows its title and formatted timestamp

#### Scenario: User scrolls to older history
- **WHEN** the current page reports that older chats remain and the user scrolls near the bottom of the loaded history
- **THEN** the Console requests the next page exactly once while that request is in flight
- **AND** appends unseen older chat rows after the already loaded rows
- **AND** preserves the user's current chat and existing scroll context

#### Scenario: First page does not fill the history container
- **WHEN** older chats remain but the loaded history is too short to create a scrollbar
- **THEN** the Console automatically requests another page until the container can scroll or no older chats remain

#### Scenario: Session state changes while an older page is loading
- **WHEN** a session is created, switched, or changes generating state while an older history page is in flight
- **THEN** the resolved page is merged with the latest session state instead of replacing those concurrent changes

#### Scenario: All history has been loaded
- **WHEN** the latest paginated response reports that no older chats remain
- **THEN** further bottom scrolling does not request another page

#### Scenario: Loading another page fails
- **WHEN** a request for an older history page fails
- **THEN** already loaded history remains visible and usable
- **AND** the user can retry loading the failed page
- **AND** ordinary scroll events do not repeatedly retry the failed request

#### Scenario: Collapsed history panel reaches the bottom
- **WHEN** the sidebar is collapsed, the history panel is open, and the user scrolls its history content near the bottom
- **THEN** the Console uses the same paginated state to request the next page exactly once
- **AND** it does not issue an unpaginated chat-list request

#### Scenario: History item click
- **WHEN** the user clicks a loaded history item
- **THEN** the corresponding chat session is loaded using the existing session navigation behavior
- **AND** its messages are displayed using the unchanged chat detail flow

#### Scenario: Direct URL targets a chat outside the first page
- **WHEN** the chat page opens with a valid chat ID that is not present in the currently loaded history pages
- **THEN** the Console loads that chat directly instead of creating an empty replacement session
- **AND** subsequent messages preserve the chat's existing logical `session_id`

#### Scenario: Pending chat resolves while history is paginated
- **WHEN** a temporary local chat resolves to a persisted chat ID while one or more history pages are loaded
- **THEN** the sidebar contains one logical row for that conversation
- **AND** chat navigation and follow-up submission use the same identities as before pagination

#### Scenario: Existing chat mutations update the paginated list
- **WHEN** a loaded chat is renamed or deleted
- **THEN** the visible history state reflects that operation without duplicating unrelated rows
- **AND** existing delete navigation and active-chat behavior remain unchanged
