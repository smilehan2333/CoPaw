import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import BusinessOverviewPage, { buildTrendSvgData } from "./index";

vi.mock("echarts-for-react", () => ({
  default: (props: { style?: Record<string, unknown> }) => (
    <div data-testid="echarts" style={props.style} />
  ),
}));

const tracingApiMock = vi.hoisted(() => ({
  getOverview: vi.fn(),
  getGrowthStats: vi.fn(),
  getHourlyTrend: vi.fn(),
  getDailyTrend: vi.fn(),
  getUsers: vi.fn(),
  getSkills: vi.fn(),
  getMCPSummary: vi.fn(),
  getTaskStatusSummary: vi.fn(),
  getDepthSummary: vi.fn(),
  getErrorSummary: vi.fn(),
  getSources: vi.fn(),
}));
const htmlPreviewEventsApiMock = vi.hoisted(() => ({
  getSummary: vi.fn(),
  getEvents: vi.fn(),
  getCustomerSummary: vi.fn(),
  getLists: vi.fn(),
  getCustomerClicks: vi.fn(),
}));

vi.mock("../../../api/modules/tracing", () => ({
  tracingApi: tracingApiMock,
}));

vi.mock("../../../api/modules/htmlPreviewEvents", () => ({
  htmlPreviewEventsApi: htmlPreviewEventsApiMock,
}));

vi.mock("../../../stores/iframeStore", () => ({
  useIframeStore: (selector: (state: unknown) => unknown) =>
    selector({
      isSuperManager: true,
      source: "CMSJY",
      bbk: undefined,
    }),
}));

vi.mock("./components/UserDetailModal", () => ({
  default: () => null,
}));

vi.mock("./components/SkillDetailModal", () => ({
  default: () => null,
}));

describe("BusinessOverview trend chart", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    tracingApiMock.getOverview.mockResolvedValue({
      total_users: 120,
      total_sessions: 80,
      total_tokens: 56000,
      total_skill_calls: 40,
      total_conversations: 160,
      branch_breakdown: {
        users: [],
        sessions: [],
        tokens: [],
        skills: [],
        cron_tasks: [],
      },
    });
    tracingApiMock.getGrowthStats.mockResolvedValue({
      callsGrowth: 10,
      tokensGrowth: 12,
      sessionGrowth: 8,
      userGrowth: 5,
      skillGrowth: 3,
      cronGrowth: 2,
      avgRoundsGrowth: 4,
      multiRoundRatioGrowth: 1,
      avgDurationGrowth: 6,
      avgSessionsPerUserGrowth: 7,
    });
    tracingApiMock.getHourlyTrend.mockResolvedValue({
      trendData: [
        { date: "2026-05-19 09:00:00", users: 3200, calls: 15800, tokens: 0 },
        { date: "2026-05-19 10:00:00", users: 2100, calls: 9200, tokens: 0 },
      ],
    });
    tracingApiMock.getDailyTrend.mockResolvedValue({ trendData: [] });
    tracingApiMock.getUsers.mockResolvedValue({ items: [], total: 0 });
    tracingApiMock.getSkills.mockResolvedValue({ items: [], total: 0 });
    tracingApiMock.getMCPSummary.mockResolvedValue({
      total_calls: 0,
      error_count: 0,
      server_count: 0,
    });
    tracingApiMock.getTaskStatusSummary.mockResolvedValue({
      total_tasks: 0,
      success: 0,
      failed: 0,
      cancelled: 0,
    });
    tracingApiMock.getDepthSummary.mockResolvedValue({
      avg_rounds: 2,
      multi_round_ratio: 10,
      avg_duration_seconds: 30,
      avg_sessions_per_user: 1.5,
    });
    tracingApiMock.getErrorSummary.mockResolvedValue({
      total_errors: 0,
      model_errors: 0,
      tool_errors: 0,
      other_errors: 0,
    });
    tracingApiMock.getSources.mockResolvedValue({ sources: ["CMSJY"] });
    htmlPreviewEventsApiMock.getSummary.mockResolvedValue({
      items: [
        {
          button_label: "立即跟进",
          button_id: "follow",
          button_name: "立即跟进",
          file_name: "到期客户名单[auto-preview].html",
          click_count: 12,
          last_clicked_at: "2026-05-19T10:30:00",
        },
      ],
    });
    htmlPreviewEventsApiMock.getEvents.mockResolvedValue({
      items: [
        {
          id: 1,
          button_name: "洞察页面",
          file_url: "https://example.com/a.html",
          customer_info: {
            customer_id: "CUST-001",
            客户姓名: "祝话",
          },
          clicked_at: "2026-05-19T10:35:00",
        },
      ],
    });
    htmlPreviewEventsApiMock.getCustomerSummary.mockResolvedValue({
      items: [
        {
          customer_id: "CUST-001",
          customer_name: "祝话",
          insight_count: 2,
          phone_count: 1,
          plan_count: 1,
          last_clicked_at: "2026-05-19T10:35:00",
        },
      ],
    });
    htmlPreviewEventsApiMock.getLists.mockResolvedValue({
      total: 328,
      clicked_list_count: 82,
      page: 1,
      page_size: 20,
      summary: {
        list_key: "all",
        list_name: "全部名单",
        customer_count: 160,
        clicked_customer_count: 40,
        insight_count: 20,
        phone_count: 10,
        plan_count: 30,
        total_click_count: 60,
        last_clicked_at: "2026-05-19T10:35:00",
      },
      items: [
        {
          list_key: "https://example.com/a.html",
          list_name: "到期客户名单[auto-preview].html",
          file_url: "https://example.com/a.html",
          file_name: "到期客户名单[auto-preview].html",
          customer_count: 16,
          clicked_customer_count: 1,
          insight_count: 2,
          phone_count: 1,
          plan_count: 1,
          total_click_count: 4,
          last_clicked_at: "2026-05-19T10:35:00",
        },
      ],
    });
    htmlPreviewEventsApiMock.getCustomerClicks.mockResolvedValue({
      items: [
        {
          customer_id: "CUST-001",
          customer_name: "祝话",
          list_key: "https://example.com/a.html",
          list_name: "到期客户名单[auto-preview].html",
          insight_count: 2,
          phone_count: 1,
          plan_count: 1,
          total_click_count: 4,
          last_clicked_user_id: "manager-1",
          last_clicked_user_name: "张经理",
          manager_clicks: [
            {
              user_id: "manager-1",
              user_name: "张经理",
              insight_count: 2,
              phone_count: 1,
              plan_count: 0,
              total_click_count: 3,
              last_clicked_at: "2026-05-19T10:35:00",
            },
            {
              user_id: "manager-2",
              user_name: "李经理",
              insight_count: 0,
              phone_count: 0,
              plan_count: 1,
              total_click_count: 1,
              last_clicked_at: "2026-05-19T09:35:00",
            },
          ],
          last_clicked_at: "2026-05-19T10:35:00",
        },
      ],
    });
  });

  function renderBusinessOverview() {
    return render(
      <MemoryRouter>
        <BusinessOverviewPage />
      </MemoryRouter>,
    );
  }

  it("builds dynamic y-axis ticks from actual trend maxima", () => {
    const trendSvg = buildTrendSvgData([
      { date: "2026-05-19", users: 3200, calls: 15800 },
      { date: "2026-05-20", users: 2100, calls: 9200 },
    ]);

    expect(trendSvg.leftAxisTicks.map((tick) => tick.label)).toEqual([
      "5K",
      "4K",
      "3K",
      "2K",
      "1K",
      "0",
    ]);
    expect(trendSvg.rightAxisTicks.map((tick) => tick.label)).toEqual([
      "2W",
      "1.6W",
      "1.2W",
      "0.8W",
      "0.4W",
      "0",
    ]);
  });

  it("scales bars and line points against nice axis maxima instead of raw maxima", () => {
    const trendSvg = buildTrendSvgData([
      { date: "2026-05-19", users: 5, calls: 5 },
      { date: "2026-05-20", users: 6, calls: 6 },
    ]);

    expect(trendSvg.leftAxisTicks.map((tick) => tick.label)).toEqual([
      "10",
      "8",
      "6",
      "4",
      "2",
      "0",
    ]);
    expect(trendSvg.rightAxisTicks.map((tick) => tick.label)).toEqual([
      "10",
      "8",
      "6",
      "4",
      "2",
      "0",
    ]);
    expect(trendSvg.bars[0]?.y).toBeCloseTo(109, 3);
    expect(trendSvg.points[0]?.y).toBeCloseTo(109, 3);
  });

  it("uses a tighter nice axis for low-hundreds trend values", () => {
    const trendSvg = buildTrendSvgData([
      { date: "2026-05-19", users: 12, calls: 202 },
      { date: "2026-05-20", users: 10, calls: 180 },
    ]);

    expect(trendSvg.rightAxisTicks.map((tick) => tick.label)).toEqual([
      "250",
      "200",
      "150",
      "100",
      "50",
      "0",
    ]);
  });

  it("shows the real values when hovering a trend column", async () => {
    renderBusinessOverview();

    await waitFor(() => {
      expect(screen.getByTestId("trend-hover-zone-0")).toBeInTheDocument();
    });

    fireEvent.mouseEnter(screen.getByTestId("trend-hover-zone-0"));

    const tooltip = await screen.findByTestId("trend-tooltip");
    expect(within(tooltip).getByText("09:00")).toBeInTheDocument();
    expect(within(tooltip).getByText("3,200")).toBeInTheDocument();
    expect(within(tooltip).getByText("15,800")).toBeInTheDocument();
  });

  it("maps avgDurationGrowth into the average duration growth card", async () => {
    renderBusinessOverview();

    expect(await screen.findByText("30s")).toBeInTheDocument();
    expect(
      await screen.findByText(
        (_, element) =>
          typeof element?.className === "string" &&
          element.className.includes("metricChangeUp") &&
          (element.textContent || "").includes("环比+6.0%"),
      ),
    ).toBeInTheDocument();
  });

  it("renders customer insight and phone click statistics inside business overview", async () => {
    renderBusinessOverview();

    expect(await screen.findByText("客户经营点击分析")).toBeInTheDocument();
    expect(await screen.findByText("点击总数")).toBeInTheDocument();
    expect(await screen.findByText("名单总客户数")).toBeInTheDocument();
    expect(await screen.findByText("被点击名单数")).toBeInTheDocument();
    expect(await screen.findByText("名单点击率")).toBeInTheDocument();
    expect(await screen.findByText("被点击客户数")).toBeInTheDocument();
    expect(await screen.findByText("客户点击覆盖率")).toBeInTheDocument();
    expect(await screen.findByText("328")).toBeInTheDocument();
    expect((await screen.findAllByText("25.0%")).length).toBeGreaterThan(0);
    expect(
      await screen.findByText("到期客户名单[auto-preview].html"),
    ).toBeInTheDocument();
    expect(await screen.findByText("祝话")).toBeInTheDocument();
    expect(await screen.findByText("CUST-001")).toBeInTheDocument();
    expect(await screen.findByText("张经理")).toBeInTheDocument();
    expect((await screen.findAllByText("洞察")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("电访")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("查看方案")).length).toBeGreaterThan(0);
    fireEvent.click(await screen.findByText("详情"));
    expect(
      await screen.findByText("祝话 客户经理点击详情"),
    ).toBeInTheDocument();
    expect(await screen.findByText("李经理")).toBeInTheDocument();
    expect(htmlPreviewEventsApiMock.getSummary).toHaveBeenCalled();
    expect(htmlPreviewEventsApiMock.getLists).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, pageSize: 20 }),
    );
    expect(htmlPreviewEventsApiMock.getCustomerClicks).toHaveBeenCalled();
  });

  it("falls back to list items when paged list summary fields are absent", async () => {
    htmlPreviewEventsApiMock.getLists.mockResolvedValueOnce({
      items: [
        {
          list_key: "https://example.com/a.html",
          list_name: "到期客户名单[auto-preview].html",
          file_url: "https://example.com/a.html",
          file_name: "到期客户名单[auto-preview].html",
          customer_count: 16,
          clicked_customer_count: 1,
          insight_count: 2,
          phone_count: 1,
          plan_count: 1,
          total_click_count: 4,
          last_clicked_at: "2026-05-19T10:35:00",
        },
      ],
    });

    renderBusinessOverview();

    expect(await screen.findByText("名单总客户数")).toBeInTheDocument();
    expect(await screen.findByText("6.3%")).toBeInTheDocument();
    expect(htmlPreviewEventsApiMock.getLists).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, pageSize: 20 }),
    );
  });

  it("does not reload paged list data when toggling unclicked customers", async () => {
    renderBusinessOverview();

    await waitFor(() => {
      expect(htmlPreviewEventsApiMock.getLists).toHaveBeenCalledTimes(1);
    });
    const includeUnclickedLabel = (
      await screen.findByText("显示未点击客户")
    ).closest("label");
    expect(includeUnclickedLabel).not.toBeNull();

    fireEvent.click(
      within(includeUnclickedLabel as HTMLElement).getByRole("switch"),
    );

    await waitFor(() => {
      expect(htmlPreviewEventsApiMock.getCustomerClicks).toHaveBeenCalledTimes(
        2,
      );
    });
    expect(htmlPreviewEventsApiMock.getSummary).toHaveBeenCalledTimes(2);
    expect(htmlPreviewEventsApiMock.getLists).toHaveBeenCalledTimes(1);
  });

  it("resets list paging before reloading after date range changes", async () => {
    renderBusinessOverview();

    await waitFor(() => {
      expect(htmlPreviewEventsApiMock.getLists).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(await screen.findByTitle("2"));

    await waitFor(() => {
      expect(htmlPreviewEventsApiMock.getLists).toHaveBeenCalledTimes(2);
    });
    expect(htmlPreviewEventsApiMock.getLists).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, pageSize: 20 }),
    );

    fireEvent.click(screen.getByRole("button", { name: "近7天" }));

    await waitFor(() => {
      expect(htmlPreviewEventsApiMock.getLists).toHaveBeenCalledTimes(3);
    });
    expect(htmlPreviewEventsApiMock.getLists).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, pageSize: 20 }),
    );
  });

  it("auto-loads more skills when the first page does not fill a scrollable viewport", async () => {
    tracingApiMock.getSkills
      .mockResolvedValueOnce({
        items: Array.from({ length: 10 }, (_, index) => ({
          skill_name: `skill-${index + 1}`,
          count: index + 1,
          avg_duration_ms: 100,
        })),
        total: 14,
        page: 1,
        page_size: 10,
      })
      .mockResolvedValueOnce({
        items: Array.from({ length: 4 }, (_, index) => ({
          skill_name: `skill-${index + 11}`,
          count: index + 11,
          avg_duration_ms: 100,
        })),
        total: 14,
        page: 2,
        page_size: 10,
      });

    renderBusinessOverview();

    await waitFor(() => {
      expect(tracingApiMock.getSkills).toHaveBeenNthCalledWith(
        1,
        1,
        10,
        expect.any(Object),
      );
    });

    await waitFor(() => {
      expect(tracingApiMock.getSkills).toHaveBeenNthCalledWith(
        2,
        2,
        10,
        expect.any(Object),
      );
    });

    expect(await screen.findByText("skill-14")).toBeInTheDocument();
  });

  it("auto-loads more active users when the first page does not fill a scrollable viewport", async () => {
    tracingApiMock.getUsers
      .mockResolvedValueOnce({
        items: Array.from({ length: 10 }, (_, index) => ({
          user_id: `user-${index + 1}`,
          user_name: `用户${index + 1}`,
          bbk_id: "100",
          manual_calls: index + 1,
          cron_executions: 0,
          cron_success: 0,
          cron_reads: 0,
        })),
        total: 14,
        page: 1,
        page_size: 10,
      })
      .mockResolvedValueOnce({
        items: Array.from({ length: 4 }, (_, index) => ({
          user_id: `user-${index + 11}`,
          user_name: `用户${index + 11}`,
          bbk_id: "100",
          manual_calls: index + 11,
          cron_executions: 0,
          cron_success: 0,
          cron_reads: 0,
        })),
        total: 14,
        page: 2,
        page_size: 10,
      });

    renderBusinessOverview();

    await waitFor(() => {
      expect(tracingApiMock.getUsers).toHaveBeenNthCalledWith(
        1,
        1,
        10,
        expect.any(Object),
      );
    });

    await waitFor(() => {
      expect(tracingApiMock.getUsers).toHaveBeenNthCalledWith(
        2,
        2,
        10,
        expect.any(Object),
      );
    });

    expect(await screen.findByText(/用户14/)).toBeInTheDocument();
  });
});
