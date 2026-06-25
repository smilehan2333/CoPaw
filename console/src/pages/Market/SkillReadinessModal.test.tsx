import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SkillReadinessModal } from "./SkillReadinessModal";
import type { MarketSkill } from "../../api/modules/market";
import type {
  SkillReadinessOverview,
  SkillReadinessResultsPage,
} from "../../api/types/skillReadiness";

const mocks = vi.hoisted(() => ({
  getSkillReadinessOverview: vi.fn(),
  startSkillReadinessRun: vi.fn(),
  getSkillReadinessResults: vi.fn(),
}));

vi.mock("../../api/modules/skillReadiness", () => ({
  skillReadinessApi: mocks,
}));

function buildSkill(overrides: Partial<MarketSkill> = {}): MarketSkill {
  return {
    item_id: "market-1",
    skill_id: "skill-001",
    name: "sales-helper",
    skill_name: "sales-helper",
    description: "",
    version: "1.0.0",
    creator_id: "admin",
    creator_name: "Admin",
    category_id: null,
    bbk_ids: [],
    status: "active",
    created_at: null,
    updated_at: null,
    call_count: 0,
    user_count: 0,
    ...overrides,
  };
}

function buildOverview(
  overrides: Partial<SkillReadinessOverview> = {},
): SkillReadinessOverview {
  return {
    skill_id: "skill-001",
    config_found: true,
    startable: true,
    config_message: "已查询到自检配置",
    config_checks: [
      {
        name: "cron_model_connection",
        display_name: "模型连通性",
        enabled: true,
      },
    ],
    owner_summary: {
      total_users: 1,
      lookup_failed_users: 0,
      failure_summary: null,
    },
    owners: [
      {
        user_id: "user-a",
        user_name: "Alice",
        bbk_id: "1001",
        skill_name: "sales-helper",
        market_version: "2.0.0",
        installed_version: "1.0.0",
        received_version: "1.0.0",
        enabled: true,
        has_update: true,
      },
    ],
    owner_lookup_status: "completed",
    owner_lookup_updated_at: null,
    latest_run: null,
    ...overrides,
  };
}

function buildResults(): SkillReadinessResultsPage {
  return {
    run: {
      run_id: "run-1",
      source_id: "source-1",
      skill_id: "skill-001",
      status: "completed",
      total_users: 1,
      completed_users: 1,
      failed_users: 1,
      failure_summary: null,
      created_at: null,
      started_at: null,
      completed_at: null,
      updated_at: null,
    },
    items: [
      {
        user_id: "user-a",
        user_name: "Alice",
        bbk_id: "1001",
        aggregate_status: "abnormal",
        summary: "模型不可用",
        duration_ms: 10,
        checks: [
          {
            check_name: "cron_model_connection",
            display_name: "模型连通性",
            status: "fail",
            message: "连接失败",
            details: {},
            duration_ms: 10,
          },
        ],
      },
    ],
    total: 1,
    page: 1,
    page_size: 20,
  };
}

describe("SkillReadinessModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getSkillReadinessOverview.mockResolvedValue(buildOverview());
    mocks.startSkillReadinessRun.mockResolvedValue({
      reused: false,
      run: {
        run_id: "run-1",
        source_id: "source-1",
        skill_id: "skill-001",
        status: "running",
        total_users: 1,
        completed_users: 0,
        failed_users: 0,
        failure_summary: null,
        created_at: null,
        started_at: null,
        completed_at: null,
        updated_at: null,
      },
    });
    mocks.getSkillReadinessResults.mockResolvedValue(buildResults());
  });

  afterEach(() => {
    cleanup();
  });

  it("starts owner lookup when config is missing", async () => {
    mocks.getSkillReadinessOverview.mockResolvedValue(
      buildOverview({
        skill_id: "sales-helper",
        config_found: false,
        startable: false,
        config_message: "未查询到自检配置",
        config_checks: [],
      }),
    );
    mocks.startSkillReadinessRun.mockResolvedValue({
      reused: false,
      run: null,
      owner_lookup_only: true,
      owner_lookup_scheduled: true,
    });

    render(
      <SkillReadinessModal
        open
        skill={buildSkill({ skill_id: null })}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText("按 skill_name 降级")).toBeInTheDocument();
    expect(await screen.findByText("未查询到自检配置")).toBeInTheDocument();
    expect(
      screen.queryByText("当前技能未返回 skill_id，已按 skill_name 查询"),
    ).not.toBeInTheDocument();
    const startButton = screen.getByRole("button", { name: /查询用户/ });
    expect(startButton).toBeEnabled();

    fireEvent.click(startButton);

    await waitFor(() => {
      expect(mocks.startSkillReadinessRun).toHaveBeenCalledWith("sales-helper");
    });
  });

  it("starts a readiness run for startable config", async () => {
    render(
      <SkillReadinessModal open skill={buildSkill()} onClose={vi.fn()} />,
    );

    await screen.findByText("已查询到自检配置");
    expect(await screen.findByText("sales-helper")).toBeInTheDocument();
    expect(await screen.findByText("2.0.0")).toBeInTheDocument();
    expect(await screen.findByText("1.0.0")).toBeInTheDocument();
    expect(await screen.findByText("已启用")).toBeInTheDocument();
    expect(await screen.findByText("可更新")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /查询用户并检查/ }));

    await waitFor(() => {
      expect(mocks.startSkillReadinessRun).toHaveBeenCalledWith("skill-001");
    });
    expect(await screen.findByText(/run-1/)).toBeInTheDocument();
  });

  it("shows owner lookup data time on overview results", async () => {
    mocks.getSkillReadinessOverview.mockResolvedValue(
      buildOverview({
        owner_lookup_updated_at: "2026-06-24T10:30:00Z",
      }),
    );

    render(
      <SkillReadinessModal open skill={buildSkill()} onClose={vi.fn()} />,
    );

    expect(await screen.findByText(/数据时间：/)).toHaveTextContent(
      "数据时间：",
    );
    expect(await screen.findByText(/2026/)).toBeInTheDocument();
  });

  it("shows start hint before owner data is generated", async () => {
    mocks.getSkillReadinessOverview.mockResolvedValue(
      buildOverview({
        owner_summary: {
          total_users: 0,
          lookup_failed_users: 0,
          failure_summary: null,
        },
        owners: [],
        owner_lookup_status: "idle",
        owner_lookup_updated_at: null,
      }),
    );

    render(
      <SkillReadinessModal open skill={buildSkill()} onClose={vi.fn()} />,
    );

    expect(
      await screen.findByText("查询用户后生成拥有用户"),
    ).toBeInTheDocument();
    expect(await screen.findByText("数据时间：查询用户后生成")).toBeInTheDocument();
  });

  it("ignores stale overview responses after switching skills", async () => {
    let resolveFirst: (value: SkillReadinessOverview) => void = () => {};
    let resolveSecond: (value: SkillReadinessOverview) => void = () => {};
    mocks.getSkillReadinessOverview
      .mockReturnValueOnce(
        new Promise<SkillReadinessOverview>((resolve) => {
          resolveFirst = resolve;
        }),
      )
      .mockReturnValueOnce(
        new Promise<SkillReadinessOverview>((resolve) => {
          resolveSecond = resolve;
        }),
      );

    const view = render(
      <SkillReadinessModal open skill={buildSkill({ skill_id: "skill-a" })} onClose={vi.fn()} />,
    );
    view.rerender(
      <SkillReadinessModal open skill={buildSkill({ skill_id: "skill-b" })} onClose={vi.fn()} />,
    );

    await act(async () => {
      resolveSecond(
        buildOverview({
          skill_id: "skill-b",
          owners: [
            {
              user_id: "user-b",
              user_name: "Skill B Owner",
              bbk_id: "1002",
            },
          ],
        }),
      );
    });
    expect(await screen.findByText("Skill B Owner")).toBeInTheDocument();

    await act(async () => {
      resolveFirst(
        buildOverview({
          skill_id: "skill-a",
          owners: [
            {
              user_id: "user-a",
              user_name: "Skill A Owner",
              bbk_id: "1001",
            },
          ],
        }),
      );
    });

    expect(screen.queryByText("Skill A Owner")).not.toBeInTheDocument();
  });

  it("filters failed users by check while requesting full check details", async () => {
    mocks.getSkillReadinessOverview.mockResolvedValue(
      buildOverview({
        latest_run: {
          run_id: "run-1",
          source_id: "source-1",
          skill_id: "skill-001",
          status: "completed",
          total_users: 1,
          completed_users: 1,
          failed_users: 1,
          failure_summary: null,
          created_at: null,
          started_at: null,
          completed_at: null,
          updated_at: null,
          check_summaries: [
            {
              check_name: "cron_model_connection",
              display_name: "模型连通性",
              total: 1,
              pass_count: 0,
              fail_count: 1,
              skip_count: 0,
            },
          ],
        },
      }),
    );

    render(
      <SkillReadinessModal open skill={buildSkill()} onClose={vi.fn()} />,
    );

    await waitFor(() => {
      expect(mocks.getSkillReadinessResults).toHaveBeenCalledWith(
        "run-1",
        expect.objectContaining({ page: 1, page_size: 20, status: "all" }),
      );
    });

    fireEvent.click(await screen.findByRole("button", { name: /模型连通性.*fail 1/ }));

    await waitFor(() => {
      expect(mocks.getSkillReadinessResults).toHaveBeenCalledWith(
        "run-1",
        expect.objectContaining({
          check_name: "cron_model_connection",
          check_status: "fail",
        }),
      );
    });
  });

  it("uses default owner metrics when overview omits owner_summary", async () => {
    mocks.getSkillReadinessOverview.mockResolvedValue({
      ...buildOverview(),
      owner_summary: undefined,
      owners: undefined,
      config_checks: undefined,
    } as unknown as SkillReadinessOverview);

    render(
      <SkillReadinessModal open skill={buildSkill()} onClose={vi.fn()} />,
    );

    expect(await screen.findByText("已查询到自检配置")).toBeInTheDocument();
    expect(await screen.findAllByText("0")).toHaveLength(2);
    expect(screen.getByText("0 / 0")).toBeInTheDocument();
  });
});
