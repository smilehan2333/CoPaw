import { request } from "../request";
import { buildAuthHeaders } from "../authHeaders";
import { getApiUrl } from "../config";

// Types for Monitor Cron Overview

export interface FilterOption {
  value: string;
  label: string;
}

export interface FilterOptionsResponse {
  users: FilterOption[];
  bbk_ids: FilterOption[];
  channels: FilterOption[];
  source_ids: FilterOption[];
  job_names: FilterOption[];
  job_ids: FilterOption[];
}

export interface CronJobItem {
  id: string;
  name: string;
  tenant_id: string;
  tenant_name: string;
  bbk_id: string;
  source_id: string;
  enabled: boolean;
  task_type: string;
  cron_expr: string;
  timezone: string;
  channel: string;
  target_user_id: string;
  target_session_id: string;
  timeout_seconds: number;
  max_concurrency: number;
  misfire_grace_seconds: number;
  text_content: string;
  request_input: string;
  creator_user_id: string;
  task_chat_id: string;
  task_session_id: string;
  job_origin: string;
  subscription_key: string;
  meta: string;
  status: string;
  pause_reason: string;
  execution_count: number;
  today_status: string | null; // 今日最新执行状态: success/running/error/cancelled/timeout/skipped
  created_at: string | null;
  updated_at: string | null;
  deleted_at: string | null;
}

export interface ExecutionItem {
  id: number;
  job_id: string;
  job_name: string;
  tenant_id: string;
  tenant_name: string;
  bbk_id?: string;
  scheduled_time: string | null;
  actual_time: string;
  end_time: string | null;
  duration_ms: number;
  status: string;
  async_status?: string | null;
  error_message: string;
  instance_id: string;
  executor_leader: string;
  is_manual: boolean;
  trace_id: string;
  session_id: string;
  input_snapshot: string;
  output_preview: string;
  meta: string;
  is_read: boolean;
  read_at: string | null;
  created_at: string | null;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface MarkReadResponse {
  marked: boolean;
  count: number;
}

export interface UnreadCountItem {
  job_id: string;
  job_name: string;
  unread_count: number;
}

export interface UnreadCountResponse {
  items: UnreadCountItem[];
  total_unread: number;
}

export interface CronOverviewMetricItem {
  key: string;
  value: number;
  compare: string;
  trend: "up" | "down" | null;
}

export interface CronOverviewDistributionItem {
  name: string;
  value: number;
  percent: number;
}

export interface CronOverviewBranchExecutionItem {
  name: string;
  success: number;
  failed: number;
  skipped: number;
}

export interface CronOverviewBranchReadItem {
  name: string;
  read: number;
  unread: number;
}

export interface CronOverviewResponse {
  start_time: string | null;
  end_time: string | null;
  metrics: CronOverviewMetricItem[];
  task_status: CronOverviewDistributionItem[];
  execution_result: CronOverviewDistributionItem[];
  read_status: CronOverviewDistributionItem[];
  failure_reasons: CronOverviewDistributionItem[];
  branch_tasks: CronOverviewDistributionItem[];
  branch_execution: CronOverviewBranchExecutionItem[];
  branch_read: CronOverviewBranchReadItem[];
}

export interface CronJobOverviewSummaryMetric {
  key: string;
  value: string;
  footerValue?: string;
}

export interface CronJobOverviewBranchRankingRow {
  rank: number | "...";
  bbkId: string;
  branchName: string;
  skillCount: string;
  totalTasks: string;
  successCount: string;
  readTasks: string;
  involvedManagers: string;
  resultViewManagers: string;
  planManagers: string;
  insightManagers: string;
  phoneManagers: string;
  recommendedCustomers: string;
  viewedCustomers: string;
  insightCustomers: string;
  phoneCustomers: string;
}

export interface CronBranchTaskRankingItem {
  bbk_id: string;
  bbk_name: string;
  manager_count: number;
  total_tasks: number;
  success_count: number;
  success_rate: number;
  read_tasks: number;
  plan_count: number;
  insight_count: number;
  phone_count: number;
  plan_clicks: number;
  insight_clicks: number;
  phone_clicks: number;
  error_count: number;
}

export interface CronBranchTaskRankingResponse {
  start_date: string;
  end_date: string;
  items: CronBranchTaskRankingItem[];
}

export interface CronJobOverviewFailureReason {
  name: string;
  count: number;
  percent: number;
  color: string;
}

export interface CronJobOverviewAnomalySummary {
  affectedBranches: string;
  affectedBranchesUnit: string;
  affectedManagers: string;
  affectedManagersUnit: string;
}

export interface CronJobOverviewAnomalyRankRow {
  rank: number;
  branchName: string;
  alertExecutions: string;
  alertRate: string;
  affectedManagers: string;
  latestAlertTime: string;
}

export interface CronJobOverviewPageData {
  summaryMetrics: CronJobOverviewSummaryMetric[];
  branchRankingRows: CronJobOverviewBranchRankingRow[];
  failureReasons: CronJobOverviewFailureReason[];
  anomalySummary: CronJobOverviewAnomalySummary;
  anomalyRankRows: CronJobOverviewAnomalyRankRow[];
}

export interface CronJobOverviewDateFilters {
  start_date?: string;
  end_date?: string;
  bbk_ids?: string;
}

export interface CronOverviewStatsResponse {
  start_date: string;
  end_date: string;
  total_tasks: number;
  total_executions: number;
  branch_count: number;
  tenant_count: number;
  success_rate: number;
  success_count: number;
  running_count: number;
  read_tasks: number;
  read_rate: number;
  error_count: number;
  error_rate: number;
}

export interface CronBranchRankingItem {
  bbk_id: string;
  bbk_name: string;
  skill_count: number;
  total_tasks: number;
  success_count: number;
  read_tasks: number;
  involved_managers: number;
  result_view_managers: number;
  plan_managers: number;
  insight_managers: number;
  phone_managers: number;
  recommended_customers: number;
  viewed_customers: number;
  insight_customers: number;
  phone_customers: number;
}

export interface CronBranchRankingResponse {
  start_date: string;
  end_date: string;
  items: CronBranchRankingItem[];
}

export interface CronErrorReasonItem {
  reason: string;
  count: number;
  percent: number;
}

export interface CronBranchErrorRankItem {
  bbk_id: string;
  bbk_name: string;
  total_executions: number;
  error_count: number;
  error_rate: number;
  affected_managers: number;
}

export interface CronBranchErrorResponse {
  start_date: string;
  end_date: string;
  affected_branch_count: number;
  affected_manager_count: number;
  error_reasons: CronErrorReasonItem[];
  branch_error_rank: CronBranchErrorRankItem[];
}

export interface BranchSkillItem {
  skill_name: string;
  cron_task_count: number;
  success_count: number;
  success_rate: number;
  read_count: number;
  error_count: number;
}

export interface BranchSkillResponse {
  start_date: string;
  end_date: string;
  bbk_id: string;
  bbk_name: string;
  items: BranchSkillItem[];
}

export interface BranchManagerSummaryItem {
  user_id: string;
  user_name: string;
  skill_count: number;
  total_tasks: number;
  success_count: number;
  read_tasks: number;
  recommended_customers: number;
  viewed_customers: number;
  insight_customers: number;
  phone_customers: number;
}

export interface BranchManagerSummaryResponse {
  start_date: string;
  end_date: string;
  bbk_id: string;
  bbk_name: string;
  items: BranchManagerSummaryItem[];
}

export interface ManagerSkillItem {
  skill_name: string;
  cron_task_count: number;
  success_count: number;
  success_rate: number;
  read_count: number;
  error_count: number;
}

export interface ManagerSkillResponse {
  start_date: string;
  end_date: string;
  bbk_id: string;
  user_id: string;
  user_name: string;
  items: ManagerSkillItem[];
}

export interface ManagerCustomerItem {
  customer_id: string;
  customer_name: string;
  clicked_plan: boolean;
  clicked_insight: boolean;
  clicked_phone: boolean;
  click_time: string | null;
}

export interface ManagerCustomerResponse {
  start_date: string;
  end_date: string;
  bbk_id: string;
  user_id: string;
  user_name: string;
  items: ManagerCustomerItem[];
}

export interface BranchSkillManagerItem {
  user_id: string;
  user_name: string;
  read_count: number;
  plan_count: number;
  insight_count: number;
  phone_count: number;
  last_click_time: string | null;
}

export interface BranchSkillManagerResponse {
  start_date: string;
  end_date: string;
  bbk_id: string;
  skill_name: string;
  items: BranchSkillManagerItem[];
}

export interface BranchSkillManagerCustomerItem {
  customer_id: string;
  customer_name: string;
  clicked_plan: boolean;
  clicked_insight: boolean;
  clicked_phone: boolean;
  click_time: string | null;
}

export interface BranchSkillManagerCustomerResponse {
  start_date: string;
  end_date: string;
  bbk_id: string;
  skill_name: string;
  user_id: string;
  items: BranchSkillManagerCustomerItem[];
}

export interface SubscriptionOverviewItem {
  subscription_key: string;
  task_name: string;
  subscriber_count: number;
  total_task_count: number;
  running_task_count: number;
  pending_task_count: number;
  executed_task_count: number;
  failed_task_count: number;
  avg_duration_ms: number;
  success_rate: number;
}

export interface SubscriptionDetailItem {
  job_id: string;
  subscriber_id: string;
  subscriber_name: string;
  bbk_id: string;
  enabled: boolean;
  execution_status: string;
  execution_time: string | null;
}

const CRON_FAILURE_REASON_COLORS = ["#1d6ff2", "#38a8f5", "#7a8cf0", "#ff821c", "#67cdb9"];

function appendDefinedParams(
  params: URLSearchParams,
  filters?: object,
) {
  if (!filters) {
    return;
  }
  Object.entries(filters).forEach(([key, value]) => {
    if (typeof value === "string" && value !== "") {
      params.append(key, value);
    }
  });
}

function buildQuery(filters?: object) {
  const params = new URLSearchParams();
  appendDefinedParams(params, filters);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function formatInteger(value: number | null | undefined) {
  return Math.round(Number(value || 0)).toLocaleString("en-US");
}

function formatPercentValue(value: number | null | undefined) {
  return Number(value || 0).toFixed(2);
}

function formatPercentText(value: number | null | undefined) {
  return `${formatPercentValue(value)}%`;
}

function mapCronJobOverviewPageData(
  stats: CronOverviewStatsResponse,
  behavior: CronBranchRankingResponse,
  branchError: CronBranchErrorResponse,
): CronJobOverviewPageData {
  return {
    summaryMetrics: [
      { key: "branches", value: formatInteger(stats.branch_count) },
      { key: "managers", value: formatInteger(stats.tenant_count) },
      {
        key: "tasks",
        value: formatInteger(stats.total_tasks),
        footerValue: `${formatInteger(stats.total_executions)} 次`,
      },
      {
        key: "success",
        value: formatPercentValue(stats.success_rate),
        footerValue: formatInteger(stats.success_count),
      },
      {
        key: "read",
        value: formatPercentValue(stats.read_rate),
        footerValue: formatInteger(stats.read_tasks),
      },
      {
        key: "alert",
        value: formatPercentValue(stats.error_rate),
        footerValue: formatInteger(stats.error_count),
      },
    ],
    branchRankingRows: behavior.items.map((item, index) => ({
      rank: index + 1,
      bbkId: item.bbk_id || "",
      branchName: item.bbk_name || item.bbk_id || "-",
      skillCount: formatInteger(item.skill_count),
      totalTasks: formatInteger(item.total_tasks),
      successCount: formatInteger(item.success_count),
      readTasks: formatInteger(item.read_tasks),
      involvedManagers: formatInteger(item.involved_managers),
      resultViewManagers: formatInteger(item.result_view_managers),
      planManagers: formatInteger(item.plan_managers),
      insightManagers: formatInteger(item.insight_managers),
      phoneManagers: formatInteger(item.phone_managers),
      recommendedCustomers: formatInteger(item.recommended_customers),
      viewedCustomers: formatInteger(item.viewed_customers),
      insightCustomers: formatInteger(item.insight_customers),
      phoneCustomers: formatInteger(item.phone_customers),
    })),
    failureReasons: branchError.error_reasons.map((item, index) => ({
      name: item.reason || "其他",
      count: Number(item.count || 0),
      percent: Number(item.percent || 0),
      color: CRON_FAILURE_REASON_COLORS[index % CRON_FAILURE_REASON_COLORS.length],
    })),
    anomalySummary: {
      affectedBranches: formatInteger(branchError.affected_branch_count),
      affectedBranchesUnit: "家",
      affectedManagers: formatInteger(branchError.affected_manager_count),
      affectedManagersUnit: "人",
    },
    anomalyRankRows: branchError.branch_error_rank.map((item, index) => ({
      rank: index + 1,
      branchName: item.bbk_name || item.bbk_id || "-",
      alertExecutions: formatInteger(item.error_count),
      alertRate: formatPercentText(item.error_rate),
      affectedManagers: formatInteger(item.affected_managers),
      latestAlertTime: "",
    })),
  };
}

// API functions
export const monitorApi = {
  // Get filter options for dropdown selects
  getFilterOptions: async (): Promise<FilterOptionsResponse> => {
    return request(`/monitor/cron/filter-options`);
  },

  // Get page-shaped aggregate data for the cron overview
  getCronOverview: async (filters?: {
    tenant_id?: string;
    bbk_id?: string;
    start_time?: string;
    end_time?: string;
  }): Promise<CronOverviewResponse> => {
    const params = new URLSearchParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          params.append(key, value);
        }
      });
    }
    const query = params.toString();
    return request(`/monitor/cron/overview${query ? `?${query}` : ""}`);
  },

  getCronOverviewStats: async (
    filters?: CronJobOverviewDateFilters,
  ): Promise<CronOverviewStatsResponse> => {
    return request(`/monitor/cron/overview-stats${buildQuery(filters)}`);
  },

  getCronBranchRanking: async (
    filters?: CronJobOverviewDateFilters,
  ): Promise<CronBranchRankingResponse> => {
    return request(`/monitor/cron/branch-behavior${buildQuery(filters)}`);
  },

  getCronBranchTaskBehavior: async (
    filters?: CronJobOverviewDateFilters,
  ): Promise<CronBranchTaskRankingResponse> => {
    return request(`/monitor/cron/branch-task-behavior${buildQuery(filters)}`);
  },

  getCronBranchError: async (
    filters?: CronJobOverviewDateFilters,
  ): Promise<CronBranchErrorResponse> => {
    return request(`/monitor/cron/branch-error${buildQuery(filters)}`);
  },

  getBranchSkills: async (params: {
    bbk_id: string;
    start_date?: string;
    end_date?: string;
  }): Promise<BranchSkillResponse> => {
    return request(`/monitor/cron/branch-skills${buildQuery(params)}`);
  },

  getBranchManagerSummary: async (params: {
    bbk_id: string;
    start_date?: string;
    end_date?: string;
  }): Promise<BranchManagerSummaryResponse> => {
    return request(`/monitor/cron/branch-manager-summary${buildQuery(params)}`);
  },

  getManagerSkills: async (params: {
    bbk_id: string;
    user_id: string;
    start_date?: string;
    end_date?: string;
  }): Promise<ManagerSkillResponse> => {
    return request(`/monitor/cron/manager-skills${buildQuery(params)}`);
  },

  getManagerCustomers: async (params: {
    bbk_id: string;
    user_id: string;
    skill_name?: string;
    start_date?: string;
    end_date?: string;
  }): Promise<ManagerCustomerResponse> => {
    return request(`/monitor/cron/manager-customers${buildQuery(params)}`);
  },

  getBranchSkillManagers: async (params: {
    bbk_id: string;
    skill_name: string;
    start_date?: string;
    end_date?: string;
  }): Promise<BranchSkillManagerResponse> => {
    return request(`/monitor/cron/branch-skill-managers${buildQuery(params)}`);
  },

  getBranchSkillManagerCustomers: async (params: {
    bbk_id: string;
    skill_name: string;
    user_id: string;
    start_date?: string;
    end_date?: string;
  }): Promise<BranchSkillManagerCustomerResponse> => {
    return request(
      `/monitor/cron/branch-skill-manager-customers${buildQuery(params)}`,
    );
  },

  getCronJobOverviewPageData: async (
    filters?: CronJobOverviewDateFilters,
  ): Promise<CronJobOverviewPageData> => {
    const [stats, ranking, branchError] = await Promise.all([
      monitorApi.getCronOverviewStats(filters),
      monitorApi.getCronBranchRanking(filters),
      monitorApi.getCronBranchError(filters),
    ]);
    return mapCronJobOverviewPageData(stats, ranking, branchError);
  },

  // Get cron jobs list
  getJobs: async (
    page = 1,
    pageSize = 20,
    filters?: {
      tenant_id?: string;
      bbk_id?: string;
      creator_user_id?: string;
      job_origin?: string;
      status?: string;
      enabled?: boolean;
    },
  ): Promise<PaginatedResponse<CronJobItem>> => {
    const params = new URLSearchParams();
    params.append("page", page.toString());
    params.append("page_size", pageSize.toString());
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "" && value !== "all") {
          params.append(key, value.toString());
        }
      });
    }
    return request(`/monitor/cron/jobs?${params.toString()}`);
  },

  // Get single job
  getJob: async (jobId: string): Promise<CronJobItem> => {
    return request(`/monitor/cron/jobs/${jobId}`);
  },

  // Get executions list
  getExecutions: async (
    page = 1,
    pageSize = 20,
    filters?: {
      job_id?: string;
      tenant_id?: string;
      bbk_id?: string;
      status?: string;
      start_time?: string;
      end_time?: string;
    },
  ): Promise<PaginatedResponse<ExecutionItem>> => {
    const params = new URLSearchParams();
    params.append("page", page.toString());
    params.append("page_size", pageSize.toString());
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          params.append(key, value);
        }
      });
    }
    return request(`/monitor/cron/executions?${params.toString()}`);
  },

  // Get single execution
  getExecution: async (executionId: number): Promise<ExecutionItem> => {
    return request(`/monitor/cron/executions/${executionId}`);
  },

  // Get subscription-level overview rows
  getSubscriptionOverview: async (
    page = 1,
    pageSize = 20,
    filters?: {
      keyword?: string;
      tenant_id?: string;
      bbk_id?: string;
      source_id?: string;
      start_time?: string;
      end_time?: string;
    },
  ): Promise<PaginatedResponse<SubscriptionOverviewItem>> => {
    const params = new URLSearchParams();
    params.append("page", page.toString());
    params.append("page_size", pageSize.toString());
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          params.append(key, value);
        }
      });
    }
    return request(`/monitor/cron/subscription-overview?${params.toString()}`);
  },

  // Get subscription detail rows for a drawer/table
  getSubscriptionDetails: async (
    subscriptionKey: string,
    page = 1,
    pageSize = 20,
    filters?: {
      tenant_id?: string;
      bbk_id?: string;
      source_id?: string;
      start_time?: string;
      end_time?: string;
    },
  ): Promise<PaginatedResponse<SubscriptionDetailItem>> => {
    const params = new URLSearchParams();
    params.append("page", page.toString());
    params.append("page_size", pageSize.toString());
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          params.append(key, value);
        }
      });
    }
    return request(
      `/monitor/cron/subscription-overview/${encodeURIComponent(
        subscriptionKey,
      )}/jobs?${params.toString()}`,
    );
  },

  // Export jobs to Excel
  exportJobs: async (
    filters?: {
      tenant_id?: string;
      bbk_id?: string;
      enabled?: boolean;
    },
  ): Promise<Blob> => {
    const params = new URLSearchParams();
    params.append("export_type", "jobs");
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null) params.append(key, value.toString());
      });
    }
    const url = getApiUrl(`/monitor/cron/export?${params.toString()}`);
    const headers = new Headers(buildAuthHeaders());
    const response = await fetch(url, { headers });
    if (!response.ok) {
      let errorMessage = `Export failed: ${response.status} ${response.statusText}`;
      try {
        const errorData = await response.json();
        if (errorData.detail) {
          errorMessage = errorData.detail;
        }
      } catch {
        // Ignore JSON parse error
      }
      throw new Error(errorMessage);
    }
    return response.blob();
  },

  // Export executions to Excel
  exportExecutions: async (
    filters?: {
      job_id?: string;
      tenant_id?: string;
      status?: string;
      start_time?: string;
      end_time?: string;
    },
  ): Promise<Blob> => {
    const params = new URLSearchParams();
    params.append("export_type", "executions");
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value) params.append(key, value);
      });
    }
    const url = getApiUrl(`/monitor/cron/export?${params.toString()}`);
    const headers = new Headers(buildAuthHeaders());
    const response = await fetch(url, { headers });
    if (!response.ok) {
      let errorMessage = `Export failed: ${response.status} ${response.statusText}`;
      try {
        const errorData = await response.json();
        if (errorData.detail) {
          errorMessage = errorData.detail;
        }
      } catch {
        // Ignore JSON parse error
      }
      throw new Error(errorMessage);
    }
    return response.blob();
  },

  // Mark job as read
  markJobAsRead: async (jobId: string): Promise<MarkReadResponse> => {
    return request(`/monitor/cron/jobs/${jobId}/mark-read`, { method: "POST" });
  },

  // Get unread count
  getUnreadCount: async (tenantId?: string): Promise<UnreadCountResponse> => {
    const params = new URLSearchParams();
    if (tenantId) {
      params.append("tenant_id", tenantId);
    }
    return request(`/monitor/cron/unread-count?${params.toString()}`);
  },
};
