import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import type { CronJobSpecOutput } from "@/api/types";
import {
  createColumns,
  getBroadcastParentInfo,
  isBroadcastChildJob,
} from "./columns";

function buildCronJob(
  overrides: Partial<CronJobSpecOutput> = {},
): CronJobSpecOutput {
  return {
    id: "job-1",
    name: "test job",
    enabled: true,
    schedule: {
      type: "cron",
      cron: "0 9 * * *",
      timezone: "UTC",
    },
    task_type: "agent",
    request: {
      input: [{ role: "user", content: [{ type: "text", text: "hello" }] }],
      session_id: "session-1",
      user_id: "user-1",
    },
    dispatch: {
      type: "channel",
      channel: "console",
      target: {
        user_id: "user-1",
        session_id: "session-1",
      },
      mode: "final",
    },
    runtime: {
      max_concurrency: 1,
    },
    meta: {},
    ...overrides,
  };
}

function buildHandlers(overrides = {}) {
  return {
    onToggleEnabled: vi.fn(),
    onExecuteNow: vi.fn(),
    onBroadcast: vi.fn(),
    onManageChildren: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onCopySuccess: vi.fn(),
    onCopyError: vi.fn(),
    executionModelOptions: [],
    tenantDefaultModelLabel: "Tenant default",
    t: ((key: string) => key) as any,
    ...overrides,
  };
}

describe("CronJobs columns", () => {
  it("displays notification delay", () => {
    const columns = createColumns(buildHandlers());
    const column = columns.find((item) => item.key === "notification_delay");
    const job = buildCronJob({
      meta: {
        notification_delay_minutes: 120,
      },
    });

    expect(column?.render?.(undefined, job, 0)).toBe("2 小时");
  });

  it("extracts broadcast parent information from child task metadata", () => {
    const job = buildCronJob({
      meta: {
        broadcast_source_job_id: "parent-job",
        broadcast_source_job_name: "Parent Task",
        broadcast_source_tenant_id: "tenant-parent",
        broadcast_source_tenant_name: "Parent User",
        broadcast_source_bbk_id: "BBK001",
      },
    });

    expect(isBroadcastChildJob(job)).toBe(true);
    expect(getBroadcastParentInfo(job)).toEqual({
      sourceJobId: "parent-job",
      sourceJobName: "Parent Task",
      sourceTenantId: "tenant-parent",
      sourceTenantName: "Parent User",
      sourceBbkId: "BBK001",
    });
  });

  it("marks broadcast child tasks in the name column", () => {
    const columns = createColumns(buildHandlers());
    const column = columns.find((item) => item.key === "name");
    const job = buildCronJob({
      meta: {
        broadcast_source_job_id: "parent-job",
      },
    });

    render(<>{column?.render?.(undefined, job, 0)}</>);

    expect(screen.getByText("test job")).toBeTruthy();
    expect(screen.getByText("分发子任务")).toBeTruthy();
  });

  it("disables broadcast actions for broadcast child tasks", () => {
    const columns = createColumns(buildHandlers());
    const column = columns.find((item) => item.key === "action");
    const job = buildCronJob({
      meta: {
        broadcast_source_job_id: "parent-job",
      },
    });

    const actionNode = column?.render?.(
      undefined,
      job,
      0,
    ) as ReactElement<{ children: ReactElement[] }>;
    const children = actionNode.props.children;
    const dropdown = children[2] as ReactElement<{
      menu: { items: Array<{ disabled?: boolean }> };
    }>;

    expect(dropdown.props.menu.items[0].disabled).toBe(true);
    expect(dropdown.props.menu.items[1].disabled).toBe(true);
  });
});
