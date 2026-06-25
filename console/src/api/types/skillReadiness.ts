export type SkillReadinessRunStatus =
  | "running"
  | "completed"
  | "partial"
  | "failed";

export type SkillReadinessAggregateStatus = "normal" | "abnormal";

export type SkillReadinessCheckStatus = "pass" | "fail" | "skip";

export type SkillReadinessOwnerLookupStatus =
  | "idle"
  | "running"
  | "completed"
  | "failed";

export interface SkillReadinessConfigCheckSummary {
  name: string;
  display_name: string;
  enabled: boolean;
  params?: Record<string, unknown>;
}

export interface SkillReadinessOwnerSummary {
  total_users: number;
  lookup_failed_users: number;
  failure_summary: string | null;
}

export interface SkillReadinessOwner {
  user_id: string;
  user_name: string | null;
  bbk_id: string | null;
  skill_name?: string | null;
  market_version?: string | null;
  installed_version?: string | null;
  received_version?: string | null;
  enabled?: boolean | null;
  has_update?: boolean | null;
}

export interface SkillReadinessRunProgress {
  run_id: string;
  source_id: string;
  skill_id: string;
  status: SkillReadinessRunStatus;
  total_users: number;
  completed_users: number;
  failed_users: number;
  failure_summary: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
}

export interface SkillReadinessCheckSummary {
  check_name: string;
  display_name: string;
  total: number;
  pass_count: number;
  fail_count: number;
  skip_count: number;
}

export interface SkillReadinessRunSummary extends SkillReadinessRunProgress {
  check_summaries: SkillReadinessCheckSummary[];
}

export interface SkillReadinessOverview {
  skill_id: string;
  config_found: boolean;
  startable: boolean;
  config_message: string;
  config_checks: SkillReadinessConfigCheckSummary[];
  owner_summary: SkillReadinessOwnerSummary;
  owners: SkillReadinessOwner[];
  owner_lookup_status: SkillReadinessOwnerLookupStatus;
  owner_lookup_updated_at: string | null;
  latest_run: SkillReadinessRunSummary | null;
}

export interface SkillReadinessStartRunResponse {
  run: SkillReadinessRunProgress | null;
  reused: boolean;
  owner_lookup_only?: boolean;
  owner_lookup_scheduled?: boolean;
}

export interface SkillReadinessCheckResult {
  check_name: string;
  display_name: string;
  status: SkillReadinessCheckStatus;
  message: string;
  details: Record<string, unknown>;
  duration_ms: number;
}

export interface SkillReadinessUserResult {
  user_id: string;
  user_name: string | null;
  bbk_id: string | null;
  aggregate_status: SkillReadinessAggregateStatus;
  summary: string;
  duration_ms: number;
  checks: SkillReadinessCheckResult[];
}

export interface SkillReadinessResultsPage {
  run: SkillReadinessRunProgress;
  items: SkillReadinessUserResult[];
  total: number;
  page: number;
  page_size: number;
}

export interface SkillReadinessResultsQuery {
  page?: number;
  page_size?: number;
  status?: "all" | SkillReadinessAggregateStatus;
  check_name?: string;
  check_status?: "fail";
}
