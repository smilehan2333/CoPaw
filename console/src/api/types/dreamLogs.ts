// Dream logs API types

export interface FileStats {
  size_before: number;
  size_after: number;
  size_saved: number;
  lines_before: number;
  lines_after: number;
  lines_removed: number;
  backup_path: string;
}

export interface DreamLogRecord {
  id: string;
  timestamp: string;
  trigger: "cron" | "manual";
  status: "success" | "failed" | "rollback";
  files_optimized: string[];
  file_stats: Record<string, FileStats>;
  total_size_saved: number;
  total_files_changed: number;
  duration_ms: number;
  model_used: string;
  input_tokens: number;
  output_tokens: number;
  summary: string;
  error?: string;
}

export interface DreamLogsStats {
  total_executions: number;
  success_count: number;
  failed_count: number;
  total_size_saved: number;
  total_files_changed: number;
  avg_duration_ms: number;
  last_execution?: string;
}

export interface DreamLogsResponse {
  records: DreamLogRecord[];
  stats: DreamLogsStats;
  total: number;
  page: number;
  page_size: number;
}

export interface DreamLogReportParams {
  start_time?: string;
  end_time?: string;
  bbk_id?: string;
  user_search?: string;
  status?: string;
  trigger?: string;
  agent_id?: string;
  page?: number;
  page_size?: number;
}

export interface DreamLogReportSummary {
  covered_users: number;
  governed_users: number;
  ungoverned_users: number;
  total_executions: number;
  success_count: number;
  failed_count: number;
  success_rate: number;
  total_files_changed: number;
  total_size_saved: number;
  avg_duration_ms: number;
  last_execution?: string | null;
}

export interface DreamLogReportTrendPoint {
  date: string;
  executions: number;
  manual_count?: number;
  cron_count?: number;
  success_count: number;
  failed_count: number;
  total_size_saved: number;
}

export interface DreamLogReportStatusBucket {
  status: string;
  count: number;
}

export interface DreamLogReportBbkBucket {
  bbk_id: string;
  user_count: number;
  governed_users: number;
  executions: number;
  success_rate: number;
}

export interface DreamLogReportUserRow {
  user_id: string;
  user_name?: string | null;
  bbk_id?: string | null;
  agents: string[];
  executions: number;
  success_rate: number;
  failed_count: number;
  total_files_changed: number;
  total_size_saved: number;
  last_execution?: string | null;
  latest_error?: string | null;
}

export interface DreamLogReportRecord {
  id: string;
  timestamp: string;
  trigger: string;
  status: string;
  agent_id: string;
  files_optimized: string[];
  total_size_saved: number;
  total_files_changed: number;
  duration_ms: number;
  model_used: string;
  input_tokens: number;
  output_tokens: number;
  summary: string;
  error?: string | null;
}

export interface ReconcileHealthInfo {
  source_id: string;
  target_user_id: string;
  target_agent_id: string;
  entity_type: string;
  entity_id: string;
  status: string;
  reason: string;
  error?: string | null;
  payload?: Record<string, unknown>;
  updated_at?: string | null;
}

export interface DreamLogReportResponse {
  summary: DreamLogReportSummary;
  trends: DreamLogReportTrendPoint[];
  status_distribution: DreamLogReportStatusBucket[];
  bbk_distribution: DreamLogReportBbkBucket[];
  users: DreamLogReportUserRow[];
  health: ReconcileHealthInfo[];
  total: number;
  page: number;
  page_size: number;
}

export interface DreamLogUserRecordsResponse {
  records: DreamLogReportRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface DiffResponse {
  filename: string;
  content_before: string;
  content_after: string;
  size_before: number;
  size_after: number;
  size_saved: number;
}

export interface TriggerResponse {
  success: boolean;
  message: string;
  record_id?: string;
}

export interface RollbackResponse {
  success: boolean;
  message: string;
  files_rolled_back: string[];
}

// Backup types
export interface BackupFileInfo {
  filename: string;
  original_file: string;
  record_id: string;
  timestamp: string;
  size: number;
  created_at: string;
}

export interface BackupListResponse {
  files: BackupFileInfo[];
  total_size: number;
  total_files: number;
}

export interface DeleteBackupResponse {
  success: boolean;
  message: string;
  files_deleted: string[];
}

export interface BackupContentResponse {
  filename: string;
  content: string;
  size: number;
  original_file: string;
}

// Orphan files types
export interface OrphanFileInfo {
  filename: string;
  size: number;
  created_at: string;
  modified_at: string;
  path: string;
  full_path: string;
}

export interface OrphanFilesResponse {
  files: OrphanFileInfo[];
  total_size: number;
  total_files: number;
  workspace_dir: string;
}

export interface OrphanFileContentResponse {
  filename: string;
  content: string;
  size: number;
  file_type: "text" | "image" | "binary" | "error";
  is_loadable: boolean;
  error_message?: string;
}

// 持续治理运行状态
export interface GovernanceStatusResponse {
  running: boolean;
  started_at?: string;
  trigger?: "cron" | "manual";
}

export interface ArchiveItem {
  id: string;
  original_path: string;
  archive_path: string;
  size_bytes: number;
  mtime: string;
  archived_at: string;
  archived_by: string;
  archive_reason: string;
  target_user_id?: string | null;
  target_agent_id?: string | null;
  expired: boolean;
}

export interface ArchiveOperationResponse {
  success: boolean;
  message: string;
  files_archived: string[];
  items: ArchiveItem[];
}

export interface ArchiveItemsResponse {
  items: ArchiveItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ArchiveRestoreRequest {
  archive_item_id: string;
  target_user_id: string;
  target_agent_id?: string;
  protect_after_restore?: boolean;
}

export interface ArchiveRestoreResponse {
  success: boolean;
  message: string;
  restored_path: string;
  protected: boolean;
}

export interface ArchivePurgeResponse {
  success: boolean;
  message: string;
  files_deleted: string[];
  files_count: number;
  total_size_bytes: number;
  audit_event_id: string;
}

export interface ProtectedFileInfo {
  target_user_id: string;
  target_agent_id: string;
  path: string;
  protected_at: string;
  protected_by: string;
  reason: string;
  exists: boolean;
  size_bytes?: number | null;
  mtime?: string | null;
}

export interface ProtectedFilesResponse {
  items: ProtectedFileInfo[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProtectedFileRemoveRequest {
  target_user_id: string;
  target_agent_id?: string;
  path: string;
}

export interface ProtectedFileRemoveResponse {
  success: boolean;
  message: string;
  removed_path: string;
}

export interface ArchiveAdminAuditRecord {
  event_id: string;
  timestamp: string;
  operation: string;
  status: string;
  actor_user_id: string;
  actor_role: string;
  source_id: string;
  source_name?: string | null;
  target_user_id: string;
  target_agent_id: string;
  scope: string;
  files_count: number;
  total_size_bytes: number;
  reason: string;
  error?: string | null;
}

export interface ArchiveAdminAuditSummary {
  total_operations: number;
  success_operations: number;
  failed_operations: number;
  partial_success_operations: number;
  manual_operations: number;
  auto_operations: number;
  total_files_cleared: number;
  total_size_cleared_bytes: number;
  last_operation_at?: string | null;
}

export interface ArchiveAdminAuditsResponse {
  summary: ArchiveAdminAuditSummary;
  items: ArchiveAdminAuditRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface ArchiveReportSummary {
  archived_files: number;
  archived_size_bytes: number;
  pending_purge_files: number;
  pending_purge_size_bytes: number;
  protected_files: number;
  protected_existing_files: number;
  protected_missing_files: number;
  purge_operations: number;
  purge_success_operations: number;
  purge_failed_operations: number;
  purged_files: number;
  purged_size_bytes: number;
  last_purge_at?: string | null;
}

export interface ArchiveReportResponse {
  summary: ArchiveReportSummary;
  health: ReconcileHealthInfo[];
}
