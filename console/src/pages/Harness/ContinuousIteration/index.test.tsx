import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ContinuousIterationPage from "./index";

const mocks = vi.hoisted(() => ({
  dreamLogsApi: {
    list: vi.fn(),
    status: vi.fn(),
    listBackups: vi.fn(),
    listOrphanFiles: vi.fn(),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "dreamLogs.filter.clear": "清空",
        "dreamLogs.filter.endDate": "结束日期",
        "dreamLogs.filter.startDate": "开始日期",
        "dreamLogs.filter.status": "状态",
        "dreamLogs.filter.trigger": "触发方式",
        "dreamLogs.running.title": "治理任务执行中...",
        "dreamLogs.running.triggering": "执行中",
        "dreamLogs.tabBackups": "备份文件",
        "dreamLogs.tabCleanup": "临时文件",
        "dreamLogs.tabRecords": "治理记录",
        "dreamLogs.title": "持续治理记录",
        "dreamLogs.triggerNow": "立即触发",
      })[key] || key,
  }),
}));

vi.mock("../../../api/modules/dreamLogs", () => ({
  dreamLogsApi: mocks.dreamLogsApi,
}));

vi.mock("../../../stores/iframeStore", () => ({
  useIframeStore: (selector: (state: unknown) => unknown) =>
    selector({ isSuperManager: false, manager: false }),
}));

describe("ContinuousIterationPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.dreamLogsApi.list.mockResolvedValue({
      records: [],
      stats: null,
      total: 0,
    });
    mocks.dreamLogsApi.status.mockResolvedValue({
      running: true,
      started_at: "2026-06-04T10:00:00Z",
      trigger: "manual",
    });
    mocks.dreamLogsApi.listBackups.mockResolvedValue({
      files: [],
      total_size: 0,
      total_files: 0,
    });
    mocks.dreamLogsApi.listOrphanFiles.mockResolvedValue({
      files: [],
      total_size: 0,
      total_files: 0,
      workspace_dir: "/workspace",
    });
  });

  it("shows running status without elapsed duration", async () => {
    render(<ContinuousIterationPage />);

    expect(await screen.findByText("治理任务执行中...")).toBeInTheDocument();
    expect(screen.queryByText(/已运行时长|dreamLogs\.running\.elapsed/))
      .not.toBeInTheDocument();
  });

  it("refreshes data whenever switching top tabs", async () => {
    mocks.dreamLogsApi.status.mockResolvedValue({
      running: false,
    });
    render(<ContinuousIterationPage />);

    await waitFor(() => {
      expect(mocks.dreamLogsApi.list).toHaveBeenCalledTimes(1);
      expect(mocks.dreamLogsApi.status).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByRole("tab", { name: /备份文件/ }));
    await waitFor(() => {
      expect(mocks.dreamLogsApi.listBackups).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByRole("tab", { name: /治理记录/ }));
    await waitFor(() => {
      expect(mocks.dreamLogsApi.list).toHaveBeenCalledTimes(2);
      expect(mocks.dreamLogsApi.status).toHaveBeenCalledTimes(2);
    });

    fireEvent.click(screen.getByRole("tab", { name: /临时文件/ }));
    await waitFor(() => {
      expect(mocks.dreamLogsApi.listOrphanFiles).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByRole("tab", { name: /备份文件/ }));
    await waitFor(() => {
      expect(mocks.dreamLogsApi.listBackups).toHaveBeenCalledTimes(2);
    });
  }, 10000);
});
