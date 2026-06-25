import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Alert,
  Button,
  Collapse,
  Empty,
  Modal,
  Pagination,
  Popover,
  Progress,
  Segmented,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  CaretDownOutlined,
  CaretRightOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import type { MarketSkill, MarketSkillDetail } from "../../api/modules/market";
import { skillReadinessApi } from "../../api/modules/skillReadiness";
import type {
  SkillReadinessCheckResult,
  SkillReadinessConfigCheckSummary,
  SkillReadinessOverview,
  SkillReadinessOwner,
  SkillReadinessResultsPage,
  SkillReadinessRunProgress,
  SkillReadinessRunStatus,
  SkillReadinessUserResult,
} from "../../api/types/skillReadiness";
import { resolveSkillReadinessTarget } from "./skillReadiness";

const { Text, Title } = Typography;

type UserStatusFilter = "all" | "abnormal" | "normal";

interface SkillReadinessModalProps {
  open: boolean;
  skill: MarketSkill | MarketSkillDetail | null;
  onClose: () => void;
}

const STATUS_LABELS: Record<SkillReadinessRunStatus, string> = {
  running: "运行中",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
};

const CHECK_STATUS_COLORS = {
  pass: "green",
  fail: "red",
  skip: "default",
} as const;

const CHECK_STATUS_LABELS = {
  pass: "通过",
  fail: "失败",
  skip: "跳过",
} as const;

const DEFAULT_OWNER_SUMMARY = {
  total_users: 0,
  lookup_failed_users: 0,
  failure_summary: null,
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN");
}

function runStatusColor(status: SkillReadinessRunStatus): string {
  if (status === "completed") return "green";
  if (status === "partial") return "orange";
  if (status === "failed") return "red";
  return "blue";
}

function runProgressPercent(run: SkillReadinessRunProgress): number {
  if (!run.total_users) return 0;
  return Math.round((run.completed_users / run.total_users) * 100);
}

function getErrorText(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

function renderNullableText(value: string | null | undefined): ReactNode {
  return value || "-";
}

function renderEnabledTag(value: boolean | null | undefined): ReactNode {
  if (value === null || value === undefined) return "-";
  return (
    <Tag color={value ? "green" : "default"}>
      {value ? "已启用" : "已停用"}
    </Tag>
  );
}

function renderUpdateTag(value: boolean | null | undefined): ReactNode {
  if (value === null || value === undefined) return "-";
  return (
    <Tag color={value ? "orange" : "blue"}>
      {value ? "可更新" : "已同步"}
    </Tag>
  );
}

function renderJsonBlock(value: unknown): ReactNode {
  return (
    <pre
      style={{
        margin: 0,
        padding: 8,
        borderRadius: 6,
        backgroundColor: "#fafafa",
        border: "1px solid #f0f0f0",
        fontSize: 12,
        lineHeight: 1.5,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        maxWidth: 520,
        maxHeight: 260,
        overflow: "auto",
      }}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function renderConfigPopoverContent(
  check: SkillReadinessConfigCheckSummary,
): ReactNode {
  return (
    <Space direction="vertical" size={6}>
      <Text strong>{check.display_name}</Text>
      <Text type="secondary" style={{ fontSize: 12 }}>
        name: {check.name}
      </Text>
      <Text type="secondary" style={{ fontSize: 12 }}>
        状态: {check.enabled ? "启用" : "停用"}
      </Text>
      {renderJsonBlock({ params: check.params ?? {} })}
    </Space>
  );
}

function renderConfigTag(check: SkillReadinessConfigCheckSummary): ReactNode {
  return (
    <Popover
      key={check.name}
      trigger="hover"
      placement="top"
      content={renderConfigPopoverContent(check)}
    >
      <Tag color={check.enabled ? "blue" : "default"}>
        {check.display_name}
        {check.enabled ? "" : "（停用）"}
      </Tag>
    </Popover>
  );
}

function hasDetails(details: Record<string, unknown>): boolean {
  return Boolean(details && Object.keys(details).length);
}

function renderCheckMessage(check: SkillReadinessCheckResult): ReactNode {
  if (!check.message) {
    return null;
  }
  const textType = check.status === "fail" ? "danger" : "secondary";
  if (!hasDetails(check.details)) {
    return (
      <Text
        type={textType}
        style={{ display: "block", marginTop: 6, fontSize: 12 }}
      >
        {check.message}
      </Text>
    );
  }
  return (
    <Collapse
      ghost
      size="small"
      expandIcon={({ isActive }) =>
        isActive ? <CaretDownOutlined /> : <CaretRightOutlined />
      }
      style={{ marginTop: 4 }}
      items={[
        {
          key: "details",
          label: (
            <Text type={textType} style={{ fontSize: 12 }}>
              {check.message}
            </Text>
          ),
          children: renderJsonBlock(check.details),
        },
      ]}
    />
  );
}

function renderCheckResult(check: SkillReadinessCheckResult): ReactNode {
  return (
    <div
      key={check.check_name}
      style={{
        padding: "8px 10px",
        borderRadius: 8,
        border: "1px solid #f0f0f0",
        backgroundColor: check.status === "fail" ? "#fff7f6" : "#fff",
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Tag color={CHECK_STATUS_COLORS[check.status]} style={{ margin: 0 }}>
          {CHECK_STATUS_LABELS[check.status]}
        </Tag>
        <Text strong style={{ fontSize: 13 }}>
          {check.display_name}
        </Text>
        <Text type="secondary" style={{ marginLeft: "auto", fontSize: 12 }}>
          {check.duration_ms}ms
        </Text>
      </div>
      {renderCheckMessage(check)}
    </div>
  );
}

function renderUserMeta(user: SkillReadinessUserResult): ReactNode {
  return (
    <div style={{ minWidth: 0, flex: "1 1 180px" }}>
      <Text strong>{user.user_name || user.user_id}</Text>
      <Text
        type="secondary"
        style={{ display: "block", fontSize: 12, marginTop: 2 }}
      >
        {user.user_id}
        {user.bbk_id ? ` · ${user.bbk_id}` : ""}
      </Text>
    </div>
  );
}

function renderAggregateTag(user: SkillReadinessUserResult): ReactNode {
  const abnormal = user.aggregate_status === "abnormal";
  return (
    <Tag color={abnormal ? "red" : "green"} style={{ margin: 0 }}>
      {abnormal ? "异常" : "正常"}
    </Tag>
  );
}

function renderCheckStatusTags(
  checks: SkillReadinessCheckResult[],
): ReactNode {
  return (
    <Space size={[4, 4]} wrap>
      {checks.map((check) => (
        <Tag
          key={check.check_name}
          color={CHECK_STATUS_COLORS[check.status]}
          style={{ margin: 0 }}
        >
          {check.display_name}：{CHECK_STATUS_LABELS[check.status]}
        </Tag>
      ))}
    </Space>
  );
}

function renderUserOverviewLabel(user: SkillReadinessUserResult): ReactNode {
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "center",
        flexWrap: "wrap",
        width: "100%",
      }}
    >
      {renderUserMeta(user)}
      {renderAggregateTag(user)}
      <div style={{ flex: "2 1 360px" }}>
        {renderCheckStatusTags(user.checks)}
      </div>
    </div>
  );
}

function renderSelectedCheckUserResult(
  user: SkillReadinessUserResult,
  selectedCheckName: string,
): ReactNode {
  const checks = user.checks.filter(
    (check) =>
      check.check_name === selectedCheckName && check.status === "fail",
  );
  return (
    <div
      key={user.user_id}
      style={{
        borderRadius: 8,
        border: "1px solid #ffccc7",
        backgroundColor: "#fff2f0",
        padding: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "flex-start",
          flexWrap: "wrap",
          marginBottom: 10,
        }}
      >
        {renderUserMeta(user)}
        {renderAggregateTag(user)}
      </div>
      {user.summary && (
        <Text
          type="danger"
          style={{ display: "block", marginBottom: 10, fontSize: 12 }}
        >
          {user.summary}
        </Text>
      )}
      <Space direction="vertical" size={8} style={{ width: "100%" }}>
        {checks.map(renderCheckResult)}
      </Space>
    </div>
  );
}

export function SkillReadinessModal({
  open,
  skill,
  onClose,
}: SkillReadinessModalProps) {
  const target = useMemo(() => resolveSkillReadinessTarget(skill), [skill]);
  const [overview, setOverview] = useState<SkillReadinessOverview | null>(
    null,
  );
  const [results, setResults] = useState<SkillReadinessResultsPage | null>(
    null,
  );
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [statusFilter, setStatusFilter] = useState<UserStatusFilter>("all");
  const [selectedCheckName, setSelectedCheckName] = useState<string | null>(
    null,
  );
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [resultsRefreshToken, setResultsRefreshToken] = useState(0);
  const overviewRequestSeq = useRef(0);
  const activeSkillRef = useRef("");

  const loadOverview = useCallback(async () => {
    const requestSeq = overviewRequestSeq.current + 1;
    overviewRequestSeq.current = requestSeq;
    if (!open || !target.valid) {
      return;
    }

    setOverviewLoading(true);
    try {
      const data = await skillReadinessApi.getSkillReadinessOverview(
        target.skillId,
      );
      if (overviewRequestSeq.current === requestSeq) {
        setOverview(data);
      }
    } catch (error) {
      if (overviewRequestSeq.current === requestSeq) {
        message.error(getErrorText(error, "加载技能可执行性概览失败"));
        setOverview(null);
      }
    } finally {
      if (overviewRequestSeq.current === requestSeq) {
        setOverviewLoading(false);
      }
    }
  }, [open, target.skillId, target.valid]);

  useEffect(() => {
    activeSkillRef.current = open && target.valid ? target.skillId : "";
    overviewRequestSeq.current += 1;
    if (!open) {
      setOverview(null);
      setResults(null);
      setOverviewLoading(false);
      setResultsLoading(false);
      setStarting(false);
      setStatusFilter("all");
      setSelectedCheckName(null);
      setPage(1);
      setPageSize(20);
      setResultsRefreshToken(0);
      return;
    }
    setOverview(null);
    setResults(null);
    setStarting(false);
    setStatusFilter("all");
    setSelectedCheckName(null);
    setPage(1);
    setPageSize(20);
    setResultsRefreshToken(0);
    void loadOverview();
  }, [open, loadOverview, target.skillId, target.valid]);

  useEffect(() => {
    const runId = overview?.latest_run?.run_id;
    if (!open || !runId) {
      setResults(null);
      return;
    }

    let cancelled = false;
    const effectiveStatus = selectedCheckName ? "all" : statusFilter;
    setResultsLoading(true);
    skillReadinessApi
      .getSkillReadinessResults(runId, {
        page,
        page_size: pageSize,
        status: effectiveStatus,
        check_name: selectedCheckName || undefined,
        check_status: selectedCheckName ? "fail" : undefined,
      })
      .then((data) => {
        if (!cancelled) {
          setResults(data);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          message.error(getErrorText(error, "加载检查结果失败"));
          setResults(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setResultsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    open,
    overview?.latest_run?.run_id,
    page,
    pageSize,
    resultsRefreshToken,
    selectedCheckName,
    statusFilter,
  ]);

  const refreshReadiness = useCallback(() => {
    void loadOverview();
    setResultsRefreshToken((current) => current + 1);
  }, [loadOverview]);

  const startRun = useCallback(async () => {
    if (!target.valid || !overview) {
      return;
    }

    setStarting(true);
    try {
      const response = await skillReadinessApi.startSkillReadinessRun(
        target.skillId,
      );
      if (activeSkillRef.current !== target.skillId) {
        return;
      }
      if (response.owner_lookup_only) {
        message.success(
          response.owner_lookup_scheduled
            ? "已开始查询用户"
            : "已有用户查询正在运行",
        );
        setOverview((current) =>
          current && current.skill_id === target.skillId
            ? {
                ...current,
                owner_lookup_status: "running",
              }
            : current,
        );
        setResults(null);
        return;
      }
      if (!response.run) {
        await loadOverview();
        return;
      }
      message.success(response.reused ? "已有检查正在运行" : "已开始查询用户并检查");
      setOverview((current) =>
        current && current.skill_id === target.skillId
          ? {
              ...current,
              latest_run: {
                ...response.run,
                check_summaries: current.latest_run?.check_summaries ?? [],
              },
            }
          : current,
      );
      setPage(1);
      setStatusFilter("all");
      setSelectedCheckName(null);
      await loadOverview();
    } catch (error) {
      message.error(getErrorText(error, "启动检查失败"));
    } finally {
      setStarting(false);
    }
  }, [loadOverview, overview, target.skillId, target.valid]);

  const activeRun = results?.run || overview?.latest_run || null;
  const ownerSummary = overview?.owner_summary ?? DEFAULT_OWNER_SUMMARY;
  const configChecks = overview?.config_checks ?? [];
  const ownerRows = overview?.owners ?? [];
  const ownerLookupRunning = overview?.owner_lookup_status === "running";
  const ownerLookupIdle = overview?.owner_lookup_status === "idle";
  const startButtonText = overview?.startable ? "查询用户并检查" : "查询用户";
  let ownerLookupDataTime = "-";
  if (ownerLookupRunning) {
    ownerLookupDataTime = "正在生成中";
  } else if (ownerLookupIdle) {
    ownerLookupDataTime = "查询用户后生成";
  }
  if (overview?.owner_lookup_updated_at) {
    ownerLookupDataTime = `${formatDateTime(overview.owner_lookup_updated_at)}${
      ownerLookupRunning ? "（检查中）" : ""
    }`;
  }
  let ownerEmptyText = "当前没有查询到分配用户";
  if (ownerLookupRunning) {
    ownerEmptyText = "正在生成中";
  } else if (ownerLookupIdle) {
    ownerEmptyText = "查询用户后生成拥有用户";
  }

  const ownerColumns = [
    {
      title: "用户",
      dataIndex: "user_name",
      key: "user_name",
      render: (_value: string | null, record: SkillReadinessOwner) => (
        <div style={{ display: "grid", gap: 2 }}>
          <Text strong>{record.user_name || record.user_id}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.user_id}
          </Text>
        </div>
      ),
    },
    {
      title: "机构",
      dataIndex: "bbk_id",
      key: "bbk_id",
      render: (value: string | null) => value || "-",
    },
    {
      title: "技能目录",
      dataIndex: "skill_name",
      key: "skill_name",
      render: renderNullableText,
    },
    {
      title: "市场版本",
      dataIndex: "market_version",
      key: "market_version",
      render: renderNullableText,
    },
    {
      title: "用户版本",
      dataIndex: "installed_version",
      key: "installed_version",
      render: renderNullableText,
    },
    {
      title: "状态",
      dataIndex: "enabled",
      key: "enabled",
      render: renderEnabledTag,
    },
    {
      title: "版本",
      dataIndex: "has_update",
      key: "has_update",
      render: renderUpdateTag,
    },
  ];

  const runSummary = activeRun ? (
    <div
      style={{
        border: "1px solid #f0f0f0",
        borderRadius: 8,
        padding: 12,
        backgroundColor: "#fff",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 10,
        }}
      >
        <Space size={8} wrap>
          <Text strong>最近一次检查</Text>
          <Text code>{activeRun.run_id}</Text>
          <Tag color={runStatusColor(activeRun.status)}>
            {STATUS_LABELS[activeRun.status]}
          </Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {formatDateTime(activeRun.updated_at || activeRun.started_at)}
          </Text>
        </Space>
        <Text type="secondary" style={{ fontSize: 12 }}>
          总用户 {activeRun.total_users} · 已完成 {activeRun.completed_users} · 失败{" "}
          {activeRun.failed_users}
        </Text>
      </div>
      <Progress
        percent={runProgressPercent(activeRun)}
        size="small"
        status={activeRun.status === "failed" ? "exception" : "active"}
      />
      {activeRun.failure_summary && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 10 }}
          message={activeRun.failure_summary}
        />
      )}
    </div>
  ) : (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有检查记录" />
  );

  const checkSummary = overview?.latest_run?.check_summaries.length ? (
    <Space size={[8, 8]} wrap>
      {overview.latest_run.check_summaries.map((summary) => {
        const selected = selectedCheckName === summary.check_name;
        return (
          <Button
            key={summary.check_name}
            size="small"
            type={selected ? "primary" : "default"}
            danger={summary.fail_count > 0}
            onClick={() => {
              setSelectedCheckName(selected ? null : summary.check_name);
              setStatusFilter("all");
              setPage(1);
            }}
          >
            {summary.display_name} · fail {summary.fail_count}
          </Button>
        );
      })}
    </Space>
  ) : (
    <Text type="secondary" style={{ fontSize: 12 }}>
      暂无检查项统计
    </Text>
  );

  const configPanel = (
    <div>
      <Text strong>自检配置</Text>
      <div style={{ marginTop: 8 }}>
        {configChecks.length ? (
          <Space size={[8, 8]} wrap>
            {configChecks.map(renderConfigTag)}
          </Space>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            没有自检配置
          </Text>
        )}
      </div>
    </div>
  );

  const resultsContent = (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <Space direction="vertical" size={4}>
          <Text strong>检查结果</Text>
          {activeRun && selectedCheckName && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              当前仅展示该检查项失败的用户。
            </Text>
          )}
        </Space>
        {activeRun && !selectedCheckName && (
          <Segmented
            value={statusFilter}
            options={[
              { label: "全部", value: "all" },
              { label: "异常", value: "abnormal" },
              { label: "正常", value: "normal" },
            ]}
            onChange={(value) => {
              setStatusFilter(value as UserStatusFilter);
              setPage(1);
            }}
          />
        )}
      </div>

      {runSummary}

      {activeRun && (
        <>
          <div>{checkSummary}</div>

          <Spin spinning={resultsLoading}>
            {!results || results.items.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="当前筛选条件下没有结果"
              />
            ) : (
              <Space direction="vertical" size={10} style={{ width: "100%" }}>
                {selectedCheckName ? (
                  results.items.map((user) =>
                    renderSelectedCheckUserResult(user, selectedCheckName),
                  )
                ) : (
                  <Collapse
                    size="small"
                    items={results.items.map((user) => ({
                      key: user.user_id,
                      label: renderUserOverviewLabel(user),
                      children: (
                        <Space
                          direction="vertical"
                          size={8}
                          style={{ width: "100%" }}
                        >
                          {user.summary && (
                            <Text
                              type={
                                user.aggregate_status === "abnormal"
                                  ? "danger"
                                  : "secondary"
                              }
                              style={{
                                display: "block",
                                fontSize: 12,
                              }}
                            >
                              {user.summary}
                            </Text>
                          )}
                          <Space
                            direction="vertical"
                            size={8}
                            style={{ width: "100%" }}
                          >
                            {user.checks.map(renderCheckResult)}
                          </Space>
                        </Space>
                      ),
                    }))}
                  />
                )}
                <Pagination
                  size="small"
                  current={page}
                  pageSize={pageSize}
                  total={results.total}
                  showSizeChanger
                  showTotal={(total) => `共 ${total} 条`}
                  onChange={(nextPage, nextPageSize) => {
                    setPage(nextPage);
                    setPageSize(nextPageSize);
                  }}
                />
              </Space>
            )}
          </Spin>
        </>
      )}
    </Space>
  );

  return (
    <Modal
      open={open}
      title={
        <Space size={8} wrap>
          <SafetyCertificateOutlined />
          <span>用户可执行性</span>
          {target.displayName && <Text type="secondary">{target.displayName}</Text>}
        </Space>
      }
      width={1040}
      onCancel={overviewLoading || starting ? undefined : onClose}
      destroyOnClose
      footer={[
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          loading={overviewLoading || resultsLoading}
          disabled={!target.valid}
          onClick={refreshReadiness}
        >
          刷新
        </Button>,
        <Button
          key="start"
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={starting}
          disabled={!target.valid || !overview}
          onClick={startRun}
        >
          {startButtonText}
        </Button>,
        <Button
          key="close"
          disabled={overviewLoading || starting}
          onClick={onClose}
        >
          关闭
        </Button>,
      ]}
    >
      <Space direction="vertical" size={14} style={{ width: "100%" }}>
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <Text type="secondary">当前 skill-id</Text>
          <Text code copyable={target.skillId ? { text: target.skillId } : false}>
            {target.skillId || "-"}
          </Text>
          <Tag color={target.idSource === "skill_id" ? "blue" : "gold"}>
            {target.idSource === "skill_id" ? "来自 skill_id" : "按 skill_name 降级"}
          </Tag>
          {overview && (
            <Tag color={overview.config_found ? "green" : "default"}>
              {overview.config_found ? "已查询到自检配置" : "未查询到自检配置"}
            </Tag>
          )}
        </div>

        {!target.valid && (
          <Alert
            type="error"
            showIcon
            message="当前技能没有可用于查询的有效 skill-id"
            description="skill-id 仅支持中文、字母、数字、下划线、点、冒号和短横线；没有 skill_id 时会降级使用 skill_name。"
          />
        )}
        <Spin spinning={overviewLoading}>
          {overview ? (
            <Space direction="vertical" size={14} style={{ width: "100%" }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: 10,
                }}
              >
                <div
                  style={{
                    border: "1px solid #f0f0f0",
                    borderRadius: 8,
                    padding: 12,
                    backgroundColor: "#fff",
                  }}
                >
                  <Text type="secondary">拥有用户</Text>
                  <Title level={4} style={{ margin: "4px 0 0" }}>
                    {ownerSummary.total_users}
                  </Title>
                </div>
                <div
                  style={{
                    border: "1px solid #f0f0f0",
                    borderRadius: 8,
                    padding: 12,
                    backgroundColor: "#fff",
                  }}
                >
                  <Text type="secondary">用户查询失败</Text>
                  <Title level={4} style={{ margin: "4px 0 0" }}>
                    {ownerSummary.lookup_failed_users}
                  </Title>
                </div>
                <div
                  style={{
                    border: "1px solid #f0f0f0",
                    borderRadius: 8,
                    padding: 12,
                    backgroundColor: "#fff",
                  }}
                >
                  <Text type="secondary">配置检查项</Text>
                  <Title level={4} style={{ margin: "4px 0 0" }}>
                    {configChecks.filter((item) => item.enabled).length}
                    <Text type="secondary" style={{ fontSize: 13 }}>
                      {" "}
                      / {configChecks.length}
                    </Text>
                  </Title>
                </div>
              </div>

              {ownerSummary.failure_summary && (
                <Alert
                  type="warning"
                  showIcon
                  message={ownerSummary.failure_summary}
                />
              )}

              {configPanel}

              <div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <Text strong>拥有用户</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    数据时间：{ownerLookupDataTime}
                  </Text>
                </div>
                <Table
                  rowKey="user_id"
                  size="small"
                  style={{ marginTop: 8 }}
                  dataSource={ownerRows}
                  pagination={{
                    pageSize: 5,
                    showSizeChanger: true,
                    pageSizeOptions: [5, 10, 20, 50],
                    showTotal: (total) => `共 ${total} 个用户`,
                  }}
                  columns={ownerColumns}
                  locale={{
                    emptyText: ownerEmptyText,
                  }}
                  scroll={{ x: 900 }}
                />
              </div>

              {resultsContent}
            </Space>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                target.valid ? "暂无可执行性数据" : "等待有效 skill-id"
              }
            />
          )}
        </Spin>
      </Space>
    </Modal>
  );
}
