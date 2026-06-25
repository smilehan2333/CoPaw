import { memo, useState, useRef, useLayoutEffect } from "react";
import { Typography, Button, Spin, Tag, Popconfirm, Tooltip, Input } from "antd";
import { StarOutlined, RocketOutlined, UserOutlined, ClockCircleOutlined, CalendarOutlined, TagOutlined, DownOutlined, UpOutlined } from "@ant-design/icons";
import { Power, Trash2, Pencil, PencilLine } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
dayjs.extend(relativeTime);
import { MySkill } from "../../api/modules/mySkills";
import styles from "./index.module.less";

const { Title, Text } = Typography;

/**
 * 将 Markdown 文件内容分割为 frontmatter 和正文。
 */
function splitMarkdownFrontmatter(
  filePath: string | null,
  content: string | null
): { protectedPrefix: string; editableContent: string; hasFrontmatter: boolean } {
  const isMarkdown = !!filePath && /\.md$/i.test(filePath);
  if (!isMarkdown || typeof content !== "string") {
    return { protectedPrefix: "", editableContent: content ?? "", hasFrontmatter: false };
  }

  const match = content.match(/^---\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/);
  if (!match) {
    return { protectedPrefix: "", editableContent: content, hasFrontmatter: false };
  }

  return {
    protectedPrefix: match[0],
    editableContent: content.slice(match[0].length),
    hasFrontmatter: true,
  };
}

/**
 * 将 protectedPrefix (frontmatter) 和 editableContent 合并为完整文件内容。
 */
function mergeMarkdownFrontmatter(protectedPrefix: string, editableContent: string): string {
  if (!protectedPrefix) return editableContent;
  if (!editableContent || protectedPrefix.endsWith("\n") || protectedPrefix.endsWith("\r\n")) {
    return `${protectedPrefix}${editableContent}`;
  }
  return `${protectedPrefix}\n${editableContent}`;
}

interface SkillDetailPanelProps {
  skill: MySkill | null;
  selectedFile: string | null;
  fileContent: string | null;
  fileType: string | null;
  isEditing: boolean;
  draftContent: string;
  draftCnName: string;  // 编辑中的中文名
  isSaving: boolean;
  togglingSkill: string | null;
  isManager: boolean;
  onEditStart: () => void;
  onEditCancel: () => void;
  onSave: () => void;
  onDraftChange: (content: string) => void;
  onCnNameChange: (cnName: string) => void;  // 中文名修改
  onToggleEnabled: (skill: MySkill) => void;
  onDelete: (skill: MySkill) => void;
  onSyncToMarket: (skill: MySkill) => void;
}

const SkillDetailPanel = memo(function SkillDetailPanel({
  skill,
  selectedFile,
  fileContent,
  fileType,
  isEditing,
  draftContent,
  draftCnName,
  isSaving,
  togglingSkill,
  isManager,
  onEditStart,
  onEditCancel,
  onSave,
  onDraftChange,
  onCnNameChange,
  onToggleEnabled,
  onDelete,
  onSyncToMarket,
}: SkillDetailPanelProps) {
  // 描述区展开状态
  const [descExpanded, setDescExpanded] = useState(false);
  // 描述区是否需要折叠（内容实际溢出）
  const [needsCollapse, setNeedsCollapse] = useState(false);
  // 描述区内容 ref
  const descContentRef = useRef<HTMLDivElement>(null);
  // 描述区最大高度（收起态）
  const DESC_MAX_HEIGHT = 80;

  // 检测内容是否实际溢出（渲染后测量）
  useLayoutEffect(() => {
    if (descContentRef.current && skill?.description) {
      // scrollHeight 是内容的完整高度，不受 maxHeight 影响
      const contentHeight = descContentRef.current.scrollHeight;
      // 内容高度超过限制时需要折叠
      setNeedsCollapse(contentHeight > DESC_MAX_HEIGHT);
    } else {
      setNeedsCollapse(false);
    }
  }, [skill?.description]);

  if (!skill) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", padding: 32, textAlign: "center" }}>
        <StarOutlined style={{ fontSize: 48, color: "#faad14", marginBottom: 16 }} />
        <Title level={5} style={{ margin: "0 0 8px 0", color: "#262626" }}>
          技能详情
        </Title>
        <Text type="secondary" style={{ fontSize: 14 }}>
          选择左侧技能查看详情
        </Text>
      </div>
    );
  }

  const isDisabled = !skill.enabled;
  const canEdit = !skill.is_received;
  const isLoading = selectedFile && fileContent === null;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div
        style={{
          padding: 16,
          borderBottom: "1px solid #f0f0f0",
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* 第一行：中文名 + 技能名 + 状态标签 */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            {/* 中文名：编辑模式为输入框，非编辑模式为主标题 */}
            {isEditing ? (
              <Input
                placeholder="输入中文名称"
                value={draftCnName}
                onChange={(e) => onCnNameChange(e.target.value)}
                style={{ width: 240, fontSize: 14 }}
                maxLength={50}
                showCount
              />
            ) : (
              <Tooltip title={skill.cn_name || skill.display_name || skill.skill_name}>
                <Text
                  strong
                  style={{
                    fontSize: 16,
                    color: "#262626",
                    maxWidth: 400,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {skill.cn_name || skill.display_name || skill.skill_name}
                </Text>
              </Tooltip>
            )}
            {/* 技能名：副标题，灰色小字（非编辑模式且与中文名不同时显示） */}
            {!isEditing && skill.skill_name && (skill.cn_name || skill.display_name) && skill.skill_name !== (skill.cn_name || skill.display_name) && (
              <Tooltip title={`技能名: ${skill.skill_name}`}>
                <Text
                  style={{
                    fontSize: 11,
                    color: "#8c8c8c",
                    maxWidth: 120,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {skill.skill_name}
                </Text>
              </Tooltip>
            )}
            {/* 状态标签：最多显示1个关键状态 */}
            {isDisabled ? (
              <Tag color="red" style={{ fontSize: 11, borderRadius: 4, margin: 0 }}>已禁用</Tag>
            ) : skill.is_received ? (
              <Tag color="orange" style={{ fontSize: 11, borderRadius: 4, margin: 0 }}>接收的</Tag>
            ) : null}
          </div>

          {/* 第二行：次要信息（图标化，一行） */}
          {!isEditing && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#8c8c8c", fontSize: 12 }}>
              {skill.creator_name && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <UserOutlined style={{ fontSize: 12 }} />
                  <span style={{ maxWidth: 80, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {skill.creator_name}
                  </span>
                </span>
              )}
              {skill.creator_name && skill.created_at && (
                <span style={{ color: "#d9d9d9" }}>·</span>
              )}
              {skill.created_at && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <CalendarOutlined style={{ fontSize: 12 }} />
                  <span>{dayjs(skill.created_at).format("YYYY-MM-DD")}</span>
                </span>
              )}
              {skill.created_at && skill.updated_at && (
                <span style={{ color: "#d9d9d9" }}>·</span>
              )}
              {skill.updated_at && (
                <Tooltip title={dayjs(skill.updated_at).format("YYYY-MM-DD HH:mm:ss")}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                    <ClockCircleOutlined style={{ fontSize: 12 }} />
                    <span>更新于 {dayjs(skill.updated_at).fromNow()}</span>
                  </span>
                </Tooltip>
              )}
              {(skill.creator_name || skill.created_at || skill.updated_at) && skill.version && (
                <span style={{ color: "#d9d9d9" }}>·</span>
              )}
              {skill.version && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <TagOutlined style={{ fontSize: 12 }} />
                  <span>v{skill.is_received ? skill.received_version || skill.version : skill.version}</span>
                </span>
              )}
              {skill.version && skill.category && (
                <span style={{ color: "#d9d9d9" }}>·</span>
              )}
              {skill.category && (
                <Tag
                  style={{
                    fontSize: 11,
                    borderRadius: 4,
                    margin: 0,
                    backgroundColor: "#fafafa",
                    border: "1px solid #e8e8e8",
                    color: "#8c8c8c",
                  }}
                >
                  {skill.category}
                </Tag>
              )}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          <Popconfirm
            title="删除技能"
            description={`确定删除技能「${skill.display_name || skill.skill_name}」？删除后不可恢复。`}
            onConfirm={() => onDelete(skill)}
            okText="确定"
            cancelText="取消"
          >
            <Button
              size="small"
              danger
              icon={<Trash2 style={{ width: 12, height: 12 }} />}
              style={{ height: 28, fontSize: 12, borderRadius: 8 }}
            >
              删除
            </Button>
          </Popconfirm>
          {canEdit && fileContent !== null && !isEditing && (
            <Button
              size="small"
              icon={<Pencil style={{ width: 12, height: 12 }} />}
              style={{ height: 28, fontSize: 12, borderRadius: 8 }}
              onClick={onEditStart}
            >
              编辑
            </Button>
          )}
          <Button
            size="small"
            type={skill.enabled ? "primary" : "default"}
            icon={<Power style={{ width: 12, height: 12 }} />}
            style={{ height: 28, fontSize: 12, borderRadius: 8 }}
            onClick={() => onToggleEnabled(skill)}
            loading={togglingSkill === skill.skill_name}
          >
            {skill.enabled ? "已启用" : "已禁用"}
          </Button>
          {isManager && canEdit && (
            <Button
              size="small"
              icon={<RocketOutlined style={{ fontSize: 12 }} />}
              style={{
                height: 28,
                fontSize: 12,
                borderRadius: 8,
                background: "linear-gradient(135deg, #c4956a 0%, #b85a3a 100%)",
                border: "none",
                color: "#fff",
              }}
              onClick={() => onSyncToMarket(skill)}
            >
              同步到市场
            </Button>
          )}
          {isEditing && (
            <>
              <Button
                size="small"
                style={{ height: 28, fontSize: 12, borderRadius: 8 }}
                onClick={onEditCancel}
                disabled={isSaving}
              >
                取消
              </Button>
              <Button
                size="small"
                type="primary"
                style={{ height: 28, fontSize: 12, borderRadius: 8 }}
                onClick={onSave}
                loading={isSaving}
              >
                保存
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Description - 可折叠 */}
      <div
        style={{
          borderBottom: "1px solid #f0f0f0",
        }}
      >
        {/* 外层容器：控制显示高度 */}
        <div
          style={{
            maxHeight: descExpanded ? undefined : DESC_MAX_HEIGHT,
            overflow: "hidden",
            transition: "max-height 0.2s ease-out",
          }}
        >
          {/* 内容区域：ref 测量真实高度，不受 maxHeight 影响 */}
          <div
            ref={descContentRef}
            style={{
              padding: "12px 16px",
            }}
          >
            <Text type="secondary" style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>
              {skill.description || "暂无描述"}
            </Text>
          </div>
        </div>
        {/* 展开/收起按钮：在 maxHeight 容器外，始终可见 */}
        {needsCollapse && (
          <div style={{ padding: "0 16px 8px 16px" }}>
            <Button
              type="link"
              size="small"
              icon={descExpanded ? <UpOutlined /> : <DownOutlined />}
              onClick={() => setDescExpanded(!descExpanded)}
              style={{
                padding: 0,
                height: 20,
                fontSize: 12,
              }}
            >
              {descExpanded ? "收起" : "展开全部"}
            </Button>
          </div>
        )}
      </div>

      {/* Content */}
      <div style={{ flex: "1 1 0", padding: 16, overflow: "auto", minHeight: 0 }}>
        {isLoading ? (
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 100 }}>
            <Spin />
          </div>
        ) : isEditing ? (
          <div className={styles.editModeContainer}>
            {/* 编辑模式标签 */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <div className={styles.editModeTag}>
                <PencilLine style={{ width: 12, height: 12 }} />
                编辑模式
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                可使用 Ctrl/Cmd + S 快速保存
              </Text>
            </div>
            {/* Frontmatter 保护提示 */}
            {selectedFile && /\.md$/i.test(selectedFile) && splitMarkdownFrontmatter(selectedFile, fileContent).hasFrontmatter && (
              <p className={styles.frontmatterNote}>
                Markdown 顶部元信息受保护，此处只编辑正文内容。
              </p>
            )}
            {/* 编辑区域 */}
            <textarea
              value={draftContent}
              onChange={(e) => onDraftChange(e.target.value)}
              onKeyDown={(e) => {
                // Ctrl/Cmd + S 快捷保存
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
                  e.preventDefault();
                  onSave();
                }
              }}
              className={styles.editModeTextarea}
              placeholder="输入内容..."
              spellCheck={false}
            />
          </div>
        ) : fileContent === null ? (
          <div className={styles.detailPanelEmpty}>
            <Text type="secondary">选择文件查看内容</Text>
          </div>
        ) : fileType === "markdown" ? (
          <div className={styles.previewContainerMarkdown}>
            {/* Frontmatter 提示 */}
            {splitMarkdownFrontmatter(selectedFile, fileContent).hasFrontmatter && (
              <p className={styles.frontmatterPreviewNote}>
                文件顶部包含受保护的元信息，此处只显示正文内容。
              </p>
            )}
            <div className={styles.streamingMarkdown}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {splitMarkdownFrontmatter(selectedFile, fileContent).editableContent.trim()}
              </ReactMarkdown>
            </div>
          </div>
        ) : fileType === "json" ? (
          <pre className={styles.previewContainerJson}>
            {(() => {
              try {
                return JSON.stringify(JSON.parse(fileContent), null, 2);
              } catch {
                return fileContent;
              }
            })()}
          </pre>
        ) : (
          <pre className={styles.previewContainer}>
            {fileContent}
          </pre>
        )}
      </div>
    </div>
  );
});

export { SkillDetailPanel, splitMarkdownFrontmatter, mergeMarkdownFrontmatter };