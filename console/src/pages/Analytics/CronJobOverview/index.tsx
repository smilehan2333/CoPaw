import {
  AlertTriangle,
  ArrowLeft,
  Banknote,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Eye,
  Landmark,
  RefreshCw,
  UserRoundCheck,
  type LucideIcon,
} from "lucide-react";
import { DatePicker, Input, Modal, Pagination, Select, Spin, Table, Tooltip } from "antd";
import { WarningOutlined } from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useState, type CSSProperties } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  monitorApi,
  type ExecutionItem,
  type CronJobOverviewFailureReason,
  type CronJobOverviewDateFilters,
  type CronJobOverviewPageData,
  type BranchManagerSummaryItem,
  type ManagerSkillItem,
  type ManagerCustomerItem,
  type BranchSkillItem,
  type BranchSkillManagerItem,
  type BranchSkillManagerCustomerItem,
  type CronBranchTaskRankingItem,
} from "../../../api/modules/monitor";
import { BBK_ID_MAP, BBK_ID_TO_NAME_MAP } from "../../../constants/bbk";
import styles from "./index.module.less";

const { Option } = Select;

type TimeRange = "day" | "week" | "month" | "custom";
type SummaryMetricTone = "blue" | "green" | "orange" | "red";

const failureReasonOptions = [
  "子任务执行失败",
  "渠道不存在",
  "token过期",
  "密文长度错误",
  "智能体请求校验失败",
  "模型错误",
  "其他",
] as const;

type FailureReason = (typeof failureReasonOptions)[number];

const quickTooltipProps = {
  mouseEnterDelay: 0,
  mouseLeaveDelay: 0,
} as const;

const SKILL_NAME_MAP: Record<string, string> = {
  insurance_mkt: "保险营销客户分析技能",
  deposit_scale_growth_skill: "存款规模增长与产品配置技能",
  fund_redeem_monitor: "基金赎回实时监控技能",
  lc_breaking: "单一持仓理财/定期客户破冰方案",
  "global-market-report": "全球市场复盘报告",
  "存款到期客户经营方案技能": "存款到期客户经营方案技能",
  "高AUM理财低收益客户调仓技能": "高AUM理财低收益客户调仓技能",
  "基金亏损客户关怀陪伴文案": "基金亏损客户关怀陪伴文案",
  "智能推荐保险计划书": "智能推荐保险计划书",
  "黄金持仓客户陪伴技能": "黄金持仓客户陪伴技能",
};

const ALLOWED_SKILLS = new Set([
  ...Object.keys(SKILL_NAME_MAP),
  ...Object.values(SKILL_NAME_MAP),
]);

function formatSkillName(key: string): string {
  return SKILL_NAME_MAP[key] || key;
}

type SummaryMetricDefinition = {
  key: string;
  title: string;
  unit?: string;
  footerLabel?: string;
  tone: SummaryMetricTone;
  icon: LucideIcon;
};

type SummaryMetricView = SummaryMetricDefinition & {
  value: string;
  footerValue?: string;
};

const summaryMetricDefinitions: SummaryMetricDefinition[] = [
  {
    key: "branches",
    title: "覆盖分行数",
    unit: "家",
    footerLabel: "客户经理数",
    tone: "blue",
    icon: Landmark,
  },
  {
    key: "tasks",
    title: "定时任务数",
    unit: "个",
    footerLabel: "任务执行次数",
    tone: "blue",
    icon: CalendarDays,
  },
  {
    key: "success",
    title: "执行成功率",
    unit: "%",
    footerLabel: "成功执行数",
    tone: "green",
    icon: CheckCircle2,
  },
  {
    key: "alert",
    title: "执行报错率",
    unit: "%",
    footerLabel: "失败执行数",
    tone: "red",
    icon: AlertTriangle,
  },
  {
    key: "read",
    title: "任务已读率",
    unit: "%",
    footerLabel: "已读任务数",
    tone: "orange",
    icon: Eye,
  },
];

const emptyOverviewData: CronJobOverviewPageData = {
  summaryMetrics: [],
  branchRankingRows: [],
  failureReasons: [],
  anomalySummary: {
    affectedBranches: "-",
    affectedBranchesUnit: "家",
    affectedManagers: "-",
    affectedManagersUnit: "人",
  },
  anomalyRankRows: [],
};

function isValidDateParam(value: string | null) {
  if (!value) {
    return false;
  }
  const parsed = dayjs(value);
  return parsed.isValid() && parsed.format("YYYY-MM-DD") === value;
}

function getInitialDateRange(searchParams: URLSearchParams): [Dayjs, Dayjs] {
  const startDate = searchParams.get("start_date");
  const endDate = searchParams.get("end_date");

  if (isValidDateParam(startDate) && isValidDateParam(endDate)) {
    return [dayjs(startDate), dayjs(endDate)];
  }

  return [dayjs(), dayjs()];
}

function getTimeRangeForDateRange([start, end]: [Dayjs, Dayjs]): TimeRange {
  const today = dayjs();

  if (start.isSame(today, "day") && end.isSame(today, "day")) {
    return "day";
  }
  if (
    start.isSame(today.subtract(6, "day"), "day") &&
    end.isSame(today, "day")
  ) {
    return "week";
  }
  if (
    start.isSame(today.subtract(29, "day"), "day") &&
    end.isSame(today, "day")
  ) {
    return "month";
  }
  return "custom";
}

function getInitialBbkIds(searchParams: URLSearchParams) {
  const bbkIds = searchParams.get("bbk_ids");
  return bbkIds ? bbkIds.split(",").map((item) => item.trim()).filter(Boolean) : [];
}

const classifyFailureReason = (
  errorMessage: string,
  asyncStatus?: string | null,
  status?: string,
): FailureReason => {
  // 只有当 status='success' AND async_status='error' 时才是子任务执行失败
  // 如果 status='error'，即使 async_status='error' 也是其他类型的失败
  if (status === "success" && asyncStatus === "error") {
    return "子任务执行失败";
  }

  const message = errorMessage || "";
  const normalizedMessage = message.toLowerCase();

  if (message.includes("channel not found")) {
    return "渠道不存在";
  }
  if (message.includes("cron auth user_info is expired")) {
    return "token过期";
  }
  if (message.includes("Illegal Argument")) {
    return "密文长度错误";
  }
  if (normalizedMessage.includes("validation error for agentrequest")) {
    return "智能体请求校验失败";
  }
  if (message.includes("Agent execution did not complete")) {
    return "模型错误";
  }
  return "其他";
};

function SummaryCard({ metric }: { metric: SummaryMetricView }) {
  const Icon = metric.icon;

  return (
    <article className={`${styles.summaryCard} ${styles[metric.tone]}`}>
      <div className={styles.summaryMain}>
        <span className={styles.summaryIcon}>
          <Icon size={28} />
        </span>
        <div className={styles.summaryText}>
          <span className={styles.summaryTitle}>{metric.title}</span>
          <strong>
            {metric.value}
            {metric.unit ? <em>{metric.unit}</em> : null}
          </strong>
        </div>
      </div>
      {metric.footerLabel && metric.footerValue ? (
        <div className={styles.summaryFooter}>
          <span>{metric.footerLabel}</span>
          <strong>{metric.footerValue}</strong>
        </div>
      ) : null}
    </article>
  );
}

function TaskRankingTable({
  data,
  loading,
  onRowClick,
  selectedBranchId,
}: {
  data: CronBranchTaskRankingItem[];
  loading: boolean;
  onRowClick: (bbkId: string, bbkName: string) => void;
  selectedBranchId: string | null;
}) {
  return (
    <section className={`${styles.panel} ${styles.behaviorPanel}`}>
      <Spin spinning={loading} tip="加载分行排行...">
        <div className={styles.tableScroller}>
          <table className={styles.behaviorTable}>
            <colgroup>
              <col style={{ width: 42 }} />
              <col style={{ width: 95 }} />
              <col style={{ width: 85 }} />
              <col style={{ width: 75 }} />
              <col style={{ width: 75 }} />
              <col style={{ width: 60 }} />
              <col style={{ width: 75 }} />
              <col style={{ width: 120 }} />
              <col style={{ width: 120 }} />
              <col style={{ width: 120 }} />
              <col style={{ width: 75 }} />
            </colgroup>
            <thead>
              <tr>
                <th className={styles.indexCell} />
                <th>分行名称</th>
                <th>覆盖客户经理数</th>
                <th>定时任务数</th>
                <th>成功执行数</th>
                <th>成功率</th>
                <th>已读任务数</th>
                <th>查看方案任务数/点击数</th>
                <th>点击去洞察任务数/点击数</th>
                <th>点击去电访任务数/点击数</th>
                <th>报错执行次数</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row, index) => {
                const isSelected = row.bbk_id === selectedBranchId;
                return (
                  <tr
                    key={`${row.bbk_id}-${index}`}
                    className={
                      `${isSelected ? styles.selectedRow : ""} ${styles.clickableRow}`.trim() || undefined
                    }
                    onClick={() => onRowClick(row.bbk_id, row.bbk_name)}
                  >
                    <td className={styles.indexCell}>{index + 1}</td>
                    <td className={styles.branchNameLink}>
                      <span>{row.bbk_name}</span>
                    </td>
                    <td>{row.manager_count}</td>
                    <td>{row.total_tasks}</td>
                    <td>{row.success_count}</td>
                    <td>{row.success_rate.toFixed(1)}%</td>
                    <td>{row.read_tasks}</td>
                    <td>{row.plan_count}/{row.plan_clicks}</td>
                    <td>{row.insight_count}/{row.insight_clicks}</td>
                    <td>{row.phone_count}/{row.phone_clicks}</td>
                    <td>{row.error_count}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Spin>
    </section>
  );
}

function RankingTable({
  data,
  onRowClick,
  selectedBranchId,
}: {
  data: CronJobOverviewPageData["branchRankingRows"];
  onRowClick: (bbkId: string, bbkName: string) => void;
  selectedBranchId: string | null;
}) {
  return (
    <section className={`${styles.panel} ${styles.behaviorPanel}`}>
      <div className={styles.tableScroller}>
        <table className={styles.behaviorTable}>
          <colgroup>
            <col style={{ width: 42 }} />
            <col style={{ width: 95 }} />
            <col style={{ width: 55 }} />
            <col style={{ width: 55 }} />
            <col style={{ width: 55 }} />
            <col style={{ width: 55 }} />
            <col style={{ width: 65 }} />
            <col style={{ width: 80 }} />
            <col style={{ width: 80 }} />
            <col style={{ width: 65 }} />
            <col style={{ width: 65 }} />
            <col style={{ width: 55 }} />
            <col style={{ width: 80 }} />
            <col style={{ width: 55 }} />
            <col style={{ width: 55 }} />
          </colgroup>
          <thead>
            <tr>
              <th className={styles.indexCell} />
              <th>分行名称</th>
              <th>技能数</th>
              <th>任务总数</th>
              <th>成功执行数</th>
              <th>已读任务数</th>
              <th>涉及客户经理数</th>
              <th>查看结果的客户经理数</th>
              <th>查看经营方案客户经理数</th>
              <th>去洞察的客户经理数</th>
              <th>去电访的客户经理数</th>
              <th>推荐的客户数</th>
              <th>被客户经理查看的客户数</th>
              <th>去洞察客户数</th>
              <th>去电访客户数</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row, index) => {
              const isClickable = row.bbkId && row.rank !== "...";
              const isSelected = row.bbkId && row.bbkId === selectedBranchId;

              return (
              <tr
                key={`${row.branchName}-${index}`}
                className={
                  `${row.rank === "..." ? styles.mutedRow : ""} ${isSelected ? styles.selectedRow : ""} ${isClickable ? styles.clickableRow : ""}`.trim() ||
                  undefined
                }
                onClick={() => {
                  if (isClickable) {
                    onRowClick(row.bbkId, row.branchName);
                  }
                }}
              >
                <td className={styles.indexCell}>{row.rank}</td>
                <td className={isClickable ? styles.branchNameLink : styles.branchName}>
                  <span>{row.branchName}</span>
                </td>
                <td>{row.skillCount}</td>
                <td>{row.totalTasks}</td>
                <td>{row.successCount}</td>
                <td>{row.readTasks}</td>
                <td>{row.involvedManagers}</td>
                <td>{row.resultViewManagers}</td>
                <td>{row.planManagers}</td>
                <td>{row.insightManagers}</td>
                <td>{row.phoneManagers}</td>
                <td>{row.recommendedCustomers}</td>
                <td>{row.viewedCustomers}</td>
                <td>{row.insightCustomers}</td>
                <td>{row.phoneCustomers}</td>
              </tr>
            );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DonutChart({ items }: { items: CronJobOverviewFailureReason[] }) {
  const total = items.reduce((sum, item) => sum + item.count, 0);
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className={styles.donutWrap}>
      <svg className={styles.donutChart} viewBox="0 0 116 116" role="img" aria-label="报错原因分布">
        <circle cx="58" cy="58" r={radius} fill="none" stroke="#edf3fb" strokeWidth="16" />
        {items.map((item) => {
          const dash = total > 0 ? (item.count / total) * circumference : 0;
          const segmentStyle = {
            "--dash": dash,
            "--gap": circumference - dash,
            "--offset": -offset,
            "--segment-color": item.color,
          } as CSSProperties;
          offset += dash;

          return (
            <circle
              key={item.name}
              className={styles.donutSegment}
              cx="58"
              cy="58"
              r={radius}
              fill="none"
              strokeWidth="16"
              style={segmentStyle}
            />
          );
        })}
      </svg>
      <div className={styles.donutCenter}>
        <strong>{total.toLocaleString("en-US")}</strong>
        <span>报错执行次数</span>
      </div>
    </div>
  );
}

function FailureReasonPanel({
  data,
  onOpenDetail,
}: {
  data: CronJobOverviewFailureReason[];
  onOpenDetail: () => void;
}) {
  return (
    <article className={styles.reasonPanel}>
      <div className={styles.reasonPanelHeader}>
        <h3>报错原因分布（按报错执行次数）</h3>
        <button
          type="button"
          className={styles.linkButton}
          onClick={onOpenDetail}
        >
          查看详情
          <ChevronRight size={14} />
        </button>
      </div>
      <div className={styles.reasonContent}>
        <DonutChart items={data} />
        <div className={styles.reasonLegend}>
          {data.map((item) => (
            <div key={item.name} className={styles.reasonRow}>
              <span>
                <i style={{ backgroundColor: item.color }} />
                {item.name}
              </span>
              <strong>
                {item.percent.toFixed(2)}% ({item.count})
              </strong>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function MiniSummaryCard({
  icon,
  title,
  value,
  unit,
  tone = "blue",
}: {
  icon: LucideIcon;
  title: string;
  value: string;
  unit: string;
  tone?: SummaryMetricTone;
}) {
  const Icon = icon;

  return (
    <article className={`${styles.miniSummaryCard} ${styles[tone]}`}>
      <span className={styles.miniIcon}>
        <Icon size={26} />
      </span>
      <div>
        <span>{title}</span>
        <strong>
          {value}
          <em>{unit}</em>
        </strong>
      </div>
    </article>
  );
}

function RankTable({ data }: { data: CronJobOverviewPageData["anomalyRankRows"] }) {
  return (
    <section className={`${styles.panel} ${styles.rankPanel}`}>
      <h2>分行异常排行</h2>
      <div className={styles.tableScroller}>
        <table className={styles.rankTable}>
          <thead>
            <tr>
              <th className={styles.indexCell} />
              <th>分行名称</th>
              <th>报错执行次数</th>
              <th>报错率</th>
              <th>受影响客户经理数</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr key={row.rank}>
                <td className={styles.indexCell}>{row.rank}</td>
                <td className={styles.branchName}>{row.branchName}</td>
                <td>{row.alertExecutions}</td>
                <td>{row.alertRate}</td>
                <td>{row.affectedManagers}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FailedTaskModal({
  open,
  onClose,
  tasks,
  loading,
}: {
  open: boolean;
  onClose: () => void;
  tasks: ExecutionItem[];
  loading: boolean;
}) {
  const [keyword, setKeyword] = useState("");
  const [failureReason, setFailureReason] = useState<FailureReason | undefined>();
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 5;
  const normalizedKeyword = keyword.trim().toLowerCase();
  const filteredTasks = tasks.filter((task) => {
    const matchesKeyword = normalizedKeyword
      ? (task.tenant_id || "").toLowerCase().includes(normalizedKeyword)
      : true;
    const matchesFailureReason = failureReason
      ? classifyFailureReason(task.error_message, task.async_status, task.status) === failureReason
      : true;

    return matchesKeyword && matchesFailureReason;
  });
  const totalCount = filteredTasks.length;
  const paginatedTasks = filteredTasks.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );
  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };
  const handleFilterChange = () => {
    setCurrentPage(1);
  };
  const handleClose = () => {
    setKeyword("");
    setFailureReason(undefined);
    setCurrentPage(1);
    onClose();
  };

  return (
    <Modal
      open={open}
      className={styles.failedTaskModal}
      title={
        <div className={styles.failedTaskModalTitle}>
          <span className={styles.failedTaskWarningIcon}>
            <WarningOutlined />
          </span>
          <span>执行失败任务清单</span>
        </div>
      }
      width={1080}
      footer={null}
      onCancel={handleClose}
      destroyOnHidden
    >
      <div className={styles.failedTaskToolbar}>
        <Input.Search
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onSearch={(val) => {
            setKeyword(val);
            handleFilterChange();
          }}
          allowClear
          placeholder="输入用户ID筛选"
          className={styles.failedTaskSearch}
        />
        <Select
          allowClear
          value={failureReason}
          onChange={(value) => {
            setFailureReason(value);
            handleFilterChange();
          }}
          placeholder="失败原因"
          className={styles.failedReasonSelect}
          options={failureReasonOptions.map((reason) => ({
            label: reason,
            value: reason,
          }))}
        />
      </div>
      <Spin spinning={loading} tip="加载失败任务...">
        <div className={styles.failedTaskTable}>
          <div className={styles.failedTaskTableHeader}>
            <span>任务名称</span>
            <span>用户姓名</span>
            <span>用户id</span>
            <span>执行时间</span>
            <span>耗时</span>
            <span>报错信息</span>
          </div>
          <div className={styles.failedTaskTableBody}>
            {paginatedTasks.map((task) => (
              <div key={task.id} className={styles.failedTaskTableRow}>
                <span className={styles.failedTaskName}>{task.job_name}</span>
                <span>{task.tenant_name}</span>
                <span>{task.tenant_id}</span>
                <span>
                  {task.actual_time
                    ? dayjs(task.actual_time).format("YYYY-MM-DD HH:mm:ss")
                    : "-"}
                </span>
                <span>
                  {task.duration_ms === undefined || task.duration_ms === null
                    ? "-"
                    : task.duration_ms < 1000
                    ? `${task.duration_ms}ms`
                    : `${(task.duration_ms / 1000).toFixed(2)}s`}
                </span>
                <Tooltip
                  {...quickTooltipProps}
                  title={
                    task.async_status === "error"
                      ? "子任务执行失败"
                      : task.error_message || "-"
                  }
                  placement="topLeft"
                >
                  <span className={styles.errorMessageCell}>
                    {task.async_status === "error"
                      ? "子任务执行失败"
                      : task.error_message || "-"}
                  </span>
                </Tooltip>
              </div>
            ))}
          </div>
        </div>
        <div className={styles.failedTaskPagination}>
          <Pagination
            current={currentPage}
            pageSize={pageSize}
            total={totalCount}
            onChange={handlePageChange}
            showSizeChanger={false}
            showTotal={(total) => `共 ${total} 条`}
          />
        </div>
      </Spin>
    </Modal>
  );
}

export default function CronJobOverviewPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialDateRange = getInitialDateRange(searchParams);
  const [overviewData, setOverviewData] = useState<CronJobOverviewPageData>(emptyOverviewData);
  const [loading, setLoading] = useState(false);
  const [timeRange, setTimeRange] = useState<TimeRange>(
    getTimeRangeForDateRange(initialDateRange),
  );
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>(initialDateRange);
  const [bbkIds, setBbkIds] = useState<string[]>(() => getInitialBbkIds(searchParams));
  const [failedTaskModalOpen, setFailedTaskModalOpen] = useState(false);
  const [failedTasks, setFailedTasks] = useState<ExecutionItem[]>([]);
  const [failedTasksLoading, setFailedTasksLoading] = useState(false);

  // Task view state (original ranking table)
  const [taskBranchRankingRows, setTaskBranchRankingRows] = useState<CronBranchTaskRankingItem[]>([]);
  const [taskBranchRankingLoading, setTaskBranchRankingLoading] = useState(false);
  const [selectedTaskBranch, setSelectedTaskBranch] = useState<{ bbk_id: string; bbk_name: string } | null>(null);
  const [selectedTaskSkill, setSelectedTaskSkill] = useState<string | null>(null);
  const [selectedTaskManager, setSelectedTaskManager] = useState<string | null>(null);
  const [taskSkills, setTaskSkills] = useState<BranchSkillItem[]>([]);
  const [taskSkillsLoading, setTaskSkillsLoading] = useState(false);
  const [taskManagers, setTaskManagers] = useState<BranchSkillManagerItem[]>([]);
  const [taskManagersLoading, setTaskManagersLoading] = useState(false);
  const [taskCustomers, setTaskCustomers] = useState<BranchSkillManagerCustomerItem[]>([]);
  const [taskCustomersLoading, setTaskCustomersLoading] = useState(false);

  // Skill view state (current ranking table with manager drill-down)
  // Inline drill-down state for branch ranking expansion
  const [selectedBranch, setSelectedBranch] = useState<{ bbk_id: string; bbk_name: string } | null>(null);
  const [managerSummary, setManagerSummary] = useState<BranchManagerSummaryItem[]>([]);
  const [managerSummaryLoading, setManagerSummaryLoading] = useState(false);

  // Manager detail modal state
  const [managerDetailModalOpen, setManagerDetailModalOpen] = useState(false);
  const [selectedManagerForModal, setSelectedManagerForModal] = useState<BranchManagerSummaryItem | null>(null);
  const [modalSkills, setModalSkills] = useState<ManagerSkillItem[]>([]);
  const [modalSkillsLoading, setModalSkillsLoading] = useState(false);
  const [modalCustomers, setModalCustomers] = useState<ManagerCustomerItem[]>([]);
  const [modalCustomersLoading, setModalCustomersLoading] = useState(false);
  const [selectedModalSkill, setSelectedModalSkill] = useState<string | null>(null);

  const getOverviewFilters = (): CronJobOverviewDateFilters => ({
    start_date: dateRange[0].format("YYYY-MM-DD"),
    end_date: dateRange[1].format("YYYY-MM-DD"),
    bbk_ids: bbkIds.length > 0 ? bbkIds.join(",") : undefined,
  });

  const getExecutionDateRangeParams = () => ({
    start_time: dateRange[0].startOf("day").format("YYYY-MM-DDTHH:mm:ss"),
    end_time: dateRange[1].endOf("day").format("YYYY-MM-DDTHH:mm:ss"),
  });

  const getDrawerDateParams = () => ({
    start_date: dateRange[0].format("YYYY-MM-DD"),
    end_date: dateRange[1].format("YYYY-MM-DD"),
  });

  // ===== Task view functions =====

  const fetchTaskBranchRanking = async () => {
    setTaskBranchRankingLoading(true);
    try {
      const response = await monitorApi.getCronBranchTaskBehavior(getOverviewFilters());
      setTaskBranchRankingRows(response.items);
    } catch (error) {
      console.warn("Failed to fetch task branch ranking.", error);
    } finally {
      setTaskBranchRankingLoading(false);
    }
  };

  const handleSelectTaskBranch = async (bbkId: string, bbkName: string) => {
    if (selectedTaskBranch?.bbk_id === bbkId) {
      setSelectedTaskBranch(null);
      setTaskSkills([]);
      setTaskManagers([]);
      setTaskCustomers([]);
      setSelectedTaskSkill(null);
      setSelectedTaskManager(null);
      return;
    }
    setSelectedTaskBranch({ bbk_id: bbkId, bbk_name: bbkName });
    setSelectedTaskSkill(null);
    setSelectedTaskManager(null);
    setTaskSkills([]);
    setTaskManagers([]);
    setTaskCustomers([]);

    // Fetch skills for this branch
    setTaskSkillsLoading(true);
    try {
      const dateParams = getDrawerDateParams();
      const response = await monitorApi.getBranchSkills({
        bbk_id: bbkId,
        ...dateParams,
      });
      const filtered = response.items.filter((item) => ALLOWED_SKILLS.has(item.skill_name));
      setTaskSkills(filtered);
    } catch (error) {
      console.warn("Failed to fetch task skills.", error);
    } finally {
      setTaskSkillsLoading(false);
    }
  };

  const handleSelectTaskSkill = async (skillName: string) => {
    if (selectedTaskSkill === skillName) {
      setSelectedTaskSkill(null);
      setTaskManagers([]);
      setTaskCustomers([]);
      setSelectedTaskManager(null);
      return;
    }
    setSelectedTaskSkill(skillName);
    setSelectedTaskManager(null);
    setTaskManagers([]);
    setTaskCustomers([]);

    // Fetch managers for this skill
    setTaskManagersLoading(true);
    try {
      const dateParams = getDrawerDateParams();
      const response = await monitorApi.getBranchSkillManagers({
        bbk_id: selectedTaskBranch!.bbk_id,
        skill_name: skillName,
        ...dateParams,
      });
      setTaskManagers(response.items);
    } catch (error) {
      console.warn("Failed to fetch task managers.", error);
    } finally {
      setTaskManagersLoading(false);
    }
  };

  const handleSelectTaskManager = async (userId: string) => {
    if (selectedTaskManager === userId) {
      setSelectedTaskManager(null);
      setTaskCustomers([]);
      return;
    }
    setSelectedTaskManager(userId);
    setTaskCustomers([]);

    // Fetch customers for this manager
    setTaskCustomersLoading(true);
    try {
      const dateParams = getDrawerDateParams();
      const response = await monitorApi.getBranchSkillManagerCustomers({
        bbk_id: selectedTaskBranch!.bbk_id,
        skill_name: selectedTaskSkill!,
        user_id: userId,
        ...dateParams,
      });
      setTaskCustomers(response.items);
    } catch (error) {
      console.warn("Failed to fetch task customers.", error);
    } finally {
      setTaskCustomersLoading(false);
    }
  };

  // ===== Skill view functions =====

  const handleSelectBranch = async (bbkId: string, bbkName: string) => {
    if (selectedBranch?.bbk_id === bbkId) {
      setSelectedBranch(null);
      setManagerSummary([]);
      return;
    }
    setSelectedBranch({ bbk_id: bbkId, bbk_name: bbkName });
    setManagerSummary([]);

    setManagerSummaryLoading(true);
    try {
      const dateParams = getDrawerDateParams();
      const response = await monitorApi.getBranchManagerSummary({
        bbk_id: bbkId,
        ...dateParams,
      });
      setManagerSummary(response.items);
    } catch (error) {
      console.warn("Failed to fetch branch manager summary.", error);
    } finally {
      setManagerSummaryLoading(false);
    }
  };

  // 打开客户经理详情弹窗
  const handleOpenManagerDetail = async (manager: BranchManagerSummaryItem) => {
    setSelectedManagerForModal(manager);
    setManagerDetailModalOpen(true);
    setModalSkills([]);
    setModalCustomers([]);
    setSelectedModalSkill(null);

    // 获取技能明细
    setModalSkillsLoading(true);
    try {
      const dateParams = getDrawerDateParams();
      const response = await monitorApi.getManagerSkills({
        bbk_id: selectedBranch!.bbk_id,
        user_id: manager.user_id,
        ...dateParams,
      });
      setModalSkills(response.items);
    } catch (error) {
      console.warn("Failed to fetch modal skills.", error);
    } finally {
      setModalSkillsLoading(false);
    }
  };

  // 选择技能，获取该技能下的点击客户明细
  const handleSelectModalSkill = async (skillName: string) => {
    setSelectedModalSkill(skillName);
    setModalCustomers([]);
    setModalCustomersLoading(true);
    try {
      const dateParams = getDrawerDateParams();
      const response = await monitorApi.getManagerCustomers({
        bbk_id: selectedBranch!.bbk_id,
        user_id: selectedManagerForModal!.user_id,
        skill_name: skillName,
        ...dateParams,
      });
      setModalCustomers(response.items);
    } catch (error) {
      console.warn("Failed to fetch modal customers.", error);
    } finally {
      setModalCustomersLoading(false);
    }
  };

  // 关闭客户经理详情弹窗
  const handleCloseManagerDetail = () => {
    setManagerDetailModalOpen(false);
    setSelectedManagerForModal(null);
    setModalSkills([]);
    setModalCustomers([]);
    setSelectedModalSkill(null);
  };

  // Collapse drill-down when date range changes
  useEffect(() => {
    setSelectedBranch(null);
    setManagerSummary([]);
    setManagerDetailModalOpen(false);
    setSelectedManagerForModal(null);
    // Task view reset
    setSelectedTaskBranch(null);
    setTaskSkills([]);
    setTaskManagers([]);
    setTaskCustomers([]);
    setSelectedTaskSkill(null);
    setSelectedTaskManager(null);
    // Fetch task branch ranking
    fetchTaskBranchRanking();
  }, [dateRange]);

  useEffect(() => {
    let ignore = false;

    async function loadOverview() {
      setLoading(true);
      try {
        const response = await monitorApi.getCronJobOverviewPageData(getOverviewFilters());
        if (!ignore) {
          setOverviewData(response);
        }
      } catch (error) {
        console.warn("Failed to fetch cron job overview page data.", error);
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    loadOverview();

    return () => {
      ignore = true;
    };
  }, [dateRange, bbkIds]);

  useEffect(() => {
    const nextParams = new URLSearchParams();
    nextParams.set("start_date", dateRange[0].format("YYYY-MM-DD"));
    nextParams.set("end_date", dateRange[1].format("YYYY-MM-DD"));
    if (bbkIds.length > 0) {
      nextParams.set("bbk_ids", bbkIds.join(","));
    }
    setSearchParams(nextParams, { replace: true });
  }, [dateRange, bbkIds, setSearchParams]);

  const fetchOverview = async () => {
    setLoading(true);
    try {
      const response = await monitorApi.getCronJobOverviewPageData(getOverviewFilters());
      setOverviewData(response);
    } catch (error) {
      console.warn("Failed to fetch cron job overview page data.", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchFailedTasks = async () => {
    setFailedTasksLoading(true);
    setFailedTasks([]);
    try {
      const pageSize = 100;
      const activeBbkIds = bbkIds.filter(Boolean);
      const selectedBbkIds = activeBbkIds.length > 0 ? activeBbkIds : [undefined];
      const selectedBbkIdSet = new Set(activeBbkIds);
      const allTasks: ExecutionItem[] = [];
      console.info("[cron failed tasks debug] start fetch", {
        dateRange: getExecutionDateRangeParams(),
        activeBbkIds,
        selectedBbkIds,
      });

      for (const bbkId of selectedBbkIds) {
        let page = 1;
        let total = 0;

        do {
          const response = await monitorApi.getExecutions(page, pageSize, {
            ...getExecutionDateRangeParams(),
            status: "failed",
            bbk_id: bbkId,
          });
          console.info("[cron failed tasks debug] response page", {
            requestedBbkId: bbkId,
            page,
            total: response.total,
            itemCount: response.items.length,
            sample: response.items.slice(0, 5).map((task) => ({
              id: task.id,
              jobId: task.job_id,
              tenantId: task.tenant_id,
              bbkId: task.bbk_id,
              status: task.status,
            })),
          });
          if (response.items.length === 0) {
            break;
          }
          allTasks.push(...response.items);
          total = response.total;
          page += 1;
        } while ((page - 1) * pageSize < total);
      }

      const tasksById = new Map<number, ExecutionItem>();
      allTasks
        .filter((task) =>
          selectedBbkIdSet.size === 0 ? true : selectedBbkIdSet.has(task.bbk_id || ""),
        )
        .forEach((task) => {
          tasksById.set(task.id, task);
        });
      console.info("[cron failed tasks debug] final tasks", {
        activeBbkIds,
        rawCount: allTasks.length,
        filteredCount: tasksById.size,
        filteredSample: Array.from(tasksById.values()).slice(0, 5).map((task) => ({
          id: task.id,
          jobId: task.job_id,
          tenantId: task.tenant_id,
          bbkId: task.bbk_id,
          status: task.status,
        })),
      });
      setFailedTasks(
        Array.from(tasksById.values()).sort((a, b) => {
          const left = a.actual_time ? dayjs(a.actual_time).valueOf() : 0;
          const right = b.actual_time ? dayjs(b.actual_time).valueOf() : 0;
          return right - left;
        }),
      );
    } catch (error) {
      console.warn("Failed to fetch failed cron executions.", error);
    } finally {
      setFailedTasksLoading(false);
    }
  };

  useEffect(() => {
    if (failedTaskModalOpen) {
      fetchFailedTasks();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [failedTaskModalOpen, dateRange, bbkIds]);

  const handleModeChange = (nextRange: TimeRange) => {
    setTimeRange(nextRange);
    const today = dayjs();

    if (nextRange === "day") {
      setDateRange([today, today]);
    } else if (nextRange === "week") {
      setDateRange([today.subtract(6, "day"), today]);
    } else if (nextRange === "month") {
      setDateRange([today.subtract(29, "day"), today]);
    }
  };

  const handleDateRangeChange = (dates: null | [Dayjs | null, Dayjs | null]) => {
    if (!dates?.[0] || !dates?.[1]) {
      return;
    }

    const [start, end] = dates;
    const today = dayjs();

    if (start.isSame(today, "day") && end.isSame(today, "day")) {
      setTimeRange("day");
    } else if (
      start.isSame(today.subtract(6, "day"), "day") &&
      end.isSame(today, "day")
    ) {
      setTimeRange("week");
    } else if (
      start.isSame(today.subtract(29, "day"), "day") &&
      end.isSame(today, "day")
    ) {
      setTimeRange("month");
    } else {
      setTimeRange("custom");
    }

    setDateRange([start, end]);
  };

  const disabledDate = (current: Dayjs | null): boolean =>
    !!current && current.isAfter(dayjs().startOf("day"), "day");

  const summaryMetricValues = new Map(
    overviewData.summaryMetrics.map((metric) => [metric.key, metric]),
  );
  const summaryMetrics = summaryMetricDefinitions.map((definition) => {
    const metricValue = summaryMetricValues.get(definition.key);
    const footerValue =
      definition.key === "branches"
        ? summaryMetricValues.get("managers")?.value
        : metricValue?.footerValue;
    return {
      ...definition,
      value: metricValue?.value ?? "-",
      footerValue,
    };
  });

  return (
    <main className={styles.cronOverviewPage}>
      {loading ? <div className={styles.loadingBar}>加载中...</div> : null}
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <button
            type="button"
            className={styles.backButton}
            onClick={() => navigate("/analytics/business-overview")}
          >
            <ArrowLeft size={20} />
          </button>
          <h1>定时任务详情</h1>
        </div>
        <div className={styles.toolbar}>
          <div className={styles.toolbarLeft}>
            <div className={styles.segmentedControl}>
              <button
                type="button"
                className={timeRange === "day" ? styles.segmentActive : styles.segmentButton}
                onClick={() => handleModeChange("day")}
              >
                今天
              </button>
              <button
                type="button"
                className={timeRange === "week" ? styles.segmentActive : styles.segmentButton}
                onClick={() => handleModeChange("week")}
              >
                近7天
              </button>
              <button
                type="button"
                className={timeRange === "month" ? styles.segmentActive : styles.segmentButton}
                onClick={() => handleModeChange("month")}
              >
                近30天
              </button>
            </div>

            <div className={styles.dateRangePanel}>
              <DatePicker.RangePicker
                className={styles.rangePicker}
                value={dateRange}
                onChange={handleDateRangeChange}
                format="YYYY-MM-DD"
                suffixIcon={<CalendarDays size={16} />}
                disabledDate={disabledDate}
                allowClear={false}
              />
            </div>
          </div>

          <div className={styles.toolbarRight}>
            <Select
              className={styles.scopeSelect}
              mode="multiple"
              value={bbkIds}
              onChange={setBbkIds}
              placeholder="全部分行"
              maxTagCount="responsive"
              maxTagPlaceholder={(omittedValues) => (
                <Tooltip
                  title={omittedValues
                    .map((item) => {
                      const value = String(item.value ?? "");
                      return BBK_ID_TO_NAME_MAP[value] || value;
                    })
                    .join("、")}
                >
                  <span>+{omittedValues.length} 个分行</span>
                </Tooltip>
              )}
              allowClear
              showSearch
              filterOption={(input, option) => {
                const searchValue = input.toLowerCase();
                const optionValue = String(option?.value ?? "");
                const optionLabel = BBK_ID_TO_NAME_MAP[optionValue] || "";
                return (
                  optionValue.toLowerCase().includes(searchValue) ||
                  optionLabel.toLowerCase().includes(searchValue)
                );
              }}
            >
              {BBK_ID_MAP.map((item) => (
                <Option key={item.value} value={item.value}>
                  {item.label}
                </Option>
              ))}
            </Select>
            <button
              type="button"
              className={styles.refreshButton}
              onClick={fetchOverview}
            >
              <RefreshCw size={16} />
              刷新
            </button>
          </div>
        </div>
      </header>

      <section className={styles.summaryGrid} aria-label="概览指标">
        {summaryMetrics.map((metric) => (
          <SummaryCard key={metric.key} metric={metric} />
        ))}
      </section>

      <p className={styles.formulaNote}>
        说明： 执行成功率 = 成功执行次数 / 任务执行次数； 任务已读率 = 已读任务去重数 / 已执行任务去重数； 执行报错率 = 报错执行次数 / 任务执行次数
      </p>

      {/* 任务视角分行排行 */}
      <h2 className={styles.sectionHeading}>
        分行综合排行
        <span className={styles.sectionHeadingHint}>（点击分行查看明细）</span>
      </h2>
      <TaskRankingTable
        data={taskBranchRankingRows}
        loading={taskBranchRankingLoading}
        onRowClick={handleSelectTaskBranch}
        selectedBranchId={selectedTaskBranch?.bbk_id ?? null}
      />

      {selectedTaskBranch && (
        <div className={styles.drillDownContainer}>
          {/* 技能列 */}
          <div className={styles.drillDownColumn}>
            <h3 className={styles.drillDownTitle}>
              当前分行下的技能明细
              <span className={styles.drillDownSubTitle}>（{selectedTaskBranch.bbk_name}）</span>
            </h3>
            <div className={styles.drillDownTableScroll}>
              <Table
                dataSource={taskSkills}
                rowKey="skill_name"
                loading={taskSkillsLoading}
                size="small"
                pagination={false}
                onRow={(record) => ({
                  onClick: () => handleSelectTaskSkill(record.skill_name),
                  style: {
                    cursor: "pointer",
                    background: record.skill_name === selectedTaskSkill ? "#e6f4ff" : undefined,
                  },
                })}
                columns={[
                  {
                    title: "技能名称",
                    dataIndex: "skill_name",
                    key: "skill_name",
                    width: 130,
                    align: "center",
                    render: (v: string) => formatSkillName(v),
                  },
                  { title: "定时任务数", dataIndex: "cron_task_count", key: "cron_task_count", width: 60, align: "center" },
                  { title: "成功执行数", dataIndex: "success_count", key: "success_count", width: 60, align: "center" },
                  {
                    title: "成功率",
                    dataIndex: "success_rate",
                    key: "success_rate",
                    width: 48,
                    align: "center",
                    render: (v: number) => (v != null ? `${v.toFixed(1)}%` : "-"),
                  },
                  { title: "已读任务数", dataIndex: "read_count", key: "read_count", width: 60, align: "center" },
                  { title: "报错次数", dataIndex: "error_count", key: "error_count", width: 55, align: "center" },
                ]}
              />
            </div>
          </div>

          {/* 客户经理列 */}
          <div className={styles.drillDownColumn}>
            <h3 className={styles.drillDownTitle}>
              该技能下的客户经理明细
              {selectedTaskSkill && (
                <span className={styles.drillDownSubTitle}>（{formatSkillName(selectedTaskSkill)}）</span>
              )}
            </h3>
            <div className={styles.drillDownTableScroll}>
              <Table
                dataSource={taskManagers}
                rowKey="user_id"
                loading={taskManagersLoading}
                size="small"
                pagination={false}
                onRow={(record) => ({
                  onClick: () => handleSelectTaskManager(record.user_id),
                  style: {
                    cursor: "pointer",
                    background: record.user_id === selectedTaskManager ? "#e6f4ff" : undefined,
                  },
                })}
                columns={[
                  { title: "客户经理", dataIndex: "user_name", key: "user_name", width: 80, align: "center" },
                  { title: "已读次数", dataIndex: "read_count", key: "read_count", width: 50, align: "center" },
                  { title: "方案次数", dataIndex: "plan_count", key: "plan_count", width: 50, align: "center" },
                  { title: "洞察次数", dataIndex: "insight_count", key: "insight_count", width: 50, align: "center" },
                  { title: "电访次数", dataIndex: "phone_count", key: "phone_count", width: 50, align: "center" },
                  {
                    title: "最后点击时间",
                    dataIndex: "last_click_time",
                    key: "last_click_time",
                    width: 100,
                    align: "center",
                    render: (v: string) => (v ? dayjs(v).format("YYYY-MM-DD HH:mm") : "-"),
                  },
                ]}
              />
            </div>
          </div>

          {/* 客户列 */}
          <div className={styles.drillDownColumn}>
            <h3 className={styles.drillDownTitle}>
              该客户经理下的客户明细
              {selectedTaskManager && taskManagers.length > 0 && (
                <span className={styles.drillDownSubTitle}>
                  （{taskManagers.find((m) => m.user_id === selectedTaskManager)?.user_name || selectedTaskManager}）
                </span>
              )}
            </h3>
            <div className={styles.drillDownTableScroll}>
              <Table
                dataSource={taskCustomers}
                rowKey="customer_id"
                loading={taskCustomersLoading}
                size="small"
                pagination={false}
                columns={[
                  { title: "客户名称", dataIndex: "customer_name", key: "customer_name", width: 90, align: "center" },
                  { title: "客户ID", dataIndex: "customer_id", key: "customer_id", width: 80, align: "center" },
                  {
                    title: "点击方案",
                    dataIndex: "clicked_plan",
                    key: "clicked_plan",
                    width: 55,
                    align: "center",
                    render: (v: boolean) => (v ? "是" : "否"),
                  },
                  {
                    title: "点击洞察",
                    dataIndex: "clicked_insight",
                    key: "clicked_insight",
                    width: 55,
                    align: "center",
                    render: (v: boolean) => (v ? "是" : "否"),
                  },
                  {
                    title: "点击电访",
                    dataIndex: "clicked_phone",
                    key: "clicked_phone",
                    width: 55,
                    align: "center",
                    render: (v: boolean) => (v ? "是" : "否"),
                  },
                ]}
              />
            </div>
          </div>
        </div>
      )}

      <section className={styles.anomalySection}>
        <div className={styles.anomalyLeft}>
          <h2>分行层异常诊断</h2>
          <div className={styles.miniSummaryGrid}>
            <MiniSummaryCard

              icon={Banknote}
              title="受影响分行数"
              value={overviewData.anomalySummary.affectedBranches}
              unit={overviewData.anomalySummary.affectedBranchesUnit}
            />
            <MiniSummaryCard
              icon={UserRoundCheck}
              title="受影响客户经理数"
              value={overviewData.anomalySummary.affectedManagers}
              unit={overviewData.anomalySummary.affectedManagersUnit}
              tone="orange"
            />
          </div>
          <FailureReasonPanel
            data={overviewData.failureReasons}
            onOpenDetail={() => setFailedTaskModalOpen(true)}
          />
        </div>
        <RankTable data={overviewData.anomalyRankRows} />
      </section>
      <FailedTaskModal
        open={failedTaskModalOpen}
        onClose={() => setFailedTaskModalOpen(false)}
        tasks={failedTasks}
        loading={failedTasksLoading}
      />

      {/* 客户经理详情弹窗 */}
      <Modal
        open={managerDetailModalOpen}
        onCancel={handleCloseManagerDetail}
        footer={null}
        width={900}
        title={
          <span>
            客户经理详情
            {selectedManagerForModal && (
              <span style={{ marginLeft: 8, fontWeight: "normal", color: "#64748b" }}>
                （{selectedManagerForModal.user_name || selectedManagerForModal.user_id}）
              </span>
            )}
          </span>
        }
      >
        {selectedManagerForModal && (
          <div className={styles.drillDownContainer}>
            {/* 技能明细列 */}
            <div className={styles.drillDownColumn}>
              <h3 className={styles.drillDownTitle}>
                技能明细
                <span className={styles.drillDownHint}>（点击查看客户）</span>
              </h3>
              <div className={styles.drillDownTableScroll}>
                <Table
                  dataSource={modalSkills}
                  rowKey="skill_name"
                  loading={modalSkillsLoading}
                  size="small"
                  pagination={false}
                  onRow={(record) => ({
                    onClick: () => handleSelectModalSkill(record.skill_name),
                    style: {
                      cursor: "pointer",
                      background: record.skill_name === selectedModalSkill ? "#e6f4ff" : undefined,
                    },
                  })}
                  columns={[
                    {
                      title: "技能名称",
                      dataIndex: "skill_name",
                      key: "skill_name",
                      width: 130,
                      align: "center",
                      render: (v: string) => formatSkillName(v),
                    },
                    { title: "定时任务数", dataIndex: "cron_task_count", key: "cron_task_count", width: 70, align: "center" },
                    { title: "成功执行数", dataIndex: "success_count", key: "success_count", width: 70, align: "center" },
                    {
                      title: "成功率",
                      dataIndex: "success_rate",
                      key: "success_rate",
                      width: 60,
                      align: "center",
                      render: (v: number) => (v != null ? `${v.toFixed(1)}%` : "-"),
                    },
                    { title: "已读任务数", dataIndex: "read_count", key: "read_count", width: 70, align: "center" },
                    { title: "报错次数", dataIndex: "error_count", key: "error_count", width: 60, align: "center" },
                  ]}
                />
              </div>
            </div>

            {/* 点击客户明细列 */}
            <div className={styles.drillDownColumn}>
              <h3 className={styles.drillDownTitle}>
                点击客户明细
                {selectedModalSkill && (
                  <span className={styles.drillDownSubTitle}>（{formatSkillName(selectedModalSkill)}）</span>
                )}
              </h3>
              <div className={styles.drillDownTableScroll}>
                <Table
                  dataSource={modalCustomers}
                  rowKey="customer_id"
                  loading={modalCustomersLoading}
                  size="small"
                  pagination={{ pageSize: 5 }}
                  columns={[
                    { title: "客户名称", dataIndex: "customer_name", key: "customer_name", width: 90, align: "center" },
                    { title: "客户ID", dataIndex: "customer_id", key: "customer_id", width: 80, align: "center" },
                    {
                      title: "点击方案",
                      dataIndex: "clicked_plan",
                      key: "clicked_plan",
                      width: 55,
                      align: "center",
                      render: (v: boolean) => (v ? "是" : "否"),
                    },
                    {
                      title: "点击洞察",
                      dataIndex: "clicked_insight",
                      key: "clicked_insight",
                      width: 55,
                      align: "center",
                      render: (v: boolean) => (v ? "是" : "否"),
                    },
                    {
                      title: "点击电访",
                      dataIndex: "clicked_phone",
                      key: "clicked_phone",
                      width: 55,
                      align: "center",
                      render: (v: boolean) => (v ? "是" : "否"),
                    },
                    {
                      title: "点击时间",
                      dataIndex: "click_time",
                      key: "click_time",
                      width: 100,
                      align: "center",
                      render: (v: string) => (v ? dayjs(v).format("YYYY-MM-DD HH:mm") : "-"),
                    },
                  ]}
                />
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* 技能视角分行排行 */}
      <h2 className={styles.sectionHeading}>
        技能视角-分行综合排行
        <span className={styles.sectionHeadingHint}>（点击分行查看明细）</span>
      </h2>
      <RankingTable
        data={overviewData.branchRankingRows}
        onRowClick={handleSelectBranch}
        selectedBranchId={selectedBranch?.bbk_id ?? null}
      />

      {/* 技能视角下钻 */}
      {selectedBranch && (
        <div className={styles.drillDownContainer}>
          <div className={styles.drillDownFullWidth}>
            <h3 className={styles.drillDownTitle}>
              当前分行下的客户经理明细
              <span className={styles.drillDownSubTitle}>（{selectedBranch.bbk_name}）</span>
            </h3>
            <div className={styles.drillDownTableScroll}>
              <Table
                dataSource={managerSummary}
                rowKey="user_id"
                loading={managerSummaryLoading}
                size="small"
                pagination={false}
                rowClassName={styles.drillHoverRow}
                columns={[
                  {
                    title: "客户经理名称",
                    dataIndex: "user_name",
                    key: "user_name",
                    width: 100,
                    align: "center",
                    render: (v: string, record: BranchManagerSummaryItem) => (
                      <span
                        className={styles.clickableLink}
                        onClick={() => handleOpenManagerDetail(record)}
                      >
                        {v || record.user_id}
                      </span>
                    ),
                  },
                  { title: "技能数量", dataIndex: "skill_count", key: "skill_count", width: 70, align: "center" },
                  { title: "任务总数", dataIndex: "total_tasks", key: "total_tasks", width: 70, align: "center" },
                  { title: "成功执行数", dataIndex: "success_count", key: "success_count", width: 70, align: "center" },
                  { title: "已读任务数", dataIndex: "read_tasks", key: "read_tasks", width: 70, align: "center" },
                  { title: "推荐客户数", dataIndex: "recommended_customers", key: "recommended_customers", width: 80, align: "center" },
                  { title: "查看方案客户数", dataIndex: "viewed_customers", key: "viewed_customers", width: 90, align: "center" },
                  { title: "去洞察客户数", dataIndex: "insight_customers", key: "insight_customers", width: 80, align: "center" },
                  { title: "去电访客户数", dataIndex: "phone_customers", key: "phone_customers", width: 80, align: "center" },
                ]}
              />
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
