import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  EditOutlined,
  HistoryOutlined,
  MoreOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Checkbox, Collapse, Dropdown, Input, message, Modal, Spin, Table, Tag, Tooltip, Typography, type MenuProps } from "antd";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Send, Undo2, Trash2, Archive, Users, PhoneCall, Tag as TagIcon, GitBranch, Calendar, CheckCircle } from "lucide-react";
import { marketApi, MarketSkillDetail } from "../../api/modules/market";
import type { FileContentResponse } from "../../api/modules/mySkills";
import type { DistributionRecord } from "../../api/types";
import { BBK_ID_TO_NAME_MAP } from "../../constants/bbk";
import { VersionHistoryModal } from "./Skills/VersionHistoryModal";
import styles from "./SkillDetailDrawer.module.less";

const { Text, Title } = Typography;

interface SkillDetailDrawerProps {
  open: boolean;
  skill: MarketSkillDetail | null;
  onClose: () => void;
  isManager?: boolean;
  onDistribute?: () => void;
  onLookupOwners?: () => void;
  onRecall?: () => void;
  onUnpublish?: () => void;
  onDelete?: () => void;
  sourceId?: string;
  onRefresh?: () => void;
  categoryName?: string;
}

const FRONTMATTER_PATTERN = /^---\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/;

// 顶栏样式 - 固定在顶部
const HEADER_STYLE = {
  position: "sticky",
  top: 0,
  zIndex: 10,
  padding: "12px 20px",
  backgroundColor: "#fff",
  borderBottom: "1px solid #f0f0f0",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
} as const;

// 元数据项样式 - 淡色小字
const META_ITEM_STYLE = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  fontSize: 12,
  color: "#8c8c8c",
} as const;

// 中文名样式 - 稍大
const CHINESE_NAME_STYLE = {
  fontSize: 14,
  fontWeight: 500,
  color: "#1a1a1a",
} as const;

// 技能名样式 - 小号
const SKILL_NAME_STYLE = {
  fontSize: 12,
  color: "#8c8c8c",
} as const;

// 操作按钮样式 - 次要按钮（版本历史）
const SECONDARY_BUTTON_STYLE = {
  height: 28,
  padding: "0 10px",
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 500,
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  border: "1px solid #d9d9d9",
  backgroundColor: "#fafafa",
  color: "#595959",
} as const;

// 主要按钮样式（分发）
const PRIMARY_BUTTON_STYLE = {
  height: 28,
  padding: "0 12px",
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 500,
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  backgroundColor: "#3769fc",
  color: "#fff",
  border: "none",
} as const;

// 信息按钮样式（用户可执行性）
const INFO_BUTTON_STYLE = {
  height: 28,
  padding: "0 10px",
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 500,
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  border: "1px solid #3769fc",
  backgroundColor: "#fff",
  color: "#3769fc",
} as const;

// 更多按钮样式（下拉）
const MORE_BUTTON_STYLE = {
  height: 28,
  padding: "0 8px",
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 500,
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  border: "1px solid #d9d9d9",
  backgroundColor: "#fff",
  color: "#595959",
} as const;

// 统计徽章样式
const STAT_TAG_STYLE = {
  margin: 0,
  borderRadius: 6,
  paddingInline: 8,
  paddingBlock: 2,
  fontSize: 12,
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
} as const;

function formatDate(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN");
}

function formatMetricValue(value: number | null): string {
  if (value === null) return "0";
  if (value >= 100000000) return `${(value / 100000000).toFixed(1)}亿`;
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

function splitMarkdownFrontmatter(
  fileType: string | null,
  fileContent: string | null,
): string | null {
  if (fileType !== "markdown" || typeof fileContent !== "string") {
    return fileContent;
  }
  const match = fileContent.match(FRONTMATTER_PATTERN);
  if (!match) {
    return fileContent;
  }
  return fileContent.slice(match[0].length).trim();
}

function renderPreviewContent(
  fileType: string | null,
  fileContent: string | null,
  fallbackDescription: string | null = null,
): ReactNode {
  // 加载失败时显示 fallback description
  if (fileContent === null && fallbackDescription) {
    return (
      <div className={styles.streamingMarkdown}>
        <Text style={{ fontSize: 14, color: "#1a1a1a", lineHeight: 1.7 }}>
          {fallbackDescription}
        </Text>
      </div>
    );
  }

  if (fileContent === null) {
    return (
      <Text type="secondary" style={{ fontSize: 13 }}>
        暂无文档内容
      </Text>
    );
  }

  if (fileType === "binary") {
    return (
      <div
        style={{
          width: "100%",
          boxSizing: "border-box",
          border: "1px dashed #d9d9d9",
          borderRadius: 8,
          padding: 24,
          backgroundColor: "#fafafa",
          textAlign: "center",
        }}
      >
        <Text type="secondary">该文件为二进制内容，当前仅支持只读占位预览。</Text>
      </div>
    );
  }

  if (fileType === "markdown") {
    const previewContent = splitMarkdownFrontmatter(fileType, fileContent) ?? "";
    return (
      <div
        style={{
          width: "100%",
          maxWidth: "100%",
          boxSizing: "border-box",
        }}
      >
        <div
          className={styles.streamingMarkdown}
          data-testid="skill-markdown-preview"
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {previewContent}
          </ReactMarkdown>
        </div>
      </div>
    );
  }

  if (fileType === "json") {
    let formatted = fileContent;
    try {
      formatted = JSON.stringify(JSON.parse(fileContent), null, 2);
    } catch {
      // 解析失败时回退原始内容，避免预览中断
    }
    return (
      <pre
        style={{
          margin: 0,
          width: "100%",
          boxSizing: "border-box",
          backgroundColor: "#1f1f1f",
          color: "#f5f5f5",
          borderRadius: 8,
          padding: 16,
          overflow: "auto",
          fontSize: 13,
          lineHeight: 1.6,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          overflowWrap: "anywhere",
        }}
      >
        {formatted}
      </pre>
    );
  }

  return (
    <pre
      style={{
        margin: 0,
        width: "100%",
        boxSizing: "border-box",
        backgroundColor: "#fafafa",
        borderRadius: 8,
        padding: 16,
        border: "1px solid #f0f0f0",
        overflow: "auto",
        fontSize: 13,
        lineHeight: 1.6,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        overflowWrap: "anywhere",
      }}
    >
      {fileContent}
    </pre>
  );
}

export function SkillDetailDrawer(
  props: SkillDetailDrawerProps,
) {
  const {
    open,
    skill,
    isManager,
    onDistribute,
    onLookupOwners,
    onRecall,
    onUnpublish,
    onDelete,
    sourceId,
    categoryName,
    onRefresh,
  } = props;
  const [fileDetail, setFileDetail] = useState<FileContentResponse | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const normalizedCategoryName = categoryName?.trim();

  // 编辑中文名相关状态
  const [isEditing, setIsEditing] = useState(false);
  const [draftCnName, setDraftCnName] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [syncModalOpen, setSyncModalOpen] = useState(false);
  const [distributions, setDistributions] = useState<DistributionRecord[]>([]);
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [syncToUsers, setSyncToUsers] = useState(true);

  // 分发记录去重（同一用户多次分发只保留最新记录）
  const uniqueDistributions = useMemo(() => {
    const userMap = new Map<string, DistributionRecord>();
    for (const dist of distributions) {
      const existing = userMap.get(dist.target_user_id);
      if (
        !existing ||
        (dist.distributed_at &&
          (!existing.distributed_at || dist.distributed_at > existing.distributed_at))
      ) {
        userMap.set(dist.target_user_id, dist);
      }
    }
    return Array.from(userMap.values());
  }, [distributions]);

  // 按机构分组分发记录
  const groupedDistributions = useMemo(() => {
    const groups: Record<string, DistributionRecord[]> = {};
    for (const dist of uniqueDistributions) {
      const bbkId = dist.target_bbk_id || "unknown";
      if (!groups[bbkId]) {
        groups[bbkId] = [];
      }
      groups[bbkId].push(dist);
    }
    return Object.entries(groups).map(([bbkId, records]) => ({
      bbkId,
      bbkName: bbkId === "unknown" ? "未分配机构" : BBK_ID_TO_NAME_MAP[bbkId] || bbkId,
      records,
    }));
  }, [uniqueDistributions]);

  // 编辑开始
  const handleEditStart = useCallback(() => {
    setIsEditing(true);
    setDraftCnName(skill?.chinese_name || "");
  }, [skill?.chinese_name]);

  // 编辑取消
  const handleEditCancel = useCallback(() => {
    setIsEditing(false);
    setDraftCnName("");
    setSyncModalOpen(false);
  }, []);

  // 执行保存
  const handleSave = useCallback(async (sync: boolean, userIds: string[]) => {
    if (!skill || !sourceId) return;

    setIsSaving(true);
    try {
      await marketApi.updateSkillCnName(sourceId, skill.item_id, {
        skill_id: skill.skill_id || "",
        chinese_name: draftCnName,
        sync_to_users: sync,
        target_user_ids: userIds,
      });
      message.success("保存成功");
      setIsEditing(false);
      setSyncModalOpen(false);
      onRefresh?.();
    } catch {
      message.error("保存失败");
    } finally {
      setIsSaving(false);
    }
  }, [skill, sourceId, draftCnName, onRefresh]);

  // 保存点击：检查是否有分发记录
  const handleSaveClick = useCallback(async () => {
    if (!skill || !sourceId) return;

    if (draftCnName === skill.chinese_name) {
      message.info("名称未变化");
      setIsEditing(false);
      return;
    }

    // 查询分发记录
    try {
      const dists = await marketApi.getSkillDistributions(sourceId, skill.item_id);
      setDistributions(dists);
      // 默认选中去重后的用户ID
      const uniqueIds = Array.from(new Set(dists.map((d) => d.target_user_id)));
      setSelectedUserIds(uniqueIds);
      if (uniqueIds.length > 0) {
        setSyncModalOpen(true);
      } else {
        // 无分发记录，直接保存
        await handleSave(false, []);
      }
    } catch {
      // 查询失败时直接保存（不同步）
      await handleSave(false, []);
    }
  }, [skill, sourceId, draftCnName, handleSave]);

  // 同步确认弹窗确认
  const handleSyncConfirm = useCallback(() => {
    handleSave(syncToUsers, syncToUsers ? selectedUserIds : []);
  }, [handleSave, syncToUsers, selectedUserIds]);

  const moreMenuItems: MenuProps["items"] = useMemo(() => {
    const items: MenuProps["items"] = [];
    if (onRecall) {
      items.push({
        key: "recall",
        icon: <Undo2 size={12} />,
        label: "撤回",
        onClick: onRecall,
      });
    }
    if (onUnpublish) {
      items.push({
        key: "unpublish",
        icon: <Archive size={12} />,
        label: "下架",
        onClick: () => {
          Modal.confirm({
            title: "确认下架此技能？",
            content: "下架后用户将无法查看此技能，但数据仍保留",
            okText: "下架",
            cancelText: "取消",
            onOk: onUnpublish,
          });
        },
      });
    }
    if (onDelete) {
      items.push({
        key: "delete",
        icon: <Trash2 size={12} />,
        label: "删除",
        danger: true,
        onClick: () => {
          Modal.confirm({
            title: "彻底删除此技能？",
            content: "删除后技能文件和版本历史将全部清除，无法恢复",
            okText: "删除",
            okButtonProps: { danger: true },
            cancelText: "取消",
            onOk: onDelete,
          });
        },
      });
    }
    return items;
  }, [onRecall, onUnpublish, onDelete]);

  useEffect(() => {
    if (!open || !skill || !sourceId) {
      return;
    }

    let cancelled = false;
    setFileLoading(true);
    setPreviewError(null);
    setFileDetail(null);

    marketApi.readSkillFile(sourceId, skill.item_id, "SKILL.md")
      .then((data) => {
        if (!cancelled) {
          setFileDetail(data);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPreviewError("暂未获取到 Skill 文档预览");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setFileLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [open, skill, sourceId]);

  const userStatsColumns = useMemo(
    () => [
      {
        title: "用户ID",
        dataIndex: "user_id",
        key: "user_id",
        width: "30%",
      },
      {
        title: "用户名称",
        dataIndex: "user_name",
        key: "user_name",
        width: "40%",
      },
      {
        title: "调用次数",
        dataIndex: "call_count",
        key: "call_count",
        width: "30%",
        align: "right" as const,
        sorter: (
          a: { call_count: number },
          b: { call_count: number },
        ) => a.call_count - b.call_count,
      },
    ],
    [],
  );

  if (!open || !skill) {
    return null;
  }

  // 中文名和技能名
  const chineseName = skill.chinese_name?.trim() || "";
  const skillName = skill.name;

  // 状态颜色和文字
  const statusColor = skill.status === "active" ? "#52c41a" : "#ff4d4f";
  const statusText = skill.status === "active" ? "已发布" : "已下架";

  // 简介
  const description = skill.description || "暂无描述";

  return (
    <>
      <div style={{ height: "100%", display: "flex", flexDirection: "column", backgroundColor: "#fafafa" }}>
        {/* 顶栏：固定 */}
        <div style={HEADER_STYLE}>
          {/* 左侧：元数据 */}
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {/* 状态徽章（标题前） */}
            <Tag
              bordered={false}
              style={{
                margin: 0,
                borderRadius: 6,
                padding: "2px 8px",
                fontSize: 12,
                backgroundColor: skill.status === "active" ? "#f6ffed" : "#fff1f0",
                color: statusColor,
              }}
            >
              <CheckCircle size={12} style={{ marginRight: 4 }} />
              {statusText}
            </Tag>

            {/* 中文名（大号） + 技能名（小号） */}
            {isEditing ? (
              <Input
                value={draftCnName}
                onChange={(e) => setDraftCnName(e.target.value)}
                style={{ width: 200, fontSize: 14 }}
                maxLength={50}
                showCount
                placeholder="输入中文名称"
              />
            ) : (
              <span style={CHINESE_NAME_STYLE}>
                {chineseName}
                {chineseName && skillName && (
                  <span style={SKILL_NAME_STYLE}> ({skillName})</span>
                )}
                {!chineseName && skillName && (
                  <span style={CHINESE_NAME_STYLE}>{skillName}</span>
                )}
              </span>
            )}

            {/* 编辑按钮 */}
            {isManager && !isEditing && (
              <Tooltip title="编辑中文名">
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined style={{ fontSize: 12, color: "#3769fc" }} />}
                  onClick={handleEditStart}
                  style={{ padding: 4 }}
                />
              </Tooltip>
            )}

            {/* 编辑时显示保存/取消按钮 */}
            {isManager && isEditing && (
              <>
                <Button
                  size="small"
                  onClick={handleEditCancel}
                  disabled={isSaving}
                  style={{ height: 24, borderRadius: 4 }}
                >
                  取消
                </Button>
                <Button
                  size="small"
                  type="primary"
                  onClick={handleSaveClick}
                  loading={isSaving}
                  style={{ height: 24, borderRadius: 4 }}
                >
                  保存
                </Button>
              </>
            )}

            {/* 分类 */}
            {normalizedCategoryName && (
              <span style={META_ITEM_STYLE}>
                <TagIcon size={12} />
                {normalizedCategoryName}
              </span>
            )}

            {/* 版本 */}
            <span style={META_ITEM_STYLE}>
              <GitBranch size={12} />
              v{skill.version}
            </span>

            {/* 创建时间 */}
            <span style={META_ITEM_STYLE}>
              <Calendar size={12} />
              {formatDate(skill.created_at)}
            </span>

            {/* 创建人 */}
            <span style={META_ITEM_STYLE}>
              <Users size={12} />
              {skill.creator_name || "未知"}
            </span>
          </div>

          {/* 右侧：操作按钮 */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Button
              onClick={() => setVersionHistoryOpen(true)}
              style={SECONDARY_BUTTON_STYLE}
            >
              <HistoryOutlined style={{ fontSize: 12 }} />
              版本历史
            </Button>
            {isManager && onDistribute && (
              <Button
                type="primary"
                onClick={onDistribute}
                style={PRIMARY_BUTTON_STYLE}
              >
                <Send size={12} />
                分发
              </Button>
            )}
            {isManager && onLookupOwners && (
              <Button
                onClick={onLookupOwners}
                style={INFO_BUTTON_STYLE}
              >
                <UserOutlined style={{ fontSize: 12 }} />
                用户可执行性
              </Button>
            )}
            {isManager && moreMenuItems.length > 0 && (
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button style={MORE_BUTTON_STYLE}>
                  <MoreOutlined style={{ fontSize: 12 }} />
                </Button>
              </Dropdown>
            )}
          </div>
        </div>

        {/* 主区域：文档 + 用户明细 */}
        <div
          style={{
            display: "flex",
            gap: 12,
            padding: 16,
            flex: 1,
            minHeight: 0,
          }}
        >
          {/* 左侧：简介 + 文档内容（可滚动） */}
          <div
            style={{
              flex: isManager ? "1 1 auto" : "1 1 100%",
              minWidth: 0,
              backgroundColor: "#fff",
              borderRadius: 8,
              padding: 20,
              overflow: "auto",
            }}
          >
            {/* 简介 */}
            <div style={{ marginBottom: 16, paddingBottom: 16, borderBottom: "1px solid #f0f0f0" }}>
              <Text style={{ fontSize: 14, color: "#595959", lineHeight: 1.6 }}>
                {description}
              </Text>
            </div>

            {/* 文档内容 */}
            {previewError ? (
              <Text type="secondary">{previewError}</Text>
            ) : fileLoading ? (
              <div
                style={{
                  display: "flex",
                  justifyContent: "center",
                  alignItems: "center",
                  minHeight: 200,
                }}
              >
                <Spin />
              </div>
            ) : (
              renderPreviewContent(
                fileDetail?.file_type ?? null,
                fileDetail?.content ?? null,
              )
            )}
          </div>

          {/* 右侧：用户明细（固定，仅管理员） */}
          {isManager && (
            <div
              style={{
                flex: "0 0 360px",
                maxWidth: 360,
                backgroundColor: "#fff",
                borderRadius: 8,
                padding: 16,
                overflow: "hidden",
              }}
            >
              {/* 标题 + 统计数据 */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: 12,
                }}
              >
                <Title level={5} style={{ margin: 0, fontSize: 13, fontWeight: 500 }}>
                  使用用户明细
                </Title>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <Tooltip title="累计调用次数（所有用户总调用）">
                    <Tag
                      bordered={false}
                      style={{
                        ...STAT_TAG_STYLE,
                        backgroundColor: "#eef4ff",
                        color: "#365d97",
                      }}
                    >
                      <PhoneCall size={12} />
                      {formatMetricValue(skill.call_count)}
                    </Tag>
                  </Tooltip>
                  <Tooltip title="使用用户数（至少调用过一次的用户）">
                    <Tag
                      bordered={false}
                      style={{
                        ...STAT_TAG_STYLE,
                        backgroundColor: "#edf8f2",
                        color: "#2f7a55",
                      }}
                    >
                      <Users size={12} />
                      {formatMetricValue(skill.user_count)}
                    </Tag>
                  </Tooltip>
                </div>
              </div>

              {/* 用户表格 */}
              <div className={styles.usageTable}>
                <Table
                  dataSource={skill.user_stats}
                  columns={userStatsColumns}
                  rowKey="user_id"
                  pagination={{ pageSize: 5, hideOnSinglePage: true, size: "small" }}
                  size="small"
                  scroll={{ y: 380 }}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      <VersionHistoryModal
        open={versionHistoryOpen}
        itemId={skill.item_id}
        skillName={chineseName || skillName}
        currentVersion={skill.version}
        sourceId={sourceId || ""}
        isManager={isManager}
        onClose={() => setVersionHistoryOpen(false)}
        onVersionSwitched={onRefresh}
      />

      {/* 同步确认弹窗 */}
      <Modal
        open={syncModalOpen}
        title="同步设置"
        onCancel={handleEditCancel}
        onOk={handleSyncConfirm}
        okText="确认保存"
        cancelText="取消"
        okButtonProps={{ loading: isSaving }}
        width={520}
      >
        {/* 同步选项 - 主选项 */}
        <div style={{ marginBottom: 12 }}>
          <Checkbox
            checked={syncToUsers}
            onChange={(e) => {
              setSyncToUsers(e.target.checked);
              if (e.target.checked && selectedUserIds.length === 0) {
                // 开启同步时，默认全选
                setSelectedUserIds(uniqueDistributions.map((d) => d.target_user_id));
              }
            }}
          >
            同步更新已分发用户的技能名称（共 {uniqueDistributions.length} 位用户）
          </Checkbox>
        </div>

        {/* 提示 */}
        {syncToUsers && (
          <div style={{ color: "#666", fontSize: 12, marginBottom: 12 }}>
            同步更新后，用户下次会话将看到新名称
          </div>
        )}

        {/* 用户列表 - 仅在同步开启时显示 */}
        {syncToUsers && uniqueDistributions.length > 0 && (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <div style={{ fontWeight: 500 }}>已分发用户</div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Checkbox
                  checked={selectedUserIds.length === uniqueDistributions.length}
                  indeterminate={selectedUserIds.length > 0 && selectedUserIds.length < uniqueDistributions.length}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedUserIds(uniqueDistributions.map((d) => d.target_user_id));
                    } else {
                      setSelectedUserIds([]);
                    }
                  }}
                >
                  全选
                </Checkbox>
                <a onClick={() => setSelectedUserIds([])} style={{ fontSize: 12 }}>
                  清空
                </a>
              </div>
            </div>

            {/* 按机构分组展示 */}
            <Collapse
              size="small"
              style={{ maxHeight: 280, overflow: "auto" }}
              items={groupedDistributions.map((group) => ({
                key: group.bbkId,
                label: (
                  <span style={{ fontSize: 13 }}>
                    <UserOutlined style={{ marginRight: 6, color: "#1677ff" }} />
                    {group.bbkName}
                    <span style={{ color: "#999", marginLeft: 8 }}>
                      {group.records.length} 人
                    </span>
                  </span>
                ),
                children: (
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
                      gap: 4,
                    }}
                  >
                    {group.records.map((dist) => {
                      const displayName = dist.target_user_name
                        ? `${dist.target_user_name} (${dist.target_user_id})`
                        : dist.target_user_id;
                      const selected = selectedUserIds.includes(dist.target_user_id);
                      return (
                        <div
                          key={dist.target_user_id}
                          onClick={() => {
                            if (selected) {
                              setSelectedUserIds((prev) => prev.filter((id) => id !== dist.target_user_id));
                            } else {
                              setSelectedUserIds((prev) => [...prev, dist.target_user_id]);
                            }
                          }}
                          style={{
                            fontSize: 12,
                            color: "#333",
                            padding: "4px 8px",
                            borderRadius: 4,
                            cursor: "pointer",
                            backgroundColor: selected ? "#e6f4ff" : "transparent",
                            border: selected ? "1px solid #1890ff" : "1px solid transparent",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                          title={displayName}
                        >
                          {displayName}
                        </div>
                      );
                    })}
                  </div>
                ),
              }))}
            />

            {/* 选择汇总 */}
            <div style={{ color: "#666", fontSize: 12, marginTop: 8 }}>
              已选择 {selectedUserIds.length} 位用户
            </div>
          </>
        )}
      </Modal>
    </>
  );
}
