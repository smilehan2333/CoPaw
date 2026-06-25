import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  InboxOutlined,
  RollbackOutlined,
  SafetyOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { dreamLogsApi } from "../../../../api/modules/dreamLogs";
import type {
  ArchiveAdminAuditRecord,
  ArchiveItem,
  ArchiveReportResponse,
  ProtectedFileInfo,
} from "../../../../api/types/dreamLogs";
import styles from "../index.module.less";

const { Text } = Typography;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)}MB`;
}

interface ArchiveGovernanceProps {
  refreshKey?: number;
}

export default function ArchiveGovernance({
  refreshKey = 0,
}: ArchiveGovernanceProps) {
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<ArchiveReportResponse | null>(null);
  const [archiveItems, setArchiveItems] = useState<ArchiveItem[]>([]);
  const [protectedFiles, setProtectedFiles] = useState<ProtectedFileInfo[]>([]);
  const [audits, setAudits] = useState<ArchiveAdminAuditRecord[]>([]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [reportData, itemsData, protectedData, auditsData] =
        await Promise.all([
          dreamLogsApi.archiveReport(),
          dreamLogsApi.listArchiveItems({ page_size: 100 }),
          dreamLogsApi.listProtectedFiles({ page_size: 100 }),
          dreamLogsApi.listArchiveAdminAudits({ page_size: 100 }),
        ]);
      setReport(reportData);
      setArchiveItems(itemsData.items);
      setProtectedFiles(protectedData.items);
      setAudits(auditsData.items);
    } catch (error) {
      message.error("归档治理数据加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [refreshKey]);

  const handleRestore = async (record: ArchiveItem, protect: boolean) => {
    if (!record.target_user_id || !record.target_agent_id) return;
    try {
      await dreamLogsApi.restoreArchiveItem({
        archive_item_id: record.id,
        target_user_id: record.target_user_id,
        target_agent_id: record.target_agent_id,
        protect_after_restore: protect,
      });
      message.success(protect ? "已恢复并加入保护名单" : "已恢复");
      fetchData();
    } catch (error) {
      message.error("恢复失败");
    }
  };

  const handlePurge = async (record: ArchiveItem) => {
    if (!record.target_user_id || !record.target_agent_id) return;
    try {
      await dreamLogsApi.purgeArchiveItems({
        archive_item_ids: [record.id],
        target_user_id: record.target_user_id,
        target_agent_id: record.target_agent_id,
        reason: "manual_clear",
      });
      message.success("归档文件已清理");
      fetchData();
    } catch (error) {
      message.error("清理失败");
    }
  };

  const handlePurgeExpired = async () => {
    try {
      const result = await dreamLogsApi.purgeExpiredArchiveItems();
      message.success(`已清理 ${result.files_count} 个过期归档文件`);
      fetchData();
    } catch (error) {
      message.error("过期归档清理失败");
    }
  };

  const handleRemoveProtection = async (record: ProtectedFileInfo) => {
    try {
      await dreamLogsApi.removeProtectedFile({
        target_user_id: record.target_user_id,
        target_agent_id: record.target_agent_id,
        path: record.path,
      });
      message.success("已取消保护");
      fetchData();
    } catch (error) {
      message.error("取消保护失败");
    }
  };

  const archiveColumns: ColumnsType<ArchiveItem> = [
    {
      title: "目标用户",
      dataIndex: "target_user_id",
      width: 120,
    },
    {
      title: "Agent",
      dataIndex: "target_agent_id",
      width: 100,
    },
    {
      title: "原路径",
      dataIndex: "original_path",
      render: (value: string) => <Text copyable>{value}</Text>,
    },
    {
      title: "大小",
      dataIndex: "size_bytes",
      width: 110,
      render: (value: number) => formatSize(value),
    },
    {
      title: "归档时间",
      dataIndex: "archived_at",
      width: 180,
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "状态",
      dataIndex: "expired",
      width: 100,
      render: (expired: boolean) =>
        expired ? <Tag color="red">待清理</Tag> : <Tag color="green">可恢复</Tag>,
    },
    {
      title: "操作",
      key: "actions",
      width: 124,
      fixed: "right",
      render: (_, record) => (
        <Space size={4} className={styles.tableActionGroup}>
          <Tooltip title="恢复">
            <Button
              type="text"
              size="small"
              aria-label="恢复"
              icon={<RollbackOutlined />}
              onClick={() => handleRestore(record, false)}
            />
          </Tooltip>
          <Tooltip title="恢复并保护">
            <Button
              type="text"
              size="small"
              aria-label="恢复并保护"
              icon={<SafetyOutlined />}
              onClick={() => handleRestore(record, true)}
            />
          </Tooltip>
          <Popconfirm
            title="确认清理该归档文件？"
            onConfirm={() => handlePurge(record)}
          >
            <Button
              type="text"
              size="small"
              danger
              aria-label="清理"
              title="清理"
              icon={<DeleteOutlined />}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const protectedColumns: ColumnsType<ProtectedFileInfo> = [
    { title: "目标用户", dataIndex: "target_user_id", width: 120 },
    { title: "Agent", dataIndex: "target_agent_id", width: 100 },
    {
      title: "路径",
      dataIndex: "path",
      render: (value: string) => <Text copyable>{value}</Text>,
    },
    {
      title: "保护时间",
      dataIndex: "protected_at",
      width: 180,
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
    { title: "保护人", dataIndex: "protected_by", width: 120 },
    { title: "原因", dataIndex: "reason", width: 160 },
    {
      title: "存在状态",
      dataIndex: "exists",
      width: 100,
      render: (exists: boolean) =>
        exists ? <Tag color="green">存在</Tag> : <Tag color="orange">缺失</Tag>,
    },
    {
      title: "大小",
      dataIndex: "size_bytes",
      width: 110,
      render: (value?: number | null) => (value ? formatSize(value) : "-"),
    },
    {
      title: "操作",
      key: "actions",
      width: 72,
      fixed: "right",
      render: (_, record) => (
        <Popconfirm
          title="确认取消该文件保护？"
          onConfirm={() => handleRemoveProtection(record)}
        >
          <Button
            type="text"
            size="small"
            danger
            aria-label="取消保护"
            title="取消保护"
            icon={<DeleteOutlined />}
          />
        </Popconfirm>
      ),
    },
  ];

  const auditColumns: ColumnsType<ArchiveAdminAuditRecord> = [
    {
      title: "操作时间",
      dataIndex: "timestamp",
      width: 180,
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
    { title: "管理员", dataIndex: "actor_user_id", width: 120 },
    { title: "渠道", dataIndex: "source_name", width: 140 },
    { title: "目标用户", dataIndex: "target_user_id", width: 120 },
    { title: "Agent", dataIndex: "target_agent_id", width: 100 },
    {
      title: "类型",
      dataIndex: "operation",
      width: 140,
      render: (value: string) =>
        value === "auto_purge_archive" ? "自动清理" : "手动清理",
    },
    { title: "文件数", dataIndex: "files_count", width: 90 },
    {
      title: "释放空间",
      dataIndex: "total_size_bytes",
      width: 110,
      render: (value: number) => formatSize(value),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (value: string) => (
        <Tag color={value === "success" ? "green" : "red"}>{value}</Tag>
      ),
    },
  ];

  const summary = report?.summary;

  return (
    <div className={styles.container}>
      <Alert
        type="info"
        showIcon
        message="归档治理仅展示当前渠道下可管理用户的数据。"
        className={styles.workspaceAlert}
      />

      {summary && (
        <Row gutter={16} className={styles.statsRow}>
          <Col flex="1 1 180px">
            <Card className={styles.subStatsCard}>
              <Statistic title="归档文件" value={summary.archived_files} />
            </Card>
          </Col>
          <Col flex="1 1 180px">
            <Card className={styles.subStatsCard}>
              <Statistic
                title="归档占用"
                value={formatSize(summary.archived_size_bytes)}
              />
            </Card>
          </Col>
          <Col flex="1 1 180px">
            <Card className={styles.subStatsCard}>
              <Statistic
                title="待清理文件"
                value={summary.pending_purge_files}
              />
            </Card>
          </Col>
          <Col flex="1 1 180px">
            <Card className={styles.subStatsCard}>
              <Statistic title="保护文件" value={summary.protected_files} />
            </Card>
          </Col>
          <Col flex="1 1 180px">
            <Card className={styles.subStatsCard}>
              <Statistic
                title="已释放空间"
                value={formatSize(summary.purged_size_bytes)}
              />
            </Card>
          </Col>
        </Row>
      )}

      <Card
        className={styles.recordsCard}
        title={
          <Space>
            <InboxOutlined />
            归档治理
          </Space>
        }
        extra={
          <Space>
            <Popconfirm
              title="确认清理超过 10 天的归档文件？"
              onConfirm={handlePurgeExpired}
            >
            <Button danger icon={<DeleteOutlined />}>
              清理超过 10 天
            </Button>
          </Popconfirm>
          </Space>
        }
      >
        <Tabs
          onChange={() => {
            void fetchData();
          }}
          items={[
            {
              key: "archives",
              label: "归档文件",
              children:
                archiveItems.length === 0 ? (
                  <Empty description="暂无归档文件" />
                ) : (
                  <Table
                    loading={loading}
                    columns={archiveColumns}
                    dataSource={archiveItems}
                    rowKey="id"
                    scroll={{ x: 1100 }}
                  />
                ),
            },
            {
              key: "protected",
              label: "保护文件",
              children:
                protectedFiles.length === 0 ? (
                  <Empty description="暂无保护文件" />
                ) : (
                  <Table
                    loading={loading}
                    columns={protectedColumns}
                    dataSource={protectedFiles}
                    rowKey={(record) =>
                      `${record.target_user_id}:${record.target_agent_id}:${record.path}`
                    }
                    scroll={{ x: 1000 }}
                  />
                ),
            },
            {
              key: "audits",
              label: "清理审计",
              children:
                audits.length === 0 ? (
                  <Empty description="暂无清理记录" />
                ) : (
                  <Table
                    loading={loading}
                    columns={auditColumns}
                    dataSource={audits}
                    rowKey="event_id"
                    scroll={{ x: 1100 }}
                  />
                ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
