import { useEffect, useMemo, useState } from "react";
import type { Key } from "react";
import { Alert, Space, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Button, Modal, Table } from "@agentscope-ai/design";
import api from "../../../../api";
import type {
  CronBroadcastChildItem,
  CronBroadcastChildOperationResult,
  CronBroadcastChildrenResponse,
  CronJobSpecOutput,
} from "../../../../api/types";

type CronJob = CronJobSpecOutput;
const { Text } = Typography;

const MODAL_WIDTH = 1280;
const MODAL_MAX_WIDTH = "calc(100vw - 48px)";
const TABLE_SCROLL_X = 1120;
const TABLE_SCROLL_Y = "calc(100vh - 380px)";

interface BroadcastChildrenModalProps {
  open: boolean;
  job: CronJob | null;
  onClose: () => void;
}

function rowKey(item: CronBroadcastChildItem): string {
  return `${item.tenant_id}:${item.job_id}`;
}

function resultLine(item: CronBroadcastChildOperationResult): string {
  const base = `${item.tenant_id} / ${item.job_id}`;
  if (item.status === "skipped") {
    return `${base}: 已暂停，未执行`;
  }
  if (item.success) {
    return `${base}: ${item.status}`;
  }
  return `${base}: ${item.message || "failed"}`;
}

function buildDuplicateTenantNameSummaries(
  children: CronBroadcastChildItem[],
): string[] {
  const counts = new Map<string, number>();
  children.forEach((item) => {
    const name = item.tenant_name?.trim();
    if (!name) return;
    counts.set(name, (counts.get(name) || 0) + 1);
  });
  return Array.from(counts.entries())
    .filter(([, count]) => count > 1)
    .map(([name, count]) => `${name} (${count} 个 UID)`);
}

function renderTenantCell(record: CronBroadcastChildItem) {
  if (!record.tenant_name) {
    return <Text>{record.tenant_id}</Text>;
  }
  return (
    <Space direction="vertical" size={0}>
      <Text strong>{record.tenant_name}</Text>
      <Text type="secondary" code>
        {record.tenant_id}
      </Text>
    </Space>
  );
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN");
}

export function BroadcastChildrenModal({
  open,
  job,
  onClose,
}: BroadcastChildrenModalProps) {
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [children, setChildren] = useState<CronBroadcastChildItem[]>([]);
  const [lookupStatus, setLookupStatus] = useState<
    CronBroadcastChildrenResponse["status"]
  >("idle");
  const [tenantCount, setTenantCount] = useState(0);
  const [failedTenants, setFailedTenants] = useState(0);
  const [failureSummary, setFailureSummary] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const [operationResults, setOperationResults] = useState<
    CronBroadcastChildOperationResult[]
  >([]);

  const selectedItems = useMemo(() => {
    const selected = new Set(selectedRowKeys.map(String));
    return children.filter((item) => selected.has(rowKey(item)));
  }, [children, selectedRowKeys]);
  const duplicateTenantNameSummaries = useMemo(
    () => buildDuplicateTenantNameSummaries(children),
    [children],
  );
  const hasFailedResults = operationResults.some((result) => !result.success);
  const isLookupRunning = lookupStatus === "running";

  const applySnapshot = (response: CronBroadcastChildrenResponse) => {
    setChildren(response.items || []);
    setLookupStatus(response.status || "idle");
    setTenantCount(response.tenant_count || 0);
    setFailedTenants(response.failed_tenants || 0);
    setFailureSummary(response.failure_summary || null);
    setUpdatedAt(response.updated_at || null);
  };

  const loadChildren = async () => {
    if (!job) return;
    setLoading(true);
    try {
      const response = await api.listCronBroadcastChildren(job.id);
      applySnapshot(response);
      setSelectedRowKeys([]);
    } finally {
      setLoading(false);
    }
  };

  const triggerBackgroundRefresh = async () => {
    if (!job) return;
    setRefreshing(true);
    try {
      const response = await api.refreshCronBroadcastChildren(job.id);
      applySnapshot(response);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (!open) {
      setChildren([]);
      setLookupStatus("idle");
      setTenantCount(0);
      setFailedTenants(0);
      setFailureSummary(null);
      setUpdatedAt(null);
      setSelectedRowKeys([]);
      setOperationResults([]);
      return;
    }
    void (async () => {
      await loadChildren();
      await triggerBackgroundRefresh();
    })();
  }, [open, job?.id]);

  const batchRefs = selectedItems.map((item) => ({
    tenant_id: item.tenant_id,
    job_id: item.job_id,
  }));

  const handleDelete = async () => {
    if (!job || batchRefs.length === 0) return;
    setSubmitting(true);
    try {
      const response = await api.deleteCronBroadcastChildren(job.id, batchRefs);
      setOperationResults(response.results || []);
      await loadChildren();
    } finally {
      setSubmitting(false);
    }
  };

  const handleRun = async () => {
    if (!job || batchRefs.length === 0) return;
    setSubmitting(true);
    try {
      const response = await api.runCronBroadcastChildren(job.id, batchRefs);
      setOperationResults(response.results || []);
      await loadChildren();
    } finally {
      setSubmitting(false);
    }
  };

  let dataTimeText = "尚未生成";
  if (isLookupRunning) {
    dataTimeText = updatedAt
      ? `${formatDateTime(updatedAt)}（刷新中）`
      : "正在生成中";
  } else if (updatedAt) {
    dataTimeText = formatDateTime(updatedAt);
  }
  let lookupStatusText = "未生成";
  if (isLookupRunning) {
    lookupStatusText = "生成中";
  } else if (lookupStatus === "completed") {
    lookupStatusText = "已生成";
  } else if (lookupStatus === "failed") {
    lookupStatusText = "失败";
  }
  const tableEmptyText = isLookupRunning
    ? "正在生成中"
    : lookupStatus === "idle"
      ? "点击刷新生成分发用户列表"
      : "当前任务尚未分发给任何用户";

  const columns: ColumnsType<CronBroadcastChildItem> = [
    {
      title: "用户",
      key: "tenant",
      width: 220,
      render: (_: unknown, record) => renderTenantCell(record),
    },
    {
      title: "机构",
      dataIndex: "bbk_id",
      key: "bbk_id",
      width: 120,
      render: (value?: string | null) => value || "-",
    },
    {
      title: "子任务ID",
      dataIndex: "job_id",
      key: "job_id",
      width: 220,
    },
    {
      title: "状态",
      key: "enabled",
      width: 110,
      render: (_: unknown, record) =>
        record.enabled ? (
          <Tag color="green">启用</Tag>
        ) : (
          <Tag color="default">已暂停</Tag>
        ),
    },
    {
      title: "Cron",
      dataIndex: "cron",
      key: "cron",
      width: 160,
    },
    {
      title: "时区",
      dataIndex: "timezone",
      key: "timezone",
      width: 140,
    },
    {
      title: "错峰",
      dataIndex: "offset_minutes",
      key: "offset_minutes",
      width: 100,
      render: (value: number) => `${value || 0} 分钟`,
    },
    {
      title: "最近状态",
      dataIndex: "last_status",
      key: "last_status",
      width: 120,
      render: (value?: string | null) => value || "-",
    },
  ];

  return (
    <Modal
      open={open}
      title={job ? `分发用户 / 子任务：${job.name}` : "分发用户 / 子任务"}
      onCancel={submitting ? undefined : onClose}
      footer={null}
      style={{ maxWidth: MODAL_MAX_WIDTH }}
      width={MODAL_WIDTH}
    >
      <div style={{ display: "grid", gap: 12, minWidth: 0 }}>
        {duplicateTenantNameSummaries.length > 0 && (
          <Alert
            type="warning"
            showIcon
            message="存在同名用户，请以 UID 区分"
            description={duplicateTenantNameSummaries.join("、")}
          />
        )}

        <Space wrap>
          <Button onClick={loadChildren} loading={loading}>
            刷新
          </Button>
          <Text type="secondary">状态：{lookupStatusText}</Text>
          <Text type="secondary">扫描用户：{tenantCount}</Text>
          {failedTenants > 0 && (
            <Text type="warning">读取失败：{failedTenants}</Text>
          )}
          <Text type="secondary">数据时间：{dataTimeText}</Text>
          <Button
            danger
            disabled={selectedItems.length === 0}
            loading={submitting}
            onClick={() => {
              Modal.confirm({
                title: "删除选中的子定时任务？",
                content: "只会删除子定时任务，不影响当前源任务。",
                okText: "删除",
                okButtonProps: { danger: true },
                cancelText: "取消",
                onOk: handleDelete,
              });
            }}
          >
            批量删除
          </Button>
          <Button
            disabled={selectedItems.length === 0}
            loading={submitting}
            onClick={handleRun}
          >
            批量重跑
          </Button>
        </Space>

        {failureSummary && (
          <Alert type="warning" showIcon message={failureSummary} />
        )}

        {operationResults.length > 0 && (
          <Alert
            type={hasFailedResults ? "warning" : "success"}
            showIcon
            message="批量操作结果"
            description={
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                {operationResults.map(resultLine).join("\n")}
              </pre>
            }
          />
        )}

        <Table
          rowKey={rowKey}
          columns={columns}
          dataSource={children}
          loading={loading || refreshing}
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
          }}
          pagination={{ pageSize: 8 }}
          locale={{ emptyText: tableEmptyText }}
          scroll={{ x: TABLE_SCROLL_X, y: TABLE_SCROLL_Y }}
        />
      </div>
    </Modal>
  );
}
