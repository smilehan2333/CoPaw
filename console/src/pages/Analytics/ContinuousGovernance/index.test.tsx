import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import dayjs from "dayjs";

import ContinuousGovernancePage from "./index";

const mocks = vi.hoisted(() => ({
  dreamLogsApi: {
    archiveReport: vi.fn(),
    listArchiveAdminAudits: vi.fn(),
    listArchiveItems: vi.fn(),
    listProtectedFiles: vi.fn(),
    report: vi.fn(),
    reportUserRecords: vi.fn(),
  },
  fetchBbkBySource: vi.fn(),
}));

vi.mock("../../../api/modules/dreamLogs", () => ({
  dreamLogsApi: mocks.dreamLogsApi,
}));
vi.mock("../../../api/modules/userInfo", () => ({
  fetchBbkBySource: mocks.fetchBbkBySource,
}));
vi.mock("../../../stores/iframeStore", () => ({
  useIframeStore: (selector: (state: { source: string }) => unknown) =>
    selector({ source: "RMASSIST" }),
}));

describe("ContinuousGovernancePage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchBbkBySource.mockResolvedValue([
      { bbk_id: "bbk-1", bbk_name: "杭州分行" },
      { bbk_id: "3302", bbk_name: "南京分行" },
    ]);
    mocks.dreamLogsApi.report.mockResolvedValue({
      summary: {
        covered_users: 10,
        governed_users: 7,
        ungoverned_users: 3,
        total_executions: 18,
        success_count: 15,
        failed_count: 3,
        success_rate: 83.33,
        total_files_changed: 44,
        total_size_saved: 2048,
        avg_duration_ms: 3200,
        last_execution: "2026-05-25T09:00:00Z",
      },
      trends: [
        {
          date: "2026-05-24",
          executions: 8,
          manual_count: 5,
          cron_count: 3,
          success_count: 7,
          failed_count: 1,
          total_size_saved: 1024,
        },
        {
          date: "2026-05-25",
          executions: 10,
          manual_count: 4,
          cron_count: 6,
          success_count: 8,
          failed_count: 2,
          total_size_saved: 1024,
        },
      ],
      status_distribution: [
        { status: "success", count: 15 },
        { status: "failed", count: 3 },
      ],
      bbk_distribution: [
        {
          bbk_id: "bbk-1",
          user_count: 6,
          governed_users: 5,
          executions: 12,
          success_rate: 90,
        },
        {
          bbk_id: "unassigned",
          user_count: 1,
          governed_users: 1,
          executions: 1,
          success_rate: 100,
        },
      ],
      users: [
        {
          user_id: "alice",
          user_name: "Alice",
          bbk_id: "bbk-1",
          agents: ["default"],
          executions: 4,
          success_rate: 75,
          failed_count: 1,
          total_files_changed: 8,
          total_size_saved: 1024,
          last_execution: "2026-05-25T09:00:00Z",
          latest_error: "model timeout",
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
      health: [],
    });
    mocks.dreamLogsApi.reportUserRecords.mockResolvedValue({
      records: [
        {
          id: "record-1",
          timestamp: "2026-05-25T09:00:00Z",
          trigger: "manual",
          status: "failed",
          agent_id: "default",
          files_optimized: ["MEMORY.md"],
          total_size_saved: 0,
          total_files_changed: 0,
          duration_ms: 1200,
          model_used: "gpt-test",
          input_tokens: 10,
          output_tokens: 20,
          summary: "failed",
          error: "model timeout",
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    });
    mocks.dreamLogsApi.archiveReport.mockResolvedValue({
      summary: {
        archived_files: 3,
        archived_size_bytes: 4096,
        pending_purge_files: 1,
        pending_purge_size_bytes: 1024,
        protected_files: 2,
        protected_existing_files: 1,
        protected_missing_files: 1,
        purge_operations: 4,
        purge_success_operations: 3,
        purge_failed_operations: 1,
        purged_files: 8,
        purged_size_bytes: 8192,
        last_purge_at: "2026-05-26T09:00:00Z",
      },
      health: [],
    });
    mocks.dreamLogsApi.listArchiveItems.mockResolvedValue({
      items: [
        {
          id: "archive-1",
          original_path: "memory/old.md",
          archive_path: "governance/archive/files/archive-1",
          size_bytes: 2048,
          mtime: "2026-05-20T09:00:00Z",
          archived_at: "2026-05-25T09:00:00Z",
          archived_by: "admin",
          archive_reason: "manual",
          target_user_id: "alice",
          target_agent_id: "default",
          expired: true,
        },
      ],
      total: 11,
      page: 1,
      page_size: 10,
    });
    mocks.dreamLogsApi.listProtectedFiles.mockResolvedValue({
      items: [
        {
          target_user_id: "bob",
          target_agent_id: "default",
          path: "memory/protected.md",
          protected_at: "2026-05-24T09:00:00Z",
          protected_by: "admin",
          reason: "restored_from_archive",
          exists: false,
          size_bytes: null,
          mtime: null,
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    });
    mocks.dreamLogsApi.listArchiveAdminAudits.mockResolvedValue({
      summary: {
        total_operations: 1,
        success_operations: 1,
        failed_operations: 0,
        partial_success_operations: 0,
        manual_operations: 1,
        auto_operations: 0,
        total_files_cleared: 2,
        total_size_cleared_bytes: 4096,
        last_operation_at: "2026-05-26T09:00:00Z",
      },
      items: [
        {
          event_id: "audit-1",
          timestamp: "2026-05-26T09:00:00Z",
          operation: "purge_archive",
          status: "success",
          actor_user_id: "admin",
          actor_role: "admin",
          source_id: "source-a",
          source_name: "source-a",
          target_user_id: "alice",
          target_agent_id: "default",
          scope: "selected",
          files_count: 2,
          total_size_bytes: 4096,
          reason: "manual_clear",
          error: null,
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    });
  });

  it("shows governance report KPIs and user rows in the default tab", async () => {
    render(<ContinuousGovernancePage />);

    expect(
      await screen.findByRole("heading", { name: "持续治理分析" }),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("governance-kpi-covered_users"),
    ).toHaveTextContent("10");
    expect(screen.getByTestId("governance-kpi-success_rate")).toHaveTextContent(
      "83.33%",
    );
    expect((await screen.findAllByText("Alice")).length).toBeGreaterThan(0);
    expect(mocks.dreamLogsApi.report).toHaveBeenLastCalledWith(
      expect.objectContaining({ agent_id: "default" }),
    );
    expect(
      screen.queryByRole("columnheader", { name: "Agent" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("最新异常")).not.toBeInTheDocument();
    expect(screen.queryByText("model timeout")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Agent")).not.toBeInTheDocument();
    expect(screen.getByText("其他")).toBeInTheDocument();
    expect((await screen.findAllByText("杭州分行")).length).toBeGreaterThan(0);
    expect(screen.getByText("手动")).toBeInTheDocument();
    expect(screen.getByText("自动")).toBeInTheDocument();
    expect(screen.getByText("节省空间趋势")).toBeInTheDocument();
    expect(mocks.dreamLogsApi.archiveReport).not.toHaveBeenCalled();
    expect(
      screen.queryByTestId("governance-kpi-archive_files"),
    ).not.toBeInTheDocument();
  }, 10000);

  it("loads all source branches for the BBK filter", async () => {
    render(<ContinuousGovernancePage />);

    await waitFor(() => {
      expect(mocks.fetchBbkBySource).toHaveBeenCalledWith("RMASSIST");
    });

    fireEvent.mouseDown(screen.getByText("机构 BBK"));

    expect(await screen.findByText("南京分行")).toBeInTheDocument();
  });

  it("keeps refresh with query actions and removes the top dashboard title", async () => {
    render(<ContinuousGovernancePage />);

    await screen.findByTestId("governance-kpi-covered_users");

    expect(
      screen.queryByRole("heading", { name: "质量工程看板" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("面向当前来源的持续治理质量与文件清理归档分析"),
    ).not.toBeInTheDocument();

    const actions = screen.getByTestId("governance-filter-actions");
    expect(
      within(actions).getByTestId("governance-query-button"),
    ).toBeInTheDocument();
    expect(within(actions).getByTestId("governance-reset-button"))
      .toBeInTheDocument();
    expect(within(actions).getAllByRole("button")).toHaveLength(2);
  });

  it("applies date shortcut filters immediately", async () => {
    render(<ContinuousGovernancePage />);

    await screen.findByTestId("governance-kpi-covered_users");
    fireEvent.click(screen.getByText("今天"));

    const today = dayjs().format("YYYY-MM-DD");
    await waitFor(() => {
      expect(mocks.dreamLogsApi.report).toHaveBeenLastCalledWith(
        expect.objectContaining({
          start_time: today,
          end_time: today,
          agent_id: "default",
        }),
      );
    });
  });

  it("loads readonly user governance records in a drawer", async () => {
    render(<ContinuousGovernancePage />);

    await screen.findAllByText("Alice");
    fireEvent.click(screen.getAllByRole("button", { name: "查看 alice" })[0]);

    await waitFor(() => {
      expect(mocks.dreamLogsApi.reportUserRecords).toHaveBeenCalledWith(
        "alice",
        expect.objectContaining({ page: 1, page_size: 10 }),
      );
    });

    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("record-1")).toBeInTheDocument();
    expect(within(drawer).queryByText("只读下钻")).not.toBeInTheDocument();
    expect(
      within(drawer).queryByRole("columnheader", { name: "异常" }),
    ).not.toBeInTheDocument();
    expect(within(drawer).queryByText("model timeout")).not.toBeInTheDocument();

    fireEvent.click(
      within(drawer).getByRole("button", { name: "查看 record-1 详情" }),
    );

    expect(screen.getByText("治理记录详情")).toBeInTheDocument();
    expect(screen.getByText("model timeout")).toBeInTheDocument();
    expect(screen.getByText("gpt-test")).toBeInTheDocument();
    expect(screen.getByText("MEMORY.md")).toBeInTheDocument();
  }, 10000);

  it("loads archive readonly metrics and lists after switching tabs", async () => {
    render(<ContinuousGovernancePage />);

    await screen.findAllByText("Alice");
    fireEvent.click(screen.getByRole("tab", { name: "文件清理与归档" }));

    expect(screen.queryByText("只读分析")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "当前来源内可管理用户的归档、保护文件和清理审计情况。这里仅展示文件清理与归档状态，不提供清理、恢复、归档或取消保护操作。需要处理文件时请进入持续治理工作台。",
      ),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(mocks.dreamLogsApi.archiveReport).toHaveBeenCalledTimes(1);
      expect(mocks.dreamLogsApi.listArchiveItems).toHaveBeenCalledWith({
        target_agent_id: "default",
        page: 1,
        page_size: 10,
      });
      expect(mocks.dreamLogsApi.listProtectedFiles).toHaveBeenCalledWith({
        target_agent_id: "default",
        page: 1,
        page_size: 10,
      });
      expect(mocks.dreamLogsApi.listArchiveAdminAudits).toHaveBeenCalledWith({
        target_agent_id: "default",
        page: 1,
        page_size: 10,
      });
    });

    expect(screen.getByTestId("governance-kpi-archive_files")).toHaveTextContent(
      "3",
    );
    expect(screen.getAllByText("memory/old.md").length).toBeGreaterThan(0);
    expect(screen.getAllByText("memory/protected.md").length).toBeGreaterThan(
      0,
    );
    expect(screen.getAllByText("audit-1").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("columnheader", { name: "Agent" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "原路径" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "归档时间" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "归档人" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "保护时间" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "保护人" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "存在状态" }),
    ).not.toBeInTheDocument();
  }, 20000);

  it("requests file cleanup details by table page", async () => {
    render(<ContinuousGovernancePage />);

    await screen.findAllByText("Alice");
    fireEvent.click(screen.getByRole("tab", { name: "文件清理与归档" }));

    await waitFor(() => {
      expect(mocks.dreamLogsApi.listArchiveItems).toHaveBeenLastCalledWith({
        target_agent_id: "default",
        page: 1,
        page_size: 10,
      });
    });

    const archiveSection = screen.getByText("归档文件").closest("section");
    expect(archiveSection).not.toBeNull();
    const secondPage = within(archiveSection as HTMLElement).getByTitle("2");
    fireEvent.click(secondPage);

    await waitFor(() => {
      expect(mocks.dreamLogsApi.listArchiveItems).toHaveBeenLastCalledWith({
        target_agent_id: "default",
        page: 2,
        page_size: 10,
      });
    });
  }, 20000);

  it("shows reconcile health separately from core metrics", async () => {
    mocks.dreamLogsApi.report.mockResolvedValueOnce({
      summary: {
        covered_users: 1,
        governed_users: 1,
        ungoverned_users: 0,
        total_executions: 1,
        success_count: 1,
        failed_count: 0,
        success_rate: 100,
        total_files_changed: 1,
        total_size_saved: 10,
        avg_duration_ms: 100,
        last_execution: "2026-05-25T09:00:00Z",
      },
      trends: [],
      status_distribution: [],
      bbk_distribution: [],
      users: [],
      total: 0,
      page: 1,
      page_size: 20,
      health: [
        {
          source_id: "source-a",
          target_user_id: "alice",
          target_agent_id: "default",
          entity_type: "governance_record",
          entity_id: "record-2",
          status: "reconcile_needed",
          reason: "db write failed",
          error: "timeout",
          payload: {},
          updated_at: "2026-05-25T10:00:00Z",
        },
      ],
    });

    render(<ContinuousGovernancePage />);

    expect(
      await screen.findByTestId("governance-health-panel"),
    ).toHaveTextContent("governance_record / record-2");
    expect(screen.getByTestId("governance-kpi-total_executions")).toHaveTextContent(
      "1",
    );
  });

  it("passes only user-dimension filters to file governance requests", async () => {
    render(<ContinuousGovernancePage />);

    await screen.findAllByText("Alice");
    fireEvent.change(screen.getByPlaceholderText("搜索用户 ID / 姓名"), {
      target: { value: "Alice" },
    });
    fireEvent.click(screen.getByTestId("governance-query-button"));

    await waitFor(() => {
      expect(mocks.dreamLogsApi.report).toHaveBeenLastCalledWith(
        expect.objectContaining({
          user_search: "Alice",
          agent_id: "default",
        }),
      );
    });

    fireEvent.click(screen.getByRole("tab", { name: "文件清理与归档" }));

    await waitFor(() => {
      expect(mocks.dreamLogsApi.archiveReport).toHaveBeenCalledWith({
        user_search: "Alice",
        target_agent_id: "default",
      });
    });
    expect(mocks.dreamLogsApi.listArchiveItems).toHaveBeenCalledWith({
      user_search: "Alice",
      target_agent_id: "default",
      page: 1,
      page_size: 10,
    });
    expect(mocks.dreamLogsApi.listProtectedFiles).toHaveBeenCalledWith({
      user_search: "Alice",
      target_agent_id: "default",
      page: 1,
      page_size: 10,
    });
    expect(mocks.dreamLogsApi.listArchiveAdminAudits).toHaveBeenCalledWith({
      user_search: "Alice",
      target_agent_id: "default",
      page: 1,
      page_size: 10,
    });
  });

  it("keeps governance report visible when archive data fails", async () => {
    mocks.dreamLogsApi.archiveReport.mockRejectedValueOnce(
      new Error("archive failed"),
    );

    render(<ContinuousGovernancePage />);

    expect((await screen.findAllByText("Alice")).length).toBeGreaterThan(0);
    expect(screen.getByTestId("governance-kpi-covered_users")).toHaveTextContent(
      "10",
    );

    fireEvent.click(screen.getByRole("tab", { name: "文件清理与归档" }));

    await waitFor(() => {
      expect(mocks.dreamLogsApi.archiveReport).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByText("memory/old.md")).not.toBeInTheDocument();
  });

  it("keeps archive tab available when governance report fails", async () => {
    mocks.dreamLogsApi.report.mockRejectedValueOnce(new Error("report failed"));

    render(<ContinuousGovernancePage />);
    fireEvent.click(screen.getByRole("tab", { name: "文件清理与归档" }));

    expect(
      await screen.findByTestId("governance-kpi-archive_files"),
    ).toHaveTextContent("3");
    expect(screen.getAllByText("memory/old.md").length).toBeGreaterThan(0);
  });
});
