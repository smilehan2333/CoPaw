import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Card,
  Table,
  Button,
  Space,
  Modal,
  message,
  Spin,
  Empty,
  Statistic,
  Row,
  Col,
  Tag,
  Popconfirm,
  Typography,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  ClockCircleOutlined,
  DeleteOutlined,
  DeleteFilled,
  DatabaseOutlined,
  DownOutlined,
  FileOutlined,
  HistoryOutlined,
  EyeOutlined,
  RightOutlined,
  RollbackOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { dreamLogsApi } from "../../../../api/modules/dreamLogs";
import type {
  BackupFileInfo,
  BackupListResponse,
  BackupContentResponse,
} from "../../../../api/types/dreamLogs";
import styles from "../index.module.less";

const { Text } = Typography;

interface BackupTaskGroup {
  key: string;
  record_id: string;
  timestamp: string;
  created_at: string;
  total_size: number;
  files: BackupFileInfo[];
}

const UNLINKED_RECORD_ID = "";

const groupBackupFilesByTask = (files: BackupFileInfo[]): BackupTaskGroup[] => {
  const groups = new Map<string, BackupTaskGroup>();

  files.forEach((file) => {
    const hasRecord = Boolean(file.record_id);
    const key = hasRecord
      ? file.record_id
      : `unlinked-${file.timestamp || file.created_at || file.filename}`;
    const current = groups.get(key);
    if (current) {
      current.files.push(file);
      current.total_size += file.size;
      if (dayjs(file.created_at).isAfter(dayjs(current.created_at))) {
        current.created_at = file.created_at;
      }
      if (
        file.timestamp &&
        dayjs(file.timestamp).isAfter(dayjs(current.timestamp))
      ) {
        current.timestamp = file.timestamp;
      }
      return;
    }

    groups.set(key, {
      key,
      record_id: hasRecord ? file.record_id : UNLINKED_RECORD_ID,
      timestamp: file.timestamp,
      created_at: file.created_at,
      total_size: file.size,
      files: [file],
    });
  });

  return Array.from(groups.values()).sort((left, right) => {
    const leftTime = left.timestamp || left.created_at;
    const rightTime = right.timestamp || right.created_at;
    return dayjs(rightTime).valueOf() - dayjs(leftTime).valueOf();
  });
};

interface BackupFilesPageProps {
  refreshKey?: number;
}

export default function BackupFilesPage({ refreshKey = 0 }: BackupFilesPageProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [backups, setBackups] = useState<BackupListResponse | null>(null);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewContent, setPreviewContent] =
    useState<BackupContentResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    fetchBackups();
  }, [refreshKey]);

  const fetchBackups = async () => {
    setLoading(true);
    try {
      const data = await dreamLogsApi.listBackups();
      setBackups(data);
    } catch (error) {
      console.error("Failed to fetch backups:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteFile = async (filename: string) => {
    try {
      const result = await dreamLogsApi.deleteBackup(filename);
      if (result.success) {
        message.success(t("dreamLogs.backup.deleteSuccess"));
        fetchBackups();
      } else {
        message.error(result.message);
      }
    } catch {
      message.error(t("dreamLogs.backup.deleteFailed"));
    }
  };

  const handleDeleteAll = async () => {
    Modal.confirm({
      title: t("dreamLogs.backup.deleteAllConfirm"),
      content: t("dreamLogs.backup.deleteAllMessage"),
      onOk: async () => {
        try {
          const result = await dreamLogsApi.deleteAllBackups();
          if (result.success) {
            message.success(t("dreamLogs.backup.deleteAllSuccess"));
            fetchBackups();
          } else {
            message.error(result.message);
          }
        } catch {
          message.error(t("dreamLogs.backup.deleteFailed"));
        }
      },
    });
  };

  const handlePreview = async (filename: string) => {
    setPreviewVisible(true);
    setPreviewLoading(true);
    try {
      const content = await dreamLogsApi.getBackupContent(filename);
      setPreviewContent(content);
    } catch {
      message.error(t("dreamLogs.backup.previewFailed"));
      setPreviewVisible(false);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleRollbackTask = (group: BackupTaskGroup) => {
    if (!group.record_id) return;
    Modal.confirm({
      title: t("dreamLogs.rollback.confirm"),
      content: t("dreamLogs.backup.rollbackTaskConfirm", {
        defaultValue: "确定要按本次治理任务回退全部文件吗？",
      }),
      onOk: async () => {
        try {
          const result = await dreamLogsApi.rollback(group.record_id);
          if (result.success) {
            message.success(t("dreamLogs.rollback.success"));
            fetchBackups();
          } else {
            message.error(result.message);
          }
        } catch {
          message.error(t("dreamLogs.rollback.failed"));
        }
      },
    });
  };

  const handleRollbackFile = (recordId: string, originalFile: string) => {
    if (!recordId || !originalFile) return;
    Modal.confirm({
      title: t("dreamLogs.rollback.confirm"),
      content: t("dreamLogs.backup.rollbackFileConfirm", {
        defaultValue: "确定要回退这个文件吗？",
      }),
      onOk: async () => {
        try {
          const result = await dreamLogsApi.rollback(recordId, [originalFile]);
          if (result.success) {
            message.success(t("dreamLogs.rollback.success"));
            fetchBackups();
          } else {
            message.error(result.message);
          }
        } catch {
          message.error(t("dreamLogs.rollback.failed"));
        }
      },
    });
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)}MB`;
  };

  const taskGroups = backups ? groupBackupFilesByTask(backups.files) : [];

  const fileColumns: ColumnsType<BackupFileInfo> = [
    {
      title: t("dreamLogs.backup.filename"),
      dataIndex: "filename",
      key: "filename",
      width: 250,
      render: (value: string) => <Tag icon={<FileOutlined />}>{value}</Tag>,
    },
    {
      title: t("dreamLogs.backup.originalFile"),
      dataIndex: "original_file",
      key: "original_file",
      width: 150,
    },
    {
      title: t("dreamLogs.backup.recordId"),
      dataIndex: "record_id",
      key: "record_id",
      width: 180,
      render: (value: string) => value || "-",
    },
    {
      title: t("dreamLogs.backup.timestamp"),
      dataIndex: "timestamp",
      key: "timestamp",
      width: 180,
      render: (value: string) =>
        value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "-",
    },
    {
      title: t("dreamLogs.backup.size"),
      dataIndex: "size",
      key: "size",
      width: 100,
      render: (value: number) => formatSize(value),
    },
    {
      title: t("dreamLogs.backup.createdAt"),
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 160,
      fixed: "right",
      render: (_, record) => (
        <Space>
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            aria-label={t("dreamLogs.backup.previewTitle")}
            onClick={() => handlePreview(record.filename)}
          />
          <Tooltip title={t("dreamLogs.rollback.single")}>
            <Button
              type="text"
              size="small"
              icon={<RollbackOutlined />}
              aria-label={`回退 ${record.original_file}`}
              disabled={!record.record_id || !record.original_file}
              onClick={() =>
                handleRollbackFile(record.record_id, record.original_file)
              }
            />
          </Tooltip>
          <Popconfirm
            title={t("dreamLogs.backup.deleteConfirm")}
            onConfirm={() => handleDeleteFile(record.filename)}
          >
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const taskColumns: ColumnsType<BackupTaskGroup> = [
    {
      title: t("dreamLogs.backup.task", { defaultValue: "治理任务" }),
      key: "task",
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Space>
            <HistoryOutlined />
            <Text strong>
              {record.record_id
                ? t("dreamLogs.backup.taskTitle", {
                    recordId: record.record_id,
                    defaultValue: `治理任务 ${record.record_id}`,
                  })
                : t("dreamLogs.backup.unlinkedTask", {
                    defaultValue: "未关联治理任务",
                  })}
            </Text>
          </Space>
          <Space size="small">
            {record.timestamp && (
              <Text type="secondary">
                <ClockCircleOutlined />{" "}
                {dayjs(record.timestamp).format("YYYY-MM-DD HH:mm:ss")}
              </Text>
            )}
            <Tag color="blue">
              {t("dreamLogs.backup.fileCount", {
                count: record.files.length,
                defaultValue: `${record.files.length} 个备份文件`,
              })}
            </Tag>
          </Space>
        </Space>
      ),
    },
    {
      title: t("dreamLogs.backup.totalSize"),
      dataIndex: "total_size",
      key: "total_size",
      width: 140,
      render: (value: number) => formatSize(value),
    },
    {
      title: t("dreamLogs.backup.createdAt"),
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 120,
      fixed: "right",
      render: (_, record) => (
        <Tooltip title={t("dreamLogs.rollback.all")}>
          <Button
            type="text"
            size="small"
            icon={<RollbackOutlined />}
            aria-label={`按任务回退 ${record.record_id}`}
            disabled={!record.record_id}
            onClick={() => handleRollbackTask(record)}
          />
        </Tooltip>
      ),
    },
  ];

  const renderTaskFiles = (group: BackupTaskGroup) => (
    <Table
      className={styles.customTable}
      columns={fileColumns}
      dataSource={group.files}
      rowKey="filename"
      pagination={false}
      size="small"
      scroll={{ x: 900 }}
    />
  );

  return (
    <div className={styles.container}>
      {backups && (
        <Row gutter={16} className={styles.statsRow}>
          <Col span={12}>
            <Card className={styles.subStatsCard}>
              <div className={styles.statContent}>
                <div
                  className={styles.statIconCircle}
                  style={{ background: "#f0f5ff", color: "#4f46e5" }}
                >
                  <FileOutlined />
                </div>
                <Statistic
                  title={t("dreamLogs.backup.totalFiles")}
                  value={backups.total_files}
                />
              </div>
            </Card>
          </Col>
          <Col span={12}>
            <Card className={styles.subStatsCard}>
              <div className={styles.statContent}>
                <div
                  className={styles.statIconCircle}
                  style={{ background: "#eef2ff", color: "#4f46e5" }}
                >
                  <DatabaseOutlined />
                </div>
                <Statistic
                  className={styles.statValue}
                  title={t("dreamLogs.backup.totalSize")}
                  value={formatSize(backups.total_size)}
                />
              </div>
            </Card>
          </Col>
        </Row>
      )}

      <Card
        className={styles.recordsCard}
        title={t("dreamLogs.backup.title")}
        extra={
          <Space>
            <Button
              type="primary"
              danger
              icon={<DeleteFilled />}
              onClick={handleDeleteAll}
              disabled={!backups || backups.total_files === 0}
            >
              {t("dreamLogs.backup.deleteAll")}
            </Button>
          </Space>
        }
      >
        <Spin spinning={loading}>
          {!backups || backups.files.length === 0 ? (
            <Empty
              description={t("dreamLogs.backup.noFiles")}
              style={{ padding: 40 }}
            />
          ) : (
            <Table
              className={styles.customTable}
              columns={taskColumns}
              dataSource={taskGroups}
              rowKey="key"
              pagination={false}
              expandable={{
                expandedRowRender: renderTaskFiles,
                expandIcon: ({ expanded, onExpand, record }) => (
                  <Button
                    type="text"
                    size="small"
                    icon={expanded ? <DownOutlined /> : <RightOutlined />}
                    aria-label={`${expanded ? "收起" : "展开"}治理任务 ${
                      record.record_id || record.key
                    }`}
                    onClick={(event) => onExpand(record, event)}
                  />
                ),
              }}
              scroll={{ x: 760 }}
            />
          )}
        </Spin>
      </Card>

      <Modal
        title={
          <Space>
            <FileOutlined />
            {t("dreamLogs.backup.previewTitle")}
            {previewContent && (
              <Text type="secondary">({previewContent.original_file})</Text>
            )}
          </Space>
        }
        open={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        footer={null}
        width={800}
      >
        <Spin spinning={previewLoading}>
          {previewContent && (
            <div style={{ maxHeight: 500, overflow: "auto" }}>
              <Space
                direction="vertical"
                style={{ width: "100%" }}
                size="small"
              >
                <Text type="secondary">
                  {t("dreamLogs.backup.filename")}: {previewContent.filename} |
                  {t("dreamLogs.backup.size")}:{" "}
                  {formatSize(previewContent.size)}
                </Text>
              </Space>
              <div
                className={styles.markdownContent}
                style={{
                  marginTop: 12,
                  padding: 12,
                  background: "#f5f5f5",
                  borderRadius: 8,
                }}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {previewContent.content}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </Spin>
      </Modal>
    </div>
  );
}
