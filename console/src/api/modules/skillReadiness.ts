import { request } from "../request";
import type {
  SkillReadinessOverview,
  SkillReadinessResultsPage,
  SkillReadinessResultsQuery,
  SkillReadinessStartRunResponse,
} from "../types/skillReadiness";

function appendResultsQuery(
  url: string,
  query: SkillReadinessResultsQuery = {},
): string {
  const params = new URLSearchParams();
  if (query.page !== undefined) {
    params.set("page", String(query.page));
  }
  if (query.page_size !== undefined) {
    params.set("page_size", String(query.page_size));
  }
  if (query.status && query.status !== "all") {
    params.set("status", query.status);
  }
  if (query.check_name) {
    params.set("check_name", query.check_name);
  }
  if (query.check_status) {
    params.set("check_status", query.check_status);
  }
  const queryString = params.toString();
  return queryString ? `${url}?${queryString}` : url;
}

export const skillReadinessApi = {
  getSkillReadinessOverview: (
    skillId: string,
  ): Promise<SkillReadinessOverview> =>
    request<SkillReadinessOverview>(
      `/skill-readiness/skills/${encodeURIComponent(skillId)}/overview`,
    ),

  startSkillReadinessRun: (
    skillId: string,
  ): Promise<SkillReadinessStartRunResponse> =>
    request<SkillReadinessStartRunResponse>(
      `/skill-readiness/skills/${encodeURIComponent(skillId)}/runs`,
      { method: "POST" },
    ),

  getSkillReadinessResults: (
    runId: string,
    query: SkillReadinessResultsQuery = {},
  ): Promise<SkillReadinessResultsPage> =>
    request<SkillReadinessResultsPage>(
      appendResultsQuery(
        `/skill-readiness/runs/${encodeURIComponent(runId)}/results`,
        query,
      ),
    ),
};
