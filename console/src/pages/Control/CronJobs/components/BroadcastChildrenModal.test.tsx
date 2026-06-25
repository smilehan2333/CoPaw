import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CronJobSpecOutput } from "@/api/types";
import { BroadcastChildrenModal } from "./BroadcastChildrenModal";

const mocks = vi.hoisted(() => ({
  listCronBroadcastChildren: vi.fn(),
  refreshCronBroadcastChildren: vi.fn(),
  deleteCronBroadcastChildren: vi.fn(),
  runCronBroadcastChildren: vi.fn(),
}));

vi.mock("../../../../api", () => ({
  default: mocks,
}));

function buildJob(): CronJobSpecOutput {
  return {
    id: "job-source",
    name: "ark",
    enabled: true,
    schedule: {
      type: "cron",
      cron: "0 5 * * thu,fri,sat,sun",
      timezone: "Asia/Shanghai",
    },
    dispatch: {
      type: "channel",
      target: {
        user_id: "source-user",
        session_id: "session-1",
      },
    },
  };
}

describe("BroadcastChildrenModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listCronBroadcastChildren.mockResolvedValue({
      items: [],
      status: "idle",
      tenant_count: 0,
      failed_tenants: 0,
      failure_summary: null,
      updated_at: null,
    });
    mocks.refreshCronBroadcastChildren.mockResolvedValue({
      items: [],
      status: "running",
      tenant_count: 0,
      failed_tenants: 0,
      failure_summary: null,
      updated_at: null,
      reused: false,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("keeps the table inside a wide modal", async () => {
    render(
      <BroadcastChildrenModal open job={buildJob()} onClose={vi.fn()} />,
    );

    await waitFor(() => {
      expect(mocks.listCronBroadcastChildren).toHaveBeenCalledWith(
        "job-source",
      );
    });

    const modal = document.querySelector(".ant-modal");
    expect(modal).toHaveStyle("width: 1280px");
    expect(modal).toHaveStyle("max-width: calc(100vw - 48px)");
  });

  it("shows duplicate tenant names as separate UID rows", async () => {
    const duplicateSnapshot = {
      status: "completed",
      tenant_count: 2,
      failed_tenants: 0,
      failure_summary: null,
      updated_at: "2026-06-24T08:00:00Z",
      items: [
        {
          tenant_id: "80112233",
          tenant_name: "周欣",
          bbk_id: "100",
          job_id: "child-1",
          job_name: "ark",
          enabled: true,
          cron: "0 5 * * thu,fri,sat,sun",
          timezone: "Asia/Shanghai",
          offset_minutes: 240,
          last_status: null,
          last_run_at: null,
          last_error: null,
        },
        {
          tenant_id: "80245604",
          tenant_name: "周欣",
          bbk_id: "100",
          job_id: "child-2",
          job_name: "ark",
          enabled: true,
          cron: "0 5 * * thu,fri,sat,sun",
          timezone: "Asia/Shanghai",
          offset_minutes: 240,
          last_status: null,
          last_run_at: null,
          last_error: null,
        },
      ],
    };
    mocks.listCronBroadcastChildren.mockResolvedValue(duplicateSnapshot);
    mocks.refreshCronBroadcastChildren.mockResolvedValue({
      ...duplicateSnapshot,
      status: "running",
      reused: false,
    });

    render(
      <BroadcastChildrenModal open job={buildJob()} onClose={vi.fn()} />,
    );

    expect(
      await screen.findByText("存在同名用户，请以 UID 区分"),
    ).toBeInTheDocument();
    expect(screen.getByText("周欣 (2 个 UID)")).toBeInTheDocument();
    expect(screen.getByText("80112233")).toBeInTheDocument();
    expect(screen.getByText("80245604")).toBeInTheDocument();
  });

  it("starts lookup on open and refresh button only reads snapshot", async () => {
    mocks.listCronBroadcastChildren
      .mockResolvedValueOnce({
        items: [],
        status: "idle",
        tenant_count: 0,
        failed_tenants: 0,
        failure_summary: null,
        updated_at: null,
      })
      .mockResolvedValueOnce({
        items: [],
        status: "running",
        tenant_count: 2,
        failed_tenants: 0,
        failure_summary: null,
        updated_at: null,
      });
    mocks.refreshCronBroadcastChildren.mockResolvedValue({
      items: [],
      status: "running",
      tenant_count: 2,
      failed_tenants: 0,
      failure_summary: null,
      updated_at: null,
      reused: false,
    });

    render(
      <BroadcastChildrenModal open job={buildJob()} onClose={vi.fn()} />,
    );

    await waitFor(() => {
      expect(mocks.listCronBroadcastChildren).toHaveBeenCalledWith(
        "job-source",
      );
    });
    await waitFor(() => {
      expect(mocks.refreshCronBroadcastChildren).toHaveBeenCalledWith(
        "job-source",
      );
    });
    expect(await screen.findByText("状态：生成中")).toBeInTheDocument();
    expect(screen.getByText("数据时间：正在生成中")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "刷新" }));

    await waitFor(() => {
      expect(mocks.listCronBroadcastChildren).toHaveBeenCalledTimes(2);
    });
    expect(mocks.refreshCronBroadcastChildren).toHaveBeenCalledTimes(1);
  });
});
