import { useState, useEffect, useRef } from "react";
import {
  Button,
  Card,
  Form,
  InputNumber,
  Modal,
  Switch,
  Table,
} from "@agentscope-ai/design";
import type {
  CronBroadcastTarget,
  CronBroadcastTenantResult,
  CronJobSpecOutput,
} from "../../../api/types";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import {
  createColumns,
  JobDrawer,
  useCronJobs,
  DEFAULT_FORM_VALUES,
  BroadcastChildrenModal,
  isBroadcastChildJob,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import { TenantSelector } from "@/components/TenantSelector";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { getUserId } from "../../../utils/identity";
import {
  buildExecutionModelKey,
  useExecutionModelOptions,
} from "@/hooks/useExecutionModelOptions";
import {
  buildCronJobFormValues,
  buildCronJobSubmitPayload,
  getBroadcastResultMessage,
} from "./helpers";
import styles from "./index.module.less";

type CronJob = CronJobSpecOutput;
const DEFAULT_BROADCAST_OFFSET_WINDOW_HOURS = 4;

function CronJobsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const {
    jobs,
    loading,
    createJob,
    updateJob,
    deleteJob,
    toggleEnabled,
    executeNow,
  } = useCronJobs();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<CronJob | null>(null);
  const [broadcastingJob, setBroadcastingJob] = useState<CronJob | null>(null);
  const [selectedBroadcastTenantIds, setSelectedBroadcastTenantIds] = useState<
    string[]
  >([]);
  const [selectedBroadcastTargets, setSelectedBroadcastTargets] = useState<
    CronBroadcastTarget[]
  >([]);
  const [broadcastResults, setBroadcastResults] = useState<
    CronBroadcastTenantResult[]
  >([]);
  const [broadcastOffsetEnabled, setBroadcastOffsetEnabled] = useState(true);
  const [broadcastOffsetWindowHours, setBroadcastOffsetWindowHours] = useState(
    DEFAULT_BROADCAST_OFFSET_WINDOW_HOURS,
  );
  const [childrenManagementJob, setChildrenManagementJob] =
    useState<CronJob | null>(null);
  const [broadcasting, setBroadcasting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<CronJob>();
  const userTimezoneRef = useRef("UTC");
  const currentTenantId = getUserId();
  const {
    loading: executionModelLoading,
    options: executionModelOptions,
    tenantDefaultLabel,
  } = useExecutionModelOptions(true);

  useEffect(() => {
    api
      .getUserTimezone()
      .then((res) => {
        if (res.timezone) userTimezoneRef.current = res.timezone;
      })
      .catch((err) => console.error("Failed to fetch user timezone:", err));
  }, []);

  const handleCreate = () => {
    setEditingJob(null);
    form.resetFields();
    form.setFieldsValue({
      ...DEFAULT_FORM_VALUES,
      schedule: {
        ...DEFAULT_FORM_VALUES.schedule,
        timezone: userTimezoneRef.current,
      },
      execution_model_key: buildExecutionModelKey(undefined),
    } as any);
    setDrawerOpen(true);
  };

  const handleEdit = (job: CronJob) => {
    setEditingJob(job);
    form.setFieldsValue(buildCronJobFormValues(job) as any);
    setDrawerOpen(true);
  };

  const handleDelete = (jobId: string) => {
    Modal.confirm({
      title: t("cronJobs.confirmDelete"),
      content: t("cronJobs.deleteConfirm"),
      okText: t("cronJobs.deleteText"),
      okType: "primary",
      cancelText: t("cronJobs.cancelText"),
      onOk: async () => {
        await deleteJob(jobId);
      },
    });
  };

  const handleToggleEnabled = async (job: CronJob) => {
    await toggleEnabled(job);
  };

  const handleExecuteNow = async (job: CronJob) => {
    Modal.confirm({
      title: t("cronJobs.executeNowTitle"),
      content: t("cronJobs.executeNowContent", { name: job.name }),
      okText: t("cronJobs.executeNowConfirm"),
      okType: "primary",
      cancelText: t("cronJobs.cancelText"),
      onOk: async () => {
        await executeNow(job.id);
      },
    });
  };

  const handleBroadcast = (job: CronJob) => {
    if (isBroadcastChildJob(job)) {
      message.warning("分发子任务不支持广播到租户");
      return;
    }
    setBroadcastingJob(job);
    setSelectedBroadcastTenantIds([]);
    setSelectedBroadcastTargets([]);
    setBroadcastResults([]);
    setBroadcastOffsetEnabled(true);
    setBroadcastOffsetWindowHours(DEFAULT_BROADCAST_OFFSET_WINDOW_HOURS);
  };

  const handleManageChildren = (job: CronJob) => {
    if (isBroadcastChildJob(job)) {
      message.warning("分发子任务不支持查看分发用户");
      return;
    }
    setChildrenManagementJob(job);
  };

  const handleBroadcastCancel = () => {
    setBroadcastingJob(null);
    setSelectedBroadcastTenantIds([]);
    setSelectedBroadcastTargets([]);
    setBroadcastResults([]);
    setBroadcastOffsetEnabled(true);
    setBroadcastOffsetWindowHours(DEFAULT_BROADCAST_OFFSET_WINDOW_HOURS);
  };

  const handleBroadcastOffsetWindowChange = (
    value: number | string | null,
  ) => {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) {
      setBroadcastOffsetWindowHours(DEFAULT_BROADCAST_OFFSET_WINDOW_HOURS);
      return;
    }
    setBroadcastOffsetWindowHours(
      Math.min(24, Math.max(1, Math.round(numericValue))),
    );
  };

  const handleBroadcastConfirm = async () => {
    if (!broadcastingJob) return;
    const targetTenantIds = Array.from(new Set(selectedBroadcastTenantIds));
    const targetByTenantId = new Map(
      selectedBroadcastTargets.map((target) => [target.tenant_id, target]),
    );
    const targets = targetTenantIds.map((tenantId) => {
      const target = targetByTenantId.get(tenantId);
      return {
        tenant_id: tenantId,
        tenant_name: target?.tenant_name ?? null,
        bbk_id: target?.bbk_id ?? null,
      };
    });
    setBroadcasting(true);
    try {
      const res = await api.broadcastCronJob(
        broadcastingJob.id,
        targets,
        {
          enable_offset: broadcastOffsetEnabled,
          offset_window_hours: broadcastOffsetWindowHours,
        },
      );
      const resultMessage = getBroadcastResultMessage(res.results);
      if (resultMessage.tone === "warning") {
        message.warning(resultMessage.text);
      } else {
        message.success(resultMessage.text);
      }
      setBroadcastResults(res.results);
    } catch (error) {
      console.error("Failed to broadcast cron job", error);
      message.error("Broadcast failed");
    } finally {
      setBroadcasting(false);
    }
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingJob(null);
  };

  const handleSubmit = async (values: any) => {
    let processedValues;
    try {
      processedValues = buildCronJobSubmitPayload(values);
    } catch (error) {
      console.error("❌ Failed to normalize cron job payload:", error);
      return;
    }

    let success = false;
    setSaving(true);
    try {
      if (editingJob) {
        success = await updateJob(editingJob.id, processedValues);
      } else {
        success = await createJob(processedValues);
      }
    } finally {
      setSaving(false);
    }
    if (success) {
      setDrawerOpen(false);
    }
  };

  const columns = createColumns({
    onToggleEnabled: handleToggleEnabled,
    onExecuteNow: handleExecuteNow,
    onBroadcast: handleBroadcast,
    onManageChildren: handleManageChildren,
    onEdit: handleEdit,
    onDelete: handleDelete,
    onCopySuccess: () => message.success(t("common.copied")),
    onCopyError: () => message.error(t("common.copyFailed")),
    executionModelOptions,
    tenantDefaultModelLabel: tenantDefaultLabel,
    t,
  });

  return (
    <div className={styles.cronJobsPage}>
      <PageHeader
        items={[{ title: t("nav.runCenter") }, { title: t("cronJobs.title") }]}
        extra={
          <Button type="primary" onClick={handleCreate}>
            + {t("cronJobs.createJob")}
          </Button>
        }
      />

      <Card className={styles.tableCard} bodyStyle={{ padding: 0 }}>
        <Table
          columns={columns}
          dataSource={jobs}
          loading={loading}
          rowKey="id"
          scroll={{ x: 3010 }}
          pagination={{
            pageSize: 10,
          }}
        />
      </Card>

      <JobDrawer
        open={drawerOpen}
        editingJob={editingJob}
        form={form}
        saving={saving}
        executionModelOptions={executionModelOptions}
        executionModelLoading={executionModelLoading}
        tenantDefaultModelLabel={tenantDefaultLabel}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />

      <BroadcastChildrenModal
        open={Boolean(childrenManagementJob)}
        job={childrenManagementJob}
        onClose={() => setChildrenManagementJob(null)}
      />

      <Modal
        open={Boolean(broadcastingJob)}
        title="广播到租户"
        onCancel={handleBroadcastCancel}
        onOk={handleBroadcastConfirm}
        confirmLoading={broadcasting}
        okButtonProps={{
          disabled: selectedBroadcastTenantIds.length === 0,
        }}
        width={640}
      >
        {broadcastingJob && (
          <div style={{ display: "grid", gap: 12 }}>
            <div>
              任务：{broadcastingJob.name}；时区：
              {broadcastingJob.schedule?.timezone || "UTC"}；
              {broadcastOffsetEnabled
                ? `优先在原执行时间前 ${broadcastOffsetWindowHours} 小时内均匀错峰，无法安全错峰的 cron 会按原表达式分发。`
                : "按原执行时间分发，不做错峰。"}
            </div>
            <div className={styles.broadcastOffsetControls}>
              <div className={styles.broadcastOffsetSwitch}>
                <span>启用错峰</span>
                <Switch
                  checked={broadcastOffsetEnabled}
                  onChange={(checked) =>
                    setBroadcastOffsetEnabled(Boolean(checked))
                  }
                />
              </div>
              <div className={styles.broadcastOffsetWindow}>
                <span>错峰窗口</span>
                <InputNumber
                  min={1}
                  max={24}
                  precision={0}
                  value={broadcastOffsetWindowHours}
                  disabled={!broadcastOffsetEnabled}
                  onChange={handleBroadcastOffsetWindowChange}
                />
                <span>小时</span>
              </div>
            </div>
            <TenantSelector
              selectedTenantIds={selectedBroadcastTenantIds}
              onChange={setSelectedBroadcastTenantIds}
              onSelectionInfoChange={setSelectedBroadcastTargets}
              hint="选择需要接收该定时任务的租户"
              excludeTenantId={currentTenantId}
            />
            {broadcastResults.length > 0 && (
              <div style={{ display: "grid", gap: 6 }}>
                {broadcastResults.map((item) => (
                  <div key={item.tenant_id}>
                    <div>
                      {item.tenant_id}:{" "}
                      {item.success
                        ? `${item.cron} (${item.timezone})`
                        : item.error || "failed"}
                    </div>
                    {item.warning ? (
                      <div style={{ color: "#d46b08", fontSize: 12 }}>
                        {item.warning}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

export default CronJobsPage;
