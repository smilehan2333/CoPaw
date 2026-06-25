import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Modal,
  Select,
  Segmented,
  Space,
  Table,
  Tabs,
  Tag,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import {
  AlertTriangle,
  Archive,
  BarChart3,
  Clock3,
  Database,
  FileText,
  HardDriveDownload,
  Search,
  ShieldCheck,
  Timer,
  UserCheck,
  Users,
  UserX,
} from "lucide-react";
import { dreamLogsApi } from "../../../api/modules/dreamLogs";
import { fetchBbkBySource, type BbkInfo } from "../../../api/modules/userInfo";
import type {
  ArchiveAdminAuditRecord,
  ArchiveItem,
  ArchiveReportResponse,
  DreamLogReportBbkBucket,
  DreamLogReportParams,
  DreamLogReportRecord,
  DreamLogReportResponse,
  DreamLogReportStatusBucket,
  DreamLogReportTrendPoint,
  DreamLogReportUserRow,
  ProtectedFileInfo,
  ReconcileHealthInfo,
} from "../../../api/types/dreamLogs";
import { BBK_ID_MAP, getBbkDisplayName } from "../../../constants/bbk";
import { DEFAULT_SOURCE_ID } from "../../../constants/identity";
import { useIframeStore } from "../../../stores/iframeStore";
import styles from "./index.module.less";

const { RangePicker } = DatePicker;
const DEFAULT_AGENT_ID = "default";
const FILE_DETAIL_DEFAULT_PAGE_SIZE = 10;

type DateRange = [Dayjs, Dayjs] | null;
type ActiveTab = "governance" | "files";
type DateShortcutKey = "today" | "last7" | "lastMonth";

const DATE_SHORTCUT_OPTIONS: Array<{
  label: string;
  value: DateShortcutKey;
}> = [
  { label: "今天", value: "today" },
  { label: "近七天", value: "last7" },
  { label: "近一个月", value: "lastMonth" },
];

interface FilterDraft {
  dateRange: DateRange;
  bbk_id?: string;
  user_search?: string;
  status?: string;
  trigger?: string;
  agent_id?: string;
}

interface KpiConfig {
  key: string;
  label: string;
  value: string;
  accent: string;
  icon: typeof Users;
}

interface BbkOption {
  label: string;
  value: string;
}

const STATUS_COLORS: Record<string, string> = {
  success: "green",
  failed: "red",
  rollback: "gold",
  unknown: "default",
};

const STATUS_TEXT: Record<string, string> = {
  success: "成功",
  failed: "失败",
  rollback: "已回退",
  unknown: "未知",
};

const TRIGGER_TEXT: Record<string, string> = {
  manual: "手动",
  cron: "定时",
};

const AUDIT_OPERATION_TEXT: Record<string, string> = {
  purge_archive: "手动清理",
  auto_purge_archive: "自动清理",
};

const AUDIT_STATUS_COLORS: Record<string, string> = {
  success: "green",
  failed: "red",
  partial_success: "gold",
};

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value || 0);
}

function formatBytes(value: number): string {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function formatDuration(value: number): string {
  if (!value) return "0ms";
  if (value < 1000) return `${value}ms`;
  if (value < 60000) return `${(value / 1000).toFixed(1)}s`;
  return `${(value / 60000).toFixed(1)}min`;
}

function formatPercent(value: number): string {
  const rounded = Number(value || 0);
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(2)}%`;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD HH:mm") : value;
}

function buildParams(
  draft: FilterDraft,
  page: number,
  pageSize: number,
): DreamLogReportParams {
  return {
    start_time: draft.dateRange?.[0]?.format("YYYY-MM-DD"),
    end_time: draft.dateRange?.[1]?.format("YYYY-MM-DD"),
    bbk_id: draft.bbk_id,
    user_search: draft.user_search?.trim() || undefined,
    status: draft.status,
    trigger: draft.trigger,
    agent_id: draft.agent_id?.trim() || undefined,
    page,
    page_size: pageSize,
  };
}

function buildDefaultDraft(): FilterDraft {
  return {
    dateRange: [dayjs().subtract(30, "day"), dayjs()],
    agent_id: DEFAULT_AGENT_ID,
  };
}

function buildDateShortcutRange(shortcut: DateShortcutKey): [Dayjs, Dayjs] {
  const today = dayjs();
  if (shortcut === "today") {
    return [today, today];
  }
  if (shortcut === "last7") {
    return [today.subtract(6, "day"), today];
  }
  return [today.subtract(30, "day"), today];
}

function getActiveDateShortcut(
  dateRange: DateRange,
): DateShortcutKey | undefined {
  if (!dateRange) return undefined;
  return DATE_SHORTCUT_OPTIONS.find(({ value }) => {
    const [start, end] = buildDateShortcutRange(value);
    return (
      dateRange[0].isSame(start, "day") && dateRange[1].isSame(end, "day")
    );
  })?.value;
}

function buildFileGovernanceParams(
  params: DreamLogReportParams,
): Record<string, unknown> {
  const next: Record<string, unknown> = {};
  if (params.bbk_id) next.bbk_id = params.bbk_id;
  if (params.user_search) next.user_search = params.user_search;
  if (params.agent_id) next.target_agent_id = params.agent_id;
  return next;
}

function buildBbkOptions(items: BbkInfo[]): BbkOption[] {
  const seen = new Set<string>();
  const options = items.reduce<BbkOption[]>((acc, item) => {
    const value = item.bbk_id?.trim();
    if (!value || seen.has(value)) {
      return acc;
    }
    seen.add(value);
    acc.push({
      value,
      label: item.bbk_name?.trim() || getBbkDisplayName(value),
    });
    return acc;
  }, []);
  return options.length ? options : BBK_ID_MAP;
}

function KpiCard({ item }: { item: KpiConfig }) {
  const Icon = item.icon;
  return (
    <div
      className={styles.kpiCard}
      style={{ borderTopColor: item.accent }}
      data-testid={`governance-kpi-${item.key}`}
    >
      <div className={styles.kpiHeader}>
        <span className={styles.kpiIcon} style={{ color: item.accent }}>
          <Icon size={18} />
        </span>
        <span className={styles.kpiLabel}>{item.label}</span>
      </div>
      <div className={styles.kpiValue}>{item.value}</div>
    </div>
  );
}

function HealthPanel({
  title,
  items,
  testId,
}: {
  title: string;
  items: ReconcileHealthInfo[];
  testId: string;
}) {
  if (!items.length) return null;
  return (
    <section className={styles.healthPanel} data-testid={testId}>
      <div className={styles.panelHeader}>
        <span>{title}</span>
        <Tag color="orange">{items.length}</Tag>
      </div>
      <div className={styles.healthList}>
        {items.map((item) => (
          <div
            key={`${item.entity_type}:${item.entity_id}`}
            className={styles.healthRow}
            data-testid={`health-row-${item.entity_type}-${item.entity_id}`}
          >
            <Tag color={item.status === "failed" ? "red" : "orange"}>
              {item.status}
            </Tag>
            <span className={styles.healthEntity}>
              {item.entity_type} / {item.entity_id}
            </span>
            <span className={styles.healthReason}>{item.reason}</span>
            <span className={styles.healthTime}>
              {formatDateTime(item.updated_at)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

const TREND_CHART_WIDTH = 360;
const TREND_CHART_HEIGHT = 170;
const TREND_CHART_MARGIN = {
  top: 18,
  right: 14,
  bottom: 30,
  left: 42,
};

function getChartTicks(maxValue: number): number[] {
  const upper = Math.max(maxValue, 1);
  return [0, Math.ceil(upper / 2), upper].filter(
    (value, index, values) => values.indexOf(value) === index,
  );
}

function getChartX(index: number, count: number): number {
  const plotWidth =
    TREND_CHART_WIDTH - TREND_CHART_MARGIN.left - TREND_CHART_MARGIN.right;
  if (count === 1) {
    return TREND_CHART_MARGIN.left + plotWidth / 2;
  }
  return TREND_CHART_MARGIN.left + (plotWidth * index) / (count - 1);
}

function getChartY(value: number, maxValue: number): number {
  const plotHeight =
    TREND_CHART_HEIGHT - TREND_CHART_MARGIN.top - TREND_CHART_MARGIN.bottom;
  return (
    TREND_CHART_MARGIN.top + plotHeight * (1 - value / Math.max(maxValue, 1))
  );
}

function TrendChart({ data }: { data: DreamLogReportTrendPoint[] }) {
  if (!data.length) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无趋势数据" />
    );
  }

  const maxValue = Math.max(...data.map((item) => item.executions), 1);
  const ticks = getChartTicks(maxValue);
  const axisBottom = TREND_CHART_HEIGHT - TREND_CHART_MARGIN.bottom;
  const barSlotWidth =
    data.length === 1
      ? TREND_CHART_WIDTH - TREND_CHART_MARGIN.left - TREND_CHART_MARGIN.right
      : (TREND_CHART_WIDTH -
          TREND_CHART_MARGIN.left -
          TREND_CHART_MARGIN.right) /
        data.length;
  const barWidth = Math.min(34, Math.max(18, barSlotWidth * 0.46));

  return (
    <div className={styles.trendWrap}>
      <svg
        className={styles.trendSvg}
        viewBox={`0 0 ${TREND_CHART_WIDTH} ${TREND_CHART_HEIGHT}`}
        aria-hidden="true"
      >
        {ticks.map((tick) => {
          const y = getChartY(tick, maxValue);
          return (
            <g key={tick}>
              <line
                className={styles.chartGridLine}
                x1={TREND_CHART_MARGIN.left}
                y1={y}
                x2={TREND_CHART_WIDTH - TREND_CHART_MARGIN.right}
                y2={y}
              />
              <text className={styles.chartYAxisLabel} x={34} y={y + 4}>
                {formatNumber(tick)}
              </text>
            </g>
          );
        })}
        <line
          className={styles.chartAxisLine}
          x1={TREND_CHART_MARGIN.left}
          y1={axisBottom}
          x2={TREND_CHART_WIDTH - TREND_CHART_MARGIN.right}
          y2={axisBottom}
        />
        <line
          className={styles.chartAxisLine}
          x1={TREND_CHART_MARGIN.left}
          y1={TREND_CHART_MARGIN.top}
          x2={TREND_CHART_MARGIN.left}
          y2={axisBottom}
        />
        {data.map((item, index) => {
          const cronCount = item.cron_count ?? 0;
          const manualCount =
            item.manual_count ?? Math.max(item.executions - cronCount, 0);
          const x = getChartX(index, data.length);
          const totalY = getChartY(item.executions, maxValue);
          const manualY = getChartY(manualCount, maxValue);
          const autoHeight = Math.max(manualY - totalY, 0);
          const manualHeight = Math.max(axisBottom - manualY, 0);
          return (
            <g key={item.date}>
              <title>{`共 ${item.executions} 次，手动 ${manualCount} 次，自动 ${cronCount} 次`}</title>
              {manualCount > 0 && (
                <rect
                  className={styles.trendBarManual}
                  x={x - barWidth / 2}
                  y={manualY}
                  width={barWidth}
                  height={manualHeight}
                  rx="4"
                />
              )}
              {cronCount > 0 && (
                <rect
                  className={styles.trendBarAuto}
                  x={x - barWidth / 2}
                  y={totalY}
                  width={barWidth}
                  height={autoHeight}
                  rx="4"
                />
              )}
              <text className={styles.chartXAxisLabel} x={x} y={158}>
                {dayjs(item.date).format("MM-DD")}
              </text>
            </g>
          );
        })}
      </svg>
      <div className={styles.trendLegend}>
        <span>
          <i className={styles.trendLegendManual} />
          手动
        </span>
        <span>
          <i className={styles.trendLegendAuto} />
          自动
        </span>
      </div>
    </div>
  );
}

function SavingsLineChart({ data }: { data: DreamLogReportTrendPoint[] }) {
  if (!data.length) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无节省空间数据" />
    );
  }

  const maxValue = Math.max(...data.map((item) => item.total_size_saved), 1);
  const ticks = getChartTicks(maxValue);
  const axisBottom = TREND_CHART_HEIGHT - TREND_CHART_MARGIN.bottom;
  const points = data.map((item, index) => ({
    x: getChartX(index, data.length),
    y: getChartY(item.total_size_saved, maxValue),
    item,
  }));
  const pointPath = points.map((point) => `${point.x},${point.y}`).join(" ");

  return (
    <div className={styles.savingsChart}>
      <svg
        className={styles.savingsLineSvg}
        viewBox={`0 0 ${TREND_CHART_WIDTH} ${TREND_CHART_HEIGHT}`}
        aria-hidden="true"
      >
        {ticks.map((tick) => {
          const y = getChartY(tick, maxValue);
          return (
            <g key={tick}>
              <line
                className={styles.chartGridLine}
                x1={TREND_CHART_MARGIN.left}
                y1={y}
                x2={TREND_CHART_WIDTH - TREND_CHART_MARGIN.right}
                y2={y}
              />
              <text className={styles.chartYAxisLabel} x={34} y={y + 4}>
                {formatBytes(tick)}
              </text>
            </g>
          );
        })}
        <line
          className={styles.chartAxisLine}
          x1={TREND_CHART_MARGIN.left}
          y1={axisBottom}
          x2={TREND_CHART_WIDTH - TREND_CHART_MARGIN.right}
          y2={axisBottom}
        />
        <line
          className={styles.chartAxisLine}
          x1={TREND_CHART_MARGIN.left}
          y1={TREND_CHART_MARGIN.top}
          x2={TREND_CHART_MARGIN.left}
          y2={axisBottom}
        />
        <polyline className={styles.savingsLine} points={pointPath} />
        {points.map((point) => (
          <g key={point.item.date}>
            <title>{`${dayjs(point.item.date).format("MM-DD")} 节省 ${formatBytes(
              point.item.total_size_saved,
            )}`}</title>
            <circle
              className={styles.savingsPoint}
              cx={point.x}
              cy={point.y}
              r="3"
            />
            <text className={styles.chartXAxisLabel} x={point.x} y={158}>
              {dayjs(point.item.date).format("MM-DD")}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function StatusChart({ data }: { data: DreamLogReportStatusBucket[] }) {
  const total = Math.max(
    data.reduce((sum, item) => sum + item.count, 0),
    1,
  );
  if (!data.length) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无状态数据" />
    );
  }
  return (
    <div className={styles.distributionList}>
      {data.map((item) => (
        <div key={item.status} className={styles.distributionRow}>
          <span className={styles.distributionName}>
            {STATUS_TEXT[item.status] || item.status}
          </span>
          <div className={styles.distributionTrack}>
            <div
              className={styles.distributionBar}
              style={{ width: `${(item.count / total) * 100}%` }}
            />
          </div>
          <span className={styles.distributionValue}>{item.count}</span>
        </div>
      ))}
    </div>
  );
}

function BbkChart({
  data,
  getBbkName,
}: {
  data: DreamLogReportBbkBucket[];
  getBbkName: (bbkId?: string) => string;
}) {
  const maxValue = Math.max(...data.map((item) => item.executions), 1);
  if (!data.length) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无机构数据" />
    );
  }
  return (
    <div
      className={`${styles.distributionList} ${styles.distributionListScrollable}`}
    >
      {data.map((item) => (
        <div key={item.bbk_id} className={styles.distributionRow}>
          <span className={styles.distributionName}>
            {getBbkName(item.bbk_id)}
          </span>
          <div className={styles.distributionTrack}>
            <div
              className={styles.bbkBar}
              style={{ width: `${(item.executions / maxValue) * 100}%` }}
            />
          </div>
          <span className={styles.distributionValue}>{item.executions}</span>
        </div>
      ))}
    </div>
  );
}

export default function ContinuousGovernancePage() {
  const sourceId = useIframeStore((state) => state.source) || DEFAULT_SOURCE_ID;
  const [activeTab, setActiveTab] = useState<ActiveTab>("governance");
  const [draft, setDraft] = useState<FilterDraft>(() => buildDefaultDraft());
  const [query, setQuery] = useState<DreamLogReportParams>(() =>
    buildParams(buildDefaultDraft(), 1, 20),
  );
  const [report, setReport] = useState<DreamLogReportResponse | null>(null);
  const [archiveReport, setArchiveReport] =
    useState<ArchiveReportResponse | null>(null);
  const [archiveItems, setArchiveItems] = useState<ArchiveItem[]>([]);
  const [archiveTotal, setArchiveTotal] = useState(0);
  const [archivePage, setArchivePage] = useState(1);
  const [archivePageSize, setArchivePageSize] = useState(
    FILE_DETAIL_DEFAULT_PAGE_SIZE,
  );
  const [protectedFiles, setProtectedFiles] = useState<ProtectedFileInfo[]>([]);
  const [protectedTotal, setProtectedTotal] = useState(0);
  const [protectedPage, setProtectedPage] = useState(1);
  const [protectedPageSize, setProtectedPageSize] = useState(
    FILE_DETAIL_DEFAULT_PAGE_SIZE,
  );
  const [adminAudits, setAdminAudits] = useState<ArchiveAdminAuditRecord[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditPageSize, setAuditPageSize] = useState(
    FILE_DETAIL_DEFAULT_PAGE_SIZE,
  );
  const [archiveLoaded, setArchiveLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedUser, setSelectedUser] =
    useState<DreamLogReportUserRow | null>(null);
  const [recordLoading, setRecordLoading] = useState(false);
  const [records, setRecords] = useState<DreamLogReportRecord[]>([]);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [recordsPage, setRecordsPage] = useState(1);
  const [recordsPageSize, setRecordsPageSize] = useState(10);
  const [detailRecord, setDetailRecord] =
    useState<DreamLogReportRecord | null>(null);
  const [bbkOptions, setBbkOptions] = useState<BbkOption[]>(BBK_ID_MAP);

  const fetchReport = useCallback(async (params: DreamLogReportParams) => {
    setLoading(true);
    try {
      const data = await dreamLogsApi.report(params);
      setReport(data);
    } catch (error) {
      console.error("Failed to fetch continuous governance report:", error);
      message.error("持续治理分析加载失败");
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchArchiveData = useCallback(async () => {
    setArchiveLoading(true);
    try {
      const fileParams = buildFileGovernanceParams(query);
      const [reportData, itemsData, protectedData, auditsData] =
        await Promise.all([
          dreamLogsApi.archiveReport(fileParams),
          dreamLogsApi.listArchiveItems({
            ...fileParams,
            page: archivePage,
            page_size: archivePageSize,
          }),
          dreamLogsApi.listProtectedFiles({
            ...fileParams,
            page: protectedPage,
            page_size: protectedPageSize,
          }),
          dreamLogsApi.listArchiveAdminAudits({
            ...fileParams,
            page: auditPage,
            page_size: auditPageSize,
          }),
        ]);
      setArchiveReport(reportData);
      setArchiveItems(itemsData.items || []);
      setArchiveTotal(itemsData.total || 0);
      setArchivePage(itemsData.page || archivePage);
      setArchivePageSize(itemsData.page_size || archivePageSize);
      setProtectedFiles(protectedData.items || []);
      setProtectedTotal(protectedData.total || 0);
      setProtectedPage(protectedData.page || protectedPage);
      setProtectedPageSize(protectedData.page_size || protectedPageSize);
      setAdminAudits(auditsData.items || []);
      setAuditTotal(auditsData.total || 0);
      setAuditPage(auditsData.page || auditPage);
      setAuditPageSize(auditsData.page_size || auditPageSize);
      setArchiveLoaded(true);
    } catch (error) {
      console.error("Failed to fetch file governance report:", error);
      message.error("文件清理与归档加载失败");
      setArchiveReport(null);
      setArchiveItems([]);
      setArchiveTotal(0);
      setProtectedFiles([]);
      setProtectedTotal(0);
      setAdminAudits([]);
      setAuditTotal(0);
    } finally {
      setArchiveLoading(false);
    }
  }, [
    archivePage,
    archivePageSize,
    auditPage,
    auditPageSize,
    protectedPage,
    protectedPageSize,
    query,
  ]);

  useEffect(() => {
    let cancelled = false;

    async function loadBbkOptions() {
      const items = await fetchBbkBySource(sourceId);
      if (!cancelled) {
        setBbkOptions(buildBbkOptions(items));
      }
    }

    void loadBbkOptions();
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  useEffect(() => {
    void fetchReport(query);
  }, [fetchReport, query]);

  useEffect(() => {
    setArchivePage(1);
    setProtectedPage(1);
    setAuditPage(1);
    setArchiveLoaded(false);
  }, [query]);

  useEffect(() => {
    if (activeTab === "files" && !archiveLoaded) {
      void fetchArchiveData();
    }
  }, [activeTab, archiveLoaded, fetchArchiveData]);

  const loadUserRecords = useCallback(
    async (user: DreamLogReportUserRow, page: number, pageSize: number) => {
      setRecordLoading(true);
      try {
        const data = await dreamLogsApi.reportUserRecords(user.user_id, {
          ...query,
          page,
          page_size: pageSize,
        });
        setRecords(data.records || []);
        setRecordsTotal(data.total || 0);
        setRecordsPage(data.page || page);
        setRecordsPageSize(data.page_size || pageSize);
      } catch (error) {
        console.error("Failed to fetch governance records:", error);
        message.error("用户治理记录加载失败");
      } finally {
        setRecordLoading(false);
      }
    },
    [query],
  );

  const kpis = useMemo<KpiConfig[]>(() => {
    const summary = report?.summary;
    return [
      {
        key: "covered_users",
        label: "覆盖用户",
        value: formatNumber(summary?.covered_users ?? 0),
        accent: "#2563eb",
        icon: Users,
      },
      {
        key: "governed_users",
        label: "已治理用户",
        value: formatNumber(summary?.governed_users ?? 0),
        accent: "#16a34a",
        icon: UserCheck,
      },
      {
        key: "ungoverned_users",
        label: "未治理用户",
        value: formatNumber(summary?.ungoverned_users ?? 0),
        accent: "#f97316",
        icon: UserX,
      },
      {
        key: "total_executions",
        label: "总执行次数",
        value: formatNumber(summary?.total_executions ?? 0),
        accent: "#0f766e",
        icon: Database,
      },
      {
        key: "success_rate",
        label: "成功率",
        value: formatPercent(summary?.success_rate ?? 0),
        accent: "#0891b2",
        icon: BarChart3,
      },
      {
        key: "failed_count",
        label: "失败次数",
        value: formatNumber(summary?.failed_count ?? 0),
        accent: "#dc2626",
        icon: AlertTriangle,
      },
      {
        key: "total_files_changed",
        label: "变更文件数",
        value: formatNumber(summary?.total_files_changed ?? 0),
        accent: "#7c3aed",
        icon: FileText,
      },
      {
        key: "total_size_saved",
        label: "节省空间",
        value: formatBytes(summary?.total_size_saved ?? 0),
        accent: "#4f46e5",
        icon: HardDriveDownload,
      },
      {
        key: "avg_duration_ms",
        label: "平均耗时",
        value: formatDuration(summary?.avg_duration_ms ?? 0),
        accent: "#ca8a04",
        icon: Timer,
      },
      {
        key: "last_execution",
        label: "最近治理时间",
        value: formatDateTime(summary?.last_execution),
        accent: "#334155",
        icon: Clock3,
      },
    ];
  }, [report]);

  const archiveKpis = useMemo<KpiConfig[]>(() => {
    const summary = archiveReport?.summary;
    return [
      {
        key: "archive_files",
        label: "归档文件",
        value: formatNumber(summary?.archived_files ?? 0),
        accent: "#0d9488",
        icon: Archive,
      },
      {
        key: "protected_files",
        label: "保护文件",
        value: formatNumber(summary?.protected_files ?? 0),
        accent: "#0284c7",
        icon: ShieldCheck,
      },
      {
        key: "pending_purge_files",
        label: "待清理文件",
        value: formatNumber(summary?.pending_purge_files ?? 0),
        accent: "#ea580c",
        icon: AlertTriangle,
      },
      {
        key: "purged_size_bytes",
        label: "归档释放空间",
        value: formatBytes(summary?.purged_size_bytes ?? 0),
        accent: "#059669",
        icon: HardDriveDownload,
      },
    ];
  }, [archiveReport]);

  const bbkNameMap = useMemo(
    () =>
      bbkOptions.reduce<Record<string, string>>((acc, item) => {
        acc[item.value] = item.label;
        return acc;
      }, {}),
    [bbkOptions],
  );

  const formatBbkName = useCallback(
    (bbkId?: string) => {
      if (!bbkId) return "-";
      if (bbkId === "other" || bbkId === "unassigned") return "其他";
      return bbkNameMap[bbkId] || getBbkDisplayName(bbkId);
    },
    [bbkNameMap],
  );

  const userColumns: ColumnsType<DreamLogReportUserRow> = [
    {
      title: "用户 ID",
      dataIndex: "user_id",
      key: "user_id",
      fixed: "left",
      width: 160,
    },
    {
      title: "姓名",
      dataIndex: "user_name",
      key: "user_name",
      width: 120,
      render: (value) => value || "-",
    },
    {
      title: "机构",
      dataIndex: "bbk_id",
      key: "bbk_id",
      width: 150,
      render: (value) => formatBbkName(value),
    },
    {
      title: "执行次数",
      dataIndex: "executions",
      key: "executions",
      width: 100,
    },
    {
      title: "成功率",
      dataIndex: "success_rate",
      key: "success_rate",
      width: 100,
      render: (value: number) => formatPercent(value),
    },
    {
      title: "失败次数",
      dataIndex: "failed_count",
      key: "failed_count",
      width: 100,
    },
    {
      title: "文件数",
      dataIndex: "total_files_changed",
      key: "total_files_changed",
      width: 100,
    },
    {
      title: "节省空间",
      dataIndex: "total_size_saved",
      key: "total_size_saved",
      width: 110,
      render: (value: number) => formatBytes(value),
    },
    {
      title: "最近治理",
      dataIndex: "last_execution",
      key: "last_execution",
      width: 160,
      render: (value) => formatDateTime(value),
    },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 90,
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          aria-label={`查看 ${record.user_id}`}
          onClick={() => {
            setSelectedUser(record);
            setDrawerOpen(true);
            setRecords([]);
            void loadUserRecords(record, 1, 10);
          }}
        >
          查看
        </Button>
      ),
    },
  ];

  const recordColumns: ColumnsType<DreamLogReportRecord> = [
    {
      title: "任务 ID",
      dataIndex: "id",
      key: "id",
      width: 160,
    },
    {
      title: "时间",
      dataIndex: "timestamp",
      key: "timestamp",
      width: 160,
      render: (value) => formatDateTime(value),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 90,
      render: (value: string) => (
        <Tag color={STATUS_COLORS[value] || "default"}>
          {STATUS_TEXT[value] || value}
        </Tag>
      ),
    },
    {
      title: "触发方式",
      dataIndex: "trigger",
      key: "trigger",
      width: 100,
      render: (value: string) => TRIGGER_TEXT[value] || value || "-",
    },
    {
      title: "文件数",
      dataIndex: "total_files_changed",
      key: "total_files_changed",
      width: 90,
    },
    {
      title: "节省空间",
      dataIndex: "total_size_saved",
      key: "total_size_saved",
      width: 110,
      render: (value: number) => formatBytes(value),
    },
    {
      title: "耗时",
      dataIndex: "duration_ms",
      key: "duration_ms",
      width: 100,
      render: (value: number) => formatDuration(value),
    },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 100,
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          aria-label={`查看 ${record.id} 详情`}
          onClick={() => setDetailRecord(record)}
        >
          查看详情
        </Button>
      ),
    },
  ];

  const archiveColumns: ColumnsType<ArchiveItem> = [
    {
      title: "目标用户",
      dataIndex: "target_user_id",
      key: "target_user_id",
      width: 120,
      render: (value) => value || "-",
    },
    {
      title: "路径",
      dataIndex: "original_path",
      key: "original_path",
      width: 300,
      render: (value) => <span className={styles.pathText}>{value}</span>,
    },
    {
      title: "大小",
      dataIndex: "size_bytes",
      key: "size_bytes",
      width: 110,
      render: (value: number) => formatBytes(value),
    },
    {
      title: "时间",
      dataIndex: "archived_at",
      key: "archived_at",
      width: 160,
      render: (value) => formatDateTime(value),
    },
    {
      title: "操作人",
      dataIndex: "archived_by",
      key: "archived_by",
      width: 120,
      render: (value) => value || "-",
    },
    {
      title: "状态",
      dataIndex: "expired",
      key: "expired",
      width: 100,
      render: (expired: boolean) =>
        expired ? <Tag color="orange">待清理</Tag> : <Tag color="green">可恢复</Tag>,
    },
  ];

  const protectedColumns: ColumnsType<ProtectedFileInfo> = [
    {
      title: "目标用户",
      dataIndex: "target_user_id",
      key: "target_user_id",
      width: 120,
    },
    {
      title: "路径",
      dataIndex: "path",
      key: "path",
      width: 300,
      render: (value) => <span className={styles.pathText}>{value}</span>,
    },
    {
      title: "大小",
      dataIndex: "size_bytes",
      key: "size_bytes",
      width: 110,
      render: (value?: number | null) => (value ? formatBytes(value) : "-"),
    },
    {
      title: "时间",
      dataIndex: "protected_at",
      key: "protected_at",
      width: 160,
      render: (value) => formatDateTime(value),
    },
    {
      title: "操作人",
      dataIndex: "protected_by",
      key: "protected_by",
      width: 120,
      render: (value) => value || "-",
    },
    {
      title: "状态",
      dataIndex: "exists",
      key: "exists",
      width: 110,
      render: (exists: boolean) =>
        exists ? <Tag color="green">存在</Tag> : <Tag color="orange">缺失</Tag>,
    },
    {
      title: "原因",
      dataIndex: "reason",
      key: "reason",
      width: 160,
      render: (value) => value || "-",
    },
  ];

  const auditColumns: ColumnsType<ArchiveAdminAuditRecord> = [
    {
      title: "事件 ID",
      dataIndex: "event_id",
      key: "event_id",
      width: 160,
      render: (value) => <span className={styles.pathText}>{value}</span>,
    },
    {
      title: "操作时间",
      dataIndex: "timestamp",
      key: "timestamp",
      width: 160,
      render: (value) => formatDateTime(value),
    },
    {
      title: "管理员",
      dataIndex: "actor_user_id",
      key: "actor_user_id",
      width: 120,
    },
    {
      title: "目标用户",
      dataIndex: "target_user_id",
      key: "target_user_id",
      width: 120,
    },
    {
      title: "类型",
      dataIndex: "operation",
      key: "operation",
      width: 120,
      render: (value: string) => AUDIT_OPERATION_TEXT[value] || value,
    },
    {
      title: "文件数",
      dataIndex: "files_count",
      key: "files_count",
      width: 90,
    },
    {
      title: "释放空间",
      dataIndex: "total_size_bytes",
      key: "total_size_bytes",
      width: 110,
      render: (value: number) => formatBytes(value),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (value: string) => (
        <Tag color={AUDIT_STATUS_COLORS[value] || "default"}>{value}</Tag>
      ),
    },
  ];

  const applyFilters = () => {
    setQuery(buildParams(draft, 1, report?.page_size || 20));
  };

  const applyDateShortcut = (shortcut: DateShortcutKey) => {
    const nextDraft = {
      ...draft,
      dateRange: buildDateShortcutRange(shortcut),
    };
    setDraft(nextDraft);
    setQuery(buildParams(nextDraft, 1, report?.page_size || 20));
  };

  const resetFilters = () => {
    const nextDraft = buildDefaultDraft();
    setDraft(nextDraft);
    setQuery(buildParams(nextDraft, 1, 20));
  };

  const renderGovernanceTab = () => (
    <>
      <div className={styles.sectionHeader}>
        <div>
          <h3>持续治理分析</h3>
          <p>当前来源内所有可管理用户的持续治理覆盖、成功率和异常情况</p>
        </div>
      </div>

      <div className={styles.filterBar}>
        <RangePicker
          value={draft.dateRange}
          onChange={(dates) => {
            setDraft((prev) => ({
              ...prev,
              dateRange: dates as DateRange,
            }));
          }}
          allowClear
        />
        <Segmented
          className={styles.dateShortcuts}
          value={getActiveDateShortcut(draft.dateRange)}
          options={DATE_SHORTCUT_OPTIONS}
          onChange={(value) => applyDateShortcut(value as DateShortcutKey)}
        />
        <Select
          className={styles.filterControl}
          placeholder="机构 BBK"
          value={draft.bbk_id}
          options={bbkOptions}
          onChange={(value) => setDraft((prev) => ({ ...prev, bbk_id: value }))}
          allowClear
          showSearch
        />
        <Input
          className={styles.searchInput}
          placeholder="搜索用户 ID / 姓名"
          prefix={<Search size={15} />}
          value={draft.user_search}
          onChange={(event) =>
            setDraft((prev) => ({
              ...prev,
              user_search: event.target.value,
            }))
          }
          onPressEnter={applyFilters}
          allowClear
        />
        <Select
          className={styles.filterControl}
          placeholder="状态"
          value={draft.status}
          onChange={(value) => setDraft((prev) => ({ ...prev, status: value }))}
          options={[
            { value: "success", label: "成功" },
            { value: "failed", label: "失败" },
            { value: "rollback", label: "已回退" },
          ]}
          allowClear
        />
        <Select
          className={styles.filterControl}
          placeholder="触发方式"
          value={draft.trigger}
          onChange={(value) =>
            setDraft((prev) => ({ ...prev, trigger: value }))
          }
          options={[
            { value: "manual", label: "手动" },
            { value: "cron", label: "定时" },
          ]}
          allowClear
        />
        <Space
          className={styles.filterActions}
          data-testid="governance-filter-actions"
        >
          <Button
            type="primary"
            onClick={applyFilters}
            loading={loading}
            data-testid="governance-query-button"
          >
            查询
          </Button>
          <Button
            onClick={resetFilters}
            data-testid="governance-reset-button"
          >
            重置
          </Button>
        </Space>
      </div>

      <HealthPanel
        title="待对账状态"
        items={report?.health || []}
        testId="governance-health-panel"
      />

      <div className={styles.kpiGrid}>
        {kpis.map((item) => (
          <KpiCard key={item.key} item={item} />
        ))}
      </div>

      <div className={styles.chartGrid}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <span>治理趋势</span>
          </div>
          <TrendChart data={report?.trends || []} />
        </section>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <span>节省空间趋势</span>
          </div>
          <SavingsLineChart data={report?.trends || []} />
        </section>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <span>状态分布</span>
          </div>
          <StatusChart data={report?.status_distribution || []} />
        </section>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <span>机构分布</span>
          </div>
          <BbkChart
            data={report?.bbk_distribution || []}
            getBbkName={formatBbkName}
          />
        </section>
      </div>

      <section className={styles.tablePanel}>
        <div className={styles.panelHeader}>
          <span>用户明细</span>
          <span className={styles.panelMeta}>共 {report?.total || 0} 人</span>
        </div>
        <Table
          rowKey="user_id"
          size="middle"
          loading={loading}
          columns={userColumns}
          dataSource={report?.users || []}
          scroll={{ x: 1120 }}
          pagination={{
            current: report?.page || query.page || 1,
            pageSize: report?.page_size || query.page_size || 20,
            total: report?.total || 0,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 人`,
            onChange: (page, pageSize) => {
              setQuery({ ...query, page, page_size: pageSize });
            },
          }}
        />
      </section>
    </>
  );

  const renderFileGovernanceTab = () => (
    <>
      <div className={styles.sectionHeader}>
        <div>
          <h3>文件清理与归档</h3>
          <p>
            当前来源内可管理用户的归档、保护文件和清理审计情况。这里仅展示文件清理与归档状态，不提供清理、恢复、归档或取消保护操作。需要处理文件时请进入持续治理工作台。
          </p>
        </div>
      </div>

      <HealthPanel
        title="文件治理待对账状态"
        items={archiveReport?.health || []}
        testId="archive-health-panel"
      />

      <div className={styles.kpiGrid}>
        {archiveKpis.map((item) => (
          <KpiCard key={item.key} item={item} />
        ))}
      </div>

      <section className={styles.tablePanel}>
        <div className={styles.panelHeader}>
          <span>归档文件</span>
          <span className={styles.panelMeta}>共 {archiveTotal} 个</span>
        </div>
        <Table
          rowKey="id"
          size="middle"
          loading={archiveLoading}
          columns={archiveColumns}
          dataSource={archiveItems}
          scroll={{ x: 870 }}
          pagination={{
            current: archivePage,
            pageSize: archivePageSize,
            total: archiveTotal,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 个`,
            onChange: (page, pageSize) => {
              setArchivePage(page);
              setArchivePageSize(pageSize);
              setArchiveLoaded(false);
            },
          }}
        />
      </section>

      <section className={styles.tablePanel}>
        <div className={styles.panelHeader}>
          <span>保护文件</span>
          <span className={styles.panelMeta}>共 {protectedTotal} 个</span>
        </div>
        <Table
          rowKey={(record) =>
            `${record.target_user_id}:${record.target_agent_id}:${record.path}`
          }
          size="middle"
          loading={archiveLoading}
          columns={protectedColumns}
          dataSource={protectedFiles}
          scroll={{ x: 980 }}
          pagination={{
            current: protectedPage,
            pageSize: protectedPageSize,
            total: protectedTotal,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 个`,
            onChange: (page, pageSize) => {
              setProtectedPage(page);
              setProtectedPageSize(pageSize);
              setArchiveLoaded(false);
            },
          }}
        />
      </section>

      <section className={styles.tablePanel}>
        <div className={styles.panelHeader}>
          <span>清理审计</span>
          <span className={styles.panelMeta}>共 {auditTotal} 条记录</span>
        </div>
        <Table
          rowKey="event_id"
          size="middle"
          loading={archiveLoading}
          columns={auditColumns}
          dataSource={adminAudits}
          scroll={{ x: 1040 }}
          pagination={{
            current: auditPage,
            pageSize: auditPageSize,
            total: auditTotal,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条记录`,
            onChange: (page, pageSize) => {
              setAuditPage(page);
              setAuditPageSize(pageSize);
              setArchiveLoaded(false);
            },
          }}
        />
      </section>
    </>
  );

  return (
    <div className={styles.page}>
      <Tabs
        className={styles.tabs}
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as ActiveTab)}
        items={[
          {
            key: "governance",
            label: "持续治理分析",
            children: renderGovernanceTab(),
          },
          {
            key: "files",
            label: "文件清理与归档",
            children: renderFileGovernanceTab(),
          },
        ]}
      />

      <Drawer
        title={
          selectedUser
            ? `${selectedUser.user_name || selectedUser.user_id} 的治理记录`
            : "治理记录"
        }
        width={860}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setDetailRecord(null);
        }}
        destroyOnClose
      >
        <Table
          rowKey="id"
          size="small"
          loading={recordLoading}
          columns={recordColumns}
          dataSource={records}
          scroll={{ x: 900 }}
          pagination={{
            current: recordsPage,
            pageSize: recordsPageSize,
            total: recordsTotal,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条记录`,
            onChange: (page, pageSize) => {
              if (selectedUser) {
                void loadUserRecords(selectedUser, page, pageSize);
              }
            },
          }}
        />
      </Drawer>
      <Modal
        title="治理记录详情"
        open={Boolean(detailRecord)}
        footer={null}
        onCancel={() => setDetailRecord(null)}
        width={720}
        destroyOnClose
      >
        {detailRecord && (
          <Descriptions size="small" bordered column={2}>
            <Descriptions.Item label="任务 ID" span={2}>
              {detailRecord.id}
            </Descriptions.Item>
            <Descriptions.Item label="时间">
              {formatDateTime(detailRecord.timestamp)}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={STATUS_COLORS[detailRecord.status] || "default"}>
                {STATUS_TEXT[detailRecord.status] || detailRecord.status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="触发方式">
              {TRIGGER_TEXT[detailRecord.trigger] ||
                detailRecord.trigger ||
                "-"}
            </Descriptions.Item>
            <Descriptions.Item label="耗时">
              {formatDuration(detailRecord.duration_ms)}
            </Descriptions.Item>
            <Descriptions.Item label="文件数">
              {formatNumber(detailRecord.total_files_changed)}
            </Descriptions.Item>
            <Descriptions.Item label="节省空间">
              {formatBytes(detailRecord.total_size_saved)}
            </Descriptions.Item>
            <Descriptions.Item label="模型">
              {detailRecord.model_used || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="Token">
              {formatNumber(
                detailRecord.input_tokens + detailRecord.output_tokens,
              )}
            </Descriptions.Item>
            <Descriptions.Item label="摘要" span={2}>
              {detailRecord.summary || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="异常" span={2}>
              {detailRecord.error ? (
                <span className={styles.errorText}>{detailRecord.error}</span>
              ) : (
                "-"
              )}
            </Descriptions.Item>
            <Descriptions.Item label="文件列表" span={2}>
              {detailRecord.files_optimized.length ? (
                <Space direction="vertical" size={0}>
                  {detailRecord.files_optimized.map((file) => (
                    <span key={file} className={styles.pathText}>
                      {file}
                    </span>
                  ))}
                </Space>
              ) : (
                "-"
              )}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
}
