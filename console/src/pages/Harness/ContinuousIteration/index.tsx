import { useEffect, useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  Card,
  Button,
  Tag,
  Space,
  Modal,
  message,
  Spin,
  Empty,
  Collapse,
  Typography,
  Tooltip,
  Tabs,
  DatePicker,
  Select,
  Row,
  Col,
  Alert,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  PlayCircleOutlined,
  HistoryOutlined,
  FileTextOutlined,
  RollbackOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  DatabaseOutlined,
  FilterOutlined,
  DeleteOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { dreamLogsApi } from "../../../api/modules/dreamLogs";
import { useIframeStore } from "../../../stores/iframeStore";
import type {
  DreamLogRecord,
  DreamLogsStats,
  FileStats,
} from "../../../api/types/dreamLogs";
import StatsCards from "./components/StatsCards";
import FileDiffModal from "./components/FileDiffModal";
import BackupFiles from "./components/BackupFiles";
import OrphanFiles from "./components/OrphanFiles";
import ArchiveGovernance from "./components/ArchiveGovernance";
import styles from "./index.module.less";

const { Text } = Typography;
const { RangePicker } = DatePicker;

const POLL_INTERVAL = 2000;
const POLL_TIMEOUT = 30 * 60 * 1000;
type TopTabKey = "records" | "backups" | "cleanup" | "archive-governance";

export default function ContinuousIterationPage() {
  const { t } = useTranslation();
  const isSuperManager = useIframeStore((state) => state.isSuperManager);
  const manager = useIframeStore((state) => state.manager);
  const canManageArchive = isSuperManager || manager;
  const [loading, setLoading] = useState(true);
  const [records, setRecords] = useState<DreamLogRecord[]>([]);
  const [stats, setStats] = useState<DreamLogsStats | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [diffModalVisible, setDiffModalVisible] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState<DreamLogRecord | null>(null);
  const [selectedFilename, setSelectedFilename] = useState<string>("");

  // 已回退文件追踪（解决单文件回退后其他文件无法回退的问题）
  const [rolledBackFiles, setRolledBackFiles] = useState<Record<string, Set<string>>>({});

  // 运行状态轮询
  const [isRunning, setIsRunning] = useState(false);
  const [runningStartedAt, setRunningStartedAt] = useState<string | null>(null);
  const [runningTrigger, setRunningTrigger] = useState<"cron" | "manual" | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Filter state
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [triggerFilter, setTriggerFilter] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TopTabKey>("records");
  const [tabRefreshKeys, setTabRefreshKeys] = useState<
    Record<Exclude<TopTabKey, "records">, number>
  >({
    backups: 0,
    cleanup: 0,
    "archive-governance": 0,
  });

  useEffect(() => {
    fetchData();
    checkStatus();
    return () => stopPolling();
  }, [page, pageSize]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await dreamLogsApi.list(page, pageSize);
      setRecords(data.records);
      setStats(data.stats);
      setTotal(data.total);
    } catch (error) {
      console.error("Failed to fetch dream logs:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleTabChange = (key: string) => {
    const nextTab = key as TopTabKey;
    setActiveTab(nextTab);
    if (nextTab === "records") {
      fetchData();
      checkStatus();
      return;
    }
    setTabRefreshKeys((current) => ({
      ...current,
      [nextTab]: current[nextTab] + 1,
    }));
  };

  // 查询运行状态
  const checkStatus = async () => {
    try {
      const result = await dreamLogsApi.status();
      if (result.running) {
        setIsRunning(true);
        setRunningStartedAt(result.started_at || null);
        setRunningTrigger(result.trigger || null);
        startPolling();
      }
    } catch {
      // 后端未实现 /status 接口时静默忽略
    }
  };

  const startPolling = () => {
    stopPolling();
    const startTime = Date.now();
    pollingRef.current = setInterval(async () => {
      const elapsed = Math.floor((Date.now() - startTime) / 1000);

      if (elapsed * 1000 >= POLL_TIMEOUT) {
        stopPolling();
        setIsRunning(false);
        fetchData();
        return;
      }

      try {
        const result = await dreamLogsApi.status();
        if (!result.running) {
          stopPolling();
          setIsRunning(false);
          fetchData();
        }
      } catch {
        stopPolling();
        setIsRunning(false);
        fetchData();
      }
    }, POLL_INTERVAL);
  };

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  // Filter records based on date range and status
  const filteredRecords = records.filter((record) => {
    if (dateRange && dateRange[0] && dateRange[1]) {
      const recordDate = dayjs(record.timestamp);
      if (recordDate < dateRange[0] || recordDate > dateRange[1].endOf("day")) {
        return false;
      }
    }
    if (statusFilter && record.status !== statusFilter) {
      return false;
    }
    if (triggerFilter && record.trigger !== triggerFilter) {
      return false;
    }
    return true;
  });

  const handleFilterChange = () => {
    setPage(1);
  };

  const clearFilters = () => {
    setDateRange(null);
    setStatusFilter(null);
    setTriggerFilter(null);
    setPage(1);
  };

  const handleTrigger = async () => {
    try {
      const result = await dreamLogsApi.trigger();
      if (result.success) {
        message.success(t("dreamLogs.triggerNow") + " - " + result.message);
        setIsRunning(true);
        setRunningTrigger("manual");
        setRunningStartedAt(new Date().toISOString());
        startPolling();
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error("Failed to trigger governance optimization");
    }
  };

  const handleRollback = async (recordId: string, files?: string[]) => {
    Modal.confirm({
      title: t("dreamLogs.rollback.confirm"),
      content: files
        ? t("dreamLogs.rollback.confirmMessage")
        : t("dreamLogs.rollback.confirmAllMessage"),
      onOk: async () => {
        try {
          const result = await dreamLogsApi.rollback(recordId, files);
          if (result.success) {
            message.success(t("dreamLogs.rollback.success"));
            // 将回退文件标记到本地状态，而非依赖记录级 status
            if (files) {
              setRolledBackFiles((prev) => {
                const next = { ...prev };
                if (!next[recordId]) next[recordId] = new Set();
                files.forEach((f) => next[recordId].add(f));
                return next;
              });
            }
            fetchData();
          } else {
            message.error(result.message);
          }
        } catch (error) {
          message.error(t("dreamLogs.rollback.failed"));
        }
      },
    });
  };

  const handleViewDiff = (record: DreamLogRecord, filename: string) => {
    setSelectedRecord(record);
    setSelectedFilename(filename);
    setDiffModalVisible(true);
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const formatDuration = (ms: number): string => {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}min`;
  };

  const getStatusTag = (status: string) => {
    const statusMap: Record<string, { color: string; icon: React.ReactNode }> = {
      success: { color: "success", icon: <CheckCircleOutlined /> },
      failed: { color: "error", icon: <CloseCircleOutlined /> },
      rollback: { color: "warning", icon: <SyncOutlined /> },
    };
    const config = statusMap[status] || { color: "default", icon: null };
    return (
      <Tag color={config.color} icon={config.icon}>
        {t(`dreamLogs.statusValue.${status}`)}
      </Tag>
    );
  };

  const getTriggerTag = (trigger: string) => {
    const color = trigger === "cron" ? "blue" : "purple";
    return (
      <Tag color={color}>
        {t(`dreamLogs.trigger.${trigger}`)}
      </Tag>
    );
  };

  const columns: ColumnsType<DreamLogRecord> = [
    {
      title: t("dreamLogs.runTime"),
      key: "timestamp",
      width: 180,
      render: (_, record) => (
        <Space direction="vertical" size="small">
          <Text>{dayjs(record.timestamp).format("YYYY-MM-DD HH:mm:ss")}</Text>
          <Space size="small">
            {getTriggerTag(record.trigger)}
            {getStatusTag(record.status)}
          </Space>
        </Space>
      ),
    },
    {
      title: t("dreamLogs.filesOptimized"),
      dataIndex: "total_files_changed",
      key: "files",
      width: 100,
      render: (value: number, record) => (
        <Tooltip title={record.files_optimized.join(", ")}>
          <Tag icon={<FileTextOutlined />}>{value}</Tag>
        </Tooltip>
      ),
    },
    {
      title: t("dreamLogs.stats.spaceSaved"),
      dataIndex: "total_size_saved",
      key: "space_saved",
      width: 120,
      render: (value: number) => (
        <Text type={value > 0 ? "success" : value < 0 ? "danger" : undefined}>
          {value > 0 && "-"}
          {value < 0 && "+"}
          {formatSize(Math.abs(value))}
        </Text>
      ),
    },
    {
      title: t("dreamLogs.duration"),
      dataIndex: "duration_ms",
      key: "duration",
      width: 100,
      render: (value: number) => (
        <Text>
          <ClockCircleOutlined /> {formatDuration(value)}
        </Text>
      ),
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 80,
      fixed: "right",
      render: (_, record) => (
        <Space>
          <Tooltip title={t("dreamLogs.rollback.all")}>
            <Button
              type="text"
              size="small"
              icon={<RollbackOutlined />}
              onClick={() => handleRollback(record.id)}
              disabled={record.status === "rollback"}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  const renderFileStats = (record: DreamLogRecord) => {
    // 显示所有有变更的文件（包括变大的）
    const fileEntries = Object.entries(record.file_stats).filter(
      ([, stats]) => stats.size_saved !== 0 || stats.lines_removed > 0
    );
    if (fileEntries.length === 0) return null;

    const rolledBack = rolledBackFiles[record.id] || new Set<string>();

    const fileColumns: ColumnsType<[string, FileStats]> = [
      {
        title: t("dreamLogs.file.filename"),
        dataIndex: 0,
        key: "filename",
        width: 180,
        render: (filename: string) => <Text strong>{filename}</Text>,
      },
      {
        title: t("dreamLogs.file.sizeBefore"),
        dataIndex: 1,
        key: "size_before",
        width: 100,
        render: (stats: FileStats) => formatSize(stats.size_before),
      },
      {
        title: t("dreamLogs.file.sizeAfter"),
        dataIndex: 1,
        key: "size_after",
        width: 100,
        render: (stats: FileStats) => formatSize(stats.size_after),
      },
      {
        title: t("dreamLogs.file.sizeSaved"),
        dataIndex: 1,
        key: "size_saved",
        width: 100,
        render: (stats: FileStats) =>
          stats.size_saved > 0 ? (
            <Tag color="green">-{formatSize(stats.size_saved)}</Tag>
          ) : stats.size_saved < 0 ? (
            <Tag color="red">+{formatSize(Math.abs(stats.size_saved))}</Tag>
          ) : (
            <Text type="secondary">0</Text>
          ),
      },
      {
        title: t("common.actions"),
        key: "actions",
        width: 150,
        render: ([filename, stats]: [string, FileStats]) => (
          <Space>
            <Button
              type="link"
              size="small"
              icon={<FileTextOutlined />}
              onClick={() => handleViewDiff(record, filename)}
            >
              {t("dreamLogs.viewDiff")}
            </Button>
            <Button
              type="link"
              size="small"
              icon={<RollbackOutlined />}
              onClick={() => handleRollback(record.id, [filename])}
              disabled={rolledBack.has(filename)}
            >
              {t("dreamLogs.rollback.single")}
            </Button>
          </Space>
        ),
      },
    ];

    return (
      <Space direction="vertical" style={{ width: "100%" }} className={styles.expandedContent}>
        <Table
          columns={fileColumns}
          dataSource={fileEntries}
          rowKey={(item) => item[0]}
          pagination={false}
          size="small"
        />
        {record.summary && (
          <Collapse
            style={{ marginTop: 12 }}
            className={styles.summaryCollapse}
            items={[
              {
                key: "summary",
                label: t("dreamLogs.summary"),
                children: (
                  <div className={styles.markdownContent} style={{ maxHeight: 300, overflow: "auto" }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {record.summary}
                    </ReactMarkdown>
                  </div>
                ),
              },
            ]}
          />
        )}
      </Space>
    );
  };

  const renderRecordsContent = () => (
    <>
      {stats && <StatsCards stats={stats} />}

      {/* 运行中状态提示 */}
      {isRunning && (
        <Alert
          className={styles.runningBanner}
          type="info"
          showIcon
          icon={<LoadingOutlined />}
          message={
            <Space>
              <Text strong>
                {runningTrigger === "cron"
                  ? t("dreamLogs.running.autoTitle")
                  : t("dreamLogs.running.title")}
              </Text>
            </Space>
          }
        />
      )}

      <Card
        className={styles.recordsCard}
        title={
          <Space>
            <HistoryOutlined />
            {t("dreamLogs.title")}
          </Space>
        }
        extra={
          <Button
            className={styles.triggerBtn}
            type="primary"
            icon={isRunning ? <LoadingOutlined /> : <PlayCircleOutlined />}
            onClick={handleTrigger}
            loading={isRunning}
            disabled={isRunning}
          >
            {isRunning ? t("dreamLogs.running.triggering") : t("dreamLogs.triggerNow")}
          </Button>
        }
      >
        {/* Filter controls */}
        <Row gutter={16} className={styles.filterRow}>
          <Col>
            <Space>
              <FilterOutlined />
              <RangePicker
                value={dateRange}
                onChange={(dates) => {
                  setDateRange(dates);
                  handleFilterChange();
                }}
                placeholder={[t("dreamLogs.filter.startDate"), t("dreamLogs.filter.endDate")]}
                allowClear
              />
              <Select
                value={statusFilter}
                onChange={(value) => {
                  setStatusFilter(value);
                  handleFilterChange();
                }}
                placeholder={t("dreamLogs.filter.status")}
                allowClear
                style={{ width: 120 }}
                options={[
                  { value: "success", label: t("dreamLogs.statusValue.success") },
                  { value: "failed", label: t("dreamLogs.statusValue.failed") },
                  { value: "rollback", label: t("dreamLogs.statusValue.rollback") },
                ]}
              />
              <Select
                value={triggerFilter}
                onChange={(value) => {
                  setTriggerFilter(value);
                  handleFilterChange();
                }}
                placeholder={t("dreamLogs.filter.trigger")}
                allowClear
                style={{ width: 120 }}
                options={[
                  { value: "cron", label: t("dreamLogs.trigger.cron") },
                  { value: "manual", label: t("dreamLogs.trigger.manual") },
                ]}
              />
              {(dateRange || statusFilter || triggerFilter) && (
                <Button onClick={clearFilters}>
                  {t("dreamLogs.filter.clear")}
                </Button>
              )}
            </Space>
          </Col>
        </Row>

        <Spin spinning={loading}>
          {filteredRecords.length === 0 ? (
            <Empty
              description={t("dreamLogs.noRecords")}
              style={{ padding: 40 }}
            >
              <Text type="secondary">{t("dreamLogs.firstRecord")}</Text>
            </Empty>
          ) : (
            <Table
              className={styles.customTable}
              columns={columns}
              dataSource={filteredRecords}
              rowKey="id"
              pagination={{
                current: page,
                pageSize,
                total: filteredRecords.length,
                onChange: (p, ps) => {
                  setPage(p);
                  setPageSize(ps);
                },
              }}
              expandable={{
                expandedRowRender: renderFileStats,
                rowExpandable: (record) =>
                  Object.entries(record.file_stats).some(
                    ([, stats]) => stats.size_saved !== 0 || stats.lines_removed > 0
                  ),
              }}
              scroll={{ x: 700 }}
            />
          )}
        </Spin>
      </Card>
    </>
  );

  const tabItems = [
    {
      key: "records",
      label: (
        <Space>
          <HistoryOutlined />
          {t("dreamLogs.tabRecords")}
        </Space>
      ),
      children: renderRecordsContent(),
    },
    {
      key: "backups",
      label: (
        <Space>
          <DatabaseOutlined />
          {t("dreamLogs.tabBackups")}
        </Space>
      ),
      children: <BackupFiles refreshKey={tabRefreshKeys.backups} />,
    },
    {
      key: "cleanup",
      label: (
        <Space>
          <DeleteOutlined />
          {t("dreamLogs.tabCleanup")}
        </Space>
      ),
      children: <OrphanFiles refreshKey={tabRefreshKeys.cleanup} />,
    },
    ...(canManageArchive
      ? [
          {
            key: "archive-governance",
            label: (
              <Space>
                <DatabaseOutlined />
                归档治理
              </Space>
            ),
            children: (
              <ArchiveGovernance
                refreshKey={tabRefreshKeys["archive-governance"]}
              />
            ),
          },
        ]
      : []),
  ];

  return (
    <div className={styles.container}>
      <Tabs
        className={styles.customTabs}
        activeKey={activeTab}
        items={tabItems}
        onChange={handleTabChange}
      />
      <FileDiffModal
        visible={diffModalVisible}
        record={selectedRecord}
        filename={selectedFilename}
        onClose={() => setDiffModalVisible(false)}
        onRollback={() => {
          if (selectedRecord) {
            handleRollback(selectedRecord.id, [selectedFilename]);
          }
          setDiffModalVisible(false);
        }}
      />
    </div>
  );
}
