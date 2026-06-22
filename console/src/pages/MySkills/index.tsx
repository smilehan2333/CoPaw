import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Typography, Card, Spin, Button, Space, Input, message, Tag, Empty, Checkbox, Modal, Popconfirm, Tooltip } from "antd";
import { PlusOutlined, UploadOutlined, ShopOutlined, RightOutlined, DownOutlined, FolderOutlined, FileOutlined, StarOutlined, SearchOutlined } from "@ant-design/icons";
import { CheckCircle } from "lucide-react";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
dayjs.extend(relativeTime);
import { useMySkills } from "./useMySkills";
import { useIframeStore } from "../../stores/iframeStore";
import { getUserId } from "../../utils/identity";
import { DEFAULT_SOURCE_ID } from "../../constants/identity";
import { MySkill, mySkillsApi, FileTreeNode } from "../../api/modules/mySkills";
import { marketApi } from "../../api/modules/market";
import { PublishModal } from "../Market/PublishModal";
import { useConflictRenameModal } from "../Agent/Skills/components";
import { SkillDetailPanel, splitMarkdownFrontmatter, mergeMarkdownFrontmatter } from "./SkillDetailPanel";
import styles from "./index.module.less";

const { Title, Text } = Typography;

/**
 * 文件树排序：SKILL.md 置顶、templates 目录优先、目录优先于文件、其余字母排序
 */
function sortFileTreeNodes(nodes: FileTreeNode[], isRoot: boolean): FileTreeNode[] {
  const sorted = [...nodes].sort((a, b) => {
    if (isRoot) {
      // SKILL.md 置顶
      if (a.type === "file" && a.name.toUpperCase() === "SKILL.MD") return -1;
      if (b.type === "file" && b.name.toUpperCase() === "SKILL.MD") return 1;
      // templates 目录次优先
      if (a.type === "directory" && a.name.toLowerCase() === "templates") return -1;
      if (b.type === "directory" && b.name.toLowerCase() === "templates") return 1;
    }
    // 目录优先于文件
    if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
    // 字母排序
    return a.name.localeCompare(b.name);
  });

  // 递归排序子节点
  for (const node of sorted) {
    if (node.type === "directory" && node.children && node.children.length > 0) {
      node.children = sortFileTreeNodes(node.children, false);
    }
  }

  return sorted;
}

export default function MySkillsPage() {
  const navigate = useNavigate();
  const sourceId = useIframeStore((state) => state.source) || DEFAULT_SOURCE_ID;
  const manager = useIframeStore((state) => state.manager) || false;
  const userId = getUserId();
  const isManager = manager || userId === "default";
  const { createdSkills, receivedSkills, loading, refresh, refreshSkill } = useMySkills();
  const [searchText, setSearchText] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<MySkill | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(["created", "received"]));
  const [expandedSkills, setExpandedSkills] = useState<Set<string>>(new Set());
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileType, setFileType] = useState<string | null>(null);
  const [skillFiles, setSkillFiles] = useState<Record<string, FileTreeNode[]>>({});
  const [isEditing, setIsEditing] = useState(false);
  const [draftContent, setDraftContent] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Batch operation state
  const [batchMode, setBatchMode] = useState<boolean>(false);
  const [selectedForBatch, setSelectedForBatch] = useState<Set<string>>(new Set());

  // Sync to market state
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [publishInitialData, setPublishInitialData] = useState<{
    skillName: string;
    description: string;
    skillJson: Record<string, unknown>;
    skillMd: string;
    skillDirName?: string; // 技能目录名，用于同步整个目录
    version?: string; // 用户工作区版本号，用于版本快照的 source_user_version
  } | null>(null);

  // Conflict rename modal for upload
  // 冲突处理：强制使用覆盖模式（不允许重命名为新名称）
  const { showConflictRenameModal, conflictRenameModal } = useConflictRenameModal({ forceOverwrite: true });

  // Debounce search
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const handleSearchChange = (value: string) => {
    setSearchText(value);
    clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => setDebouncedQuery(value), 200);
  };

  // 同步 selectedSkill 与技能列表的状态（启用/禁用状态实时更新）
  useEffect(() => {
    if (selectedSkill) {
      const allSkills = [...createdSkills, ...receivedSkills];
      const updated = allSkills.find(s => s.skill_name === selectedSkill.skill_name);
      if (updated && updated.enabled !== selectedSkill.enabled) {
        setSelectedSkill(updated);
      }
    }
  }, [createdSkills, receivedSkills, selectedSkill]);

  useEffect(() => {
    refresh();
    return () => clearTimeout(debounceTimer.current);
  }, [refresh]);

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    let renameMap: Record<string, string> | undefined;
    let overwrite = false;
    while (true) {
      try {
        message.loading({ content: `正在上传 ${file.name}...`, key: "upload" });
        const result = await marketApi.uploadSkillToWorkspace(
          sourceId,
          file,
          { enable: true, overwrite, rename_map: renameMap }
        );

        // 检查冲突
        const conflicts = Array.isArray(result.conflicts) ? result.conflicts : [];
        if (conflicts.length > 0) {
          message.destroy("upload");
          const resolveResult = await showConflictRenameModal(
            conflicts.map((c: { skill_name?: string; original_name?: string; suggested_name?: string }) => ({
              key: c.original_name || c.skill_name || "",
              label: c.original_name || c.skill_name || "",
              suggested_name: c.suggested_name || "",
            }))
          );
          if (!resolveResult) {
            // 用户取消
            break;
          }
          if (resolveResult.mode === "overwrite") {
            // 用户选择覆盖
            overwrite = true;
            renameMap = undefined;
          } else {
            // 用户选择重命名
            renameMap = { ...renameMap, ...resolveResult.renameMap };
            overwrite = false;
          }
          continue;  // 重新上传
        }

        // 成功或无新技能
        if (result.count > 0) {
          message.success({ content: `上传成功，导入 ${result.count} 个技能`, key: "upload" });
        } else {
          message.info({ content: "未导入新技能，可能已存在", key: "upload" });
        }
        await refresh();

        // 刷新上传技能的文件树缓存并自动展开
        const importedNames = result.imported || [];
        if (importedNames.length > 0) {
          // 清除已上传技能的文件树缓存
          setSkillFiles((prev) => {
            const next = { ...prev };
            for (const name of importedNames) {
              delete next[name];
            }
            return next;
          });

          // 自动展开第一个导入的技能并加载其文件树
          const firstImportedName = importedNames[0];
          try {
            const files = await mySkillsApi.listSkillFiles(firstImportedName);
            const sortedFiles = sortFileTreeNodes(files, true);
            setSkillFiles((prev) => ({ ...prev, [firstImportedName]: sortedFiles }));

            // 刷新后重新获取最新的技能列表
            const latestCreated = await mySkillsApi.getCreatedSkills();
            const latestReceived = await mySkillsApi.getReceivedSkills();
            const allSkills = [...latestCreated, ...latestReceived];
            const newSkill = allSkills.find(s => s.skill_name === firstImportedName);
            if (newSkill) {
              setSelectedSkill(newSkill);
              setExpandedSkills(new Set([firstImportedName]));
            }

            // 自动选择 SKILL.md
            const skillMdFile = sortedFiles.find((f) => f.name === "SKILL.md" && f.type === "file");
            if (skillMdFile) {
              const res = await mySkillsApi.readSkillFile(firstImportedName, "SKILL.md");
              setSelectedFile("SKILL.md");
              setFileContent(res.content);
              setFileType(res.file_type);
            }
          } catch (err) {
            console.error("Failed to load skill files after upload:", err);
          }
        }
        break;
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : "上传失败";
        message.error({ content: errorMsg, key: "upload" });
        break;
      }
    }
  };

  // Filter skills
  const filterSkills = (skills: MySkill[]) => {
    const q = debouncedQuery.trim().toLowerCase();
    if (!q) return skills;
    return skills.filter((s) =>
      s.skill_name.toLowerCase().includes(q) ||
      (s.description?.toLowerCase().includes(q) ?? false)
    );
  };

  const filteredCreated = filterSkills(createdSkills);
  const filteredReceived = filterSkills(receivedSkills);

  const toggleGroup = (key: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleSkillExpand = useCallback(async (skill: MySkill) => {
    const skillName = skill.skill_name;
    setExpandedSkills((prev) => {
      const next = new Set(prev);
      if (next.has(skillName)) {
        next.delete(skillName);
      } else {
        next.clear();
        next.add(skillName);
      }
      return next;
    });
    setSelectedSkill(skill);
    setSelectedFile(null);
    setFileContent(null);
    setIsEditing(false);

    // Load skill files if not cached
    try {
      let files = skillFiles[skillName] || await mySkillsApi.listSkillFiles(skillName);
      // 对文件树排序：SKILL.md 置顶、templates 目录优先
      files = sortFileTreeNodes(files, true);
      setSkillFiles((prev) => ({ ...prev, [skillName]: files }));

      // 自动选择 SKILL.md（如果存在）
      const skillMdFile = files.find((f) => f.name === "SKILL.md" && f.type === "file");
      if (skillMdFile) {
        try {
          const res = await mySkillsApi.readSkillFile(skillName, "SKILL.md");
          setSelectedFile("SKILL.md");
          setFileContent(res.content);
          setFileType(res.file_type);
        } catch (err) {
          console.error("Failed to load SKILL.md:", err);
          setFileContent("");
        }
      }
    } catch (err) {
      console.error("Failed to load skill files:", err);
    }
  }, [skillFiles]);

  const toggleDir = useCallback((path: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const selectFile = useCallback(async (skill: MySkill, filePath: string) => {
    setSelectedFile(filePath);
    setFileContent(null);
    setIsEditing(false);
    try {
      const res = await mySkillsApi.readSkillFile(skill.skill_name, filePath);
      setFileContent(res.content);
      setFileType(res.file_type);
    } catch (err) {
      message.error("加载文件失败");
      setFileContent("");
    }
  }, []);

  const [togglingSkill, setTogglingSkill] = useState<string | null>(null);

  const handleToggleEnabled = useCallback(async (skill: MySkill) => {
    if (togglingSkill) return;
    const action = skill.enabled ? "disable" : "enable";
    setTogglingSkill(skill.skill_name);
    try {
      if (skill.enabled) {
        await mySkillsApi.disableSkill(skill.skill_name);
      } else {
        await mySkillsApi.enableSkill(skill.skill_name);
      }
      message.success(`${action === "enable" ? "启用" : "禁用"}成功`);
      refresh();
    } catch (err: unknown) {
      const errObj = err as Error & { status?: number; data?: { detail?: { reason?: string; detail?: string } } };
      const detail = errObj?.data?.detail;
      if (detail?.reason === "security_scan_failed") {
        message.error(`启用失败：安全扫描未通过，${detail.detail || "请检查技能内容"}`);
      } else {
        message.error(`${action === "enable" ? "启用" : "禁用"}失败`);
      }
    } finally {
      setTogglingSkill(null);
    }
  }, [refresh, togglingSkill]);

  const handleDelete = useCallback(async (skill: MySkill) => {
    try {
      await mySkillsApi.deleteSkill(skill.skill_name);
      message.success("删除成功");
      refresh();
      setSelectedSkill(null);
      setSelectedFile(null);
      setFileContent(null);
      setSkillFiles((prev) => {
        const next = { ...prev };
        delete next[skill.skill_name];
        return next;
      });
    } catch (err) {
      message.error("删除失败");
    }
  }, [refresh]);

  const handleBatchDelete = useCallback(async () => {
    if (selectedForBatch.size === 0) return;
    const names = [...selectedForBatch];
    try {
      const result = await mySkillsApi.batchDeleteSkills(names);
      message.success(`成功删除 ${result.success_count} 个技能`);
      setSelectedForBatch(new Set());
      setBatchMode(false);
      refresh();
    } catch (err) {
      message.error("批量删除失败");
    }
  }, [selectedForBatch, refresh]);

  const handleBatchEnable = useCallback(async () => {
    if (selectedForBatch.size === 0) return;
    const names = [...selectedForBatch];
    try {
      const result = await mySkillsApi.batchEnableSkills(names);
      message.success(`成功启用 ${result.success_count} 个技能`);
      setSelectedForBatch(new Set());
      setBatchMode(false);
      refresh();
    } catch (err) {
      message.error("批量启用失败");
    }
  }, [selectedForBatch, refresh]);

  const handleBatchDisable = useCallback(async () => {
    if (selectedForBatch.size === 0) return;
    const names = [...selectedForBatch];
    try {
      const result = await mySkillsApi.batchDisableSkills(names);
      message.success(`成功禁用 ${result.success_count} 个技能`);
      setSelectedForBatch(new Set());
      setBatchMode(false);
      refresh();
    } catch (err) {
      message.error("批量禁用失败");
    }
  }, [selectedForBatch, refresh]);

  const handleSaveContent = useCallback(async () => {
    if (!selectedSkill || !selectedFile || !isEditing) return;

    // 检查内容是否发生了变化
    const frontmatter = splitMarkdownFrontmatter(selectedFile, fileContent);
    if (draftContent === frontmatter.editableContent) {
      message.info("内容未变化，无需保存");
      setIsEditing(false);
      return;
    }

    setIsSaving(true);
    try {
      // 对于 Markdown 文件，合并 frontmatter
      const contentToSave = frontmatter.hasFrontmatter
        ? mergeMarkdownFrontmatter(frontmatter.protectedPrefix, draftContent)
        : draftContent;

      await mySkillsApi.saveSkillFile(selectedSkill.skill_name, selectedFile, contentToSave);
      setIsEditing(false);
      message.success("保存成功，可新开会话试一试效果。");

      // 重新读取文件内容，确保展示与后端保存结果一致
      try {
        const res = await mySkillsApi.readSkillFile(selectedSkill.skill_name, selectedFile);
        setFileContent(res.content);
      } catch {
        setFileContent(contentToSave);
      }

      // 刷新单个技能数据（更新 version、updated_at 显示）
      const updatedSkill = await refreshSkill(selectedSkill.skill_name);
      if (updatedSkill) {
        setSelectedSkill(updatedSkill);
      }
    } catch (err) {
      message.error("保存失败");
    } finally {
      setIsSaving(false);
    }
  }, [selectedSkill, selectedFile, isEditing, draftContent, fileContent, refreshSkill]);

  // 编辑开始：初始化 draftContent
  const handleEditStart = useCallback(() => {
    setIsEditing(true);
    const frontmatter = splitMarkdownFrontmatter(selectedFile, fileContent);
    setDraftContent(frontmatter.editableContent);
  }, [selectedFile, fileContent]);

  // 编辑取消：重置 draftContent
  const handleEditCancel = useCallback(() => {
    setIsEditing(false);
    const frontmatter = splitMarkdownFrontmatter(selectedFile, fileContent);
    setDraftContent(frontmatter.editableContent);
  }, [selectedFile, fileContent]);

  // Navigate to marketplace
  const goToMarketplace = () => {
    navigate("/market");
  };

  // Sync skill to market
  const handleSyncToMarket = useCallback(async (skill: MySkill) => {
    if (!skill || skill.is_received) return;

    try {
      message.loading({ content: "读取技能文件...", key: "sync" });

      // Read skill.json and SKILL.md
      const files = await mySkillsApi.listSkillFiles(skill.skill_name);

      let skillJson: Record<string, unknown> = {};
      let skillMd = "";

      // Find skill.json
      const skillJsonFile = files.find((f) => f.name === "skill.json" && f.type === "file");
      if (skillJsonFile) {
        const res = await mySkillsApi.readSkillFile(skill.skill_name, "skill.json");
        try {
          skillJson = JSON.parse(res.content);
        } catch {
          // ignore parse error
        }
      }

      // Find SKILL.md
      const skillMdFile = files.find((f) => f.name === "SKILL.md" && f.type === "file");
      if (skillMdFile) {
        const res = await mySkillsApi.readSkillFile(skill.skill_name, "SKILL.md");
        skillMd = res.content;
      }

      message.destroy("sync");

      setPublishInitialData({
        skillName: skill.display_name || skill.skill_name,
        description: skill.description || "",
        skillJson,
        skillMd,
        skillDirName: skill.skill_name, // 传递目录名，用于同步整个目录
        version: skill.version, // 传递用户工作区版本号
      });
      setPublishModalOpen(true);
    } catch (err) {
      message.error({ content: "读取技能文件失败", key: "sync" });
    }
  }, []);

  // File tree component
  const FileTree = ({ nodes, level, skill }: { nodes: FileTreeNode[]; level: number; skill: MySkill }) => (
    <div>
      {nodes.map((node) => {
        const paddingLeft = 24 + level * 16;
        const isExpanded = expandedDirs.has(node.path);
        const isSelected = selectedFile === node.path;

        if (node.type === "directory") {
          return (
            <div key={node.path}>
              <div
                onClick={() => toggleDir(node.path)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  padding: "4px 8px",
                  paddingLeft,
                  cursor: "pointer",
                  borderRadius: 4,
                  marginBottom: 2,
                  backgroundColor: isExpanded ? "#f5f5f5" : "transparent",
                }}
              >
                {isExpanded ? (
                  <DownOutlined style={{ fontSize: 10, marginRight: 6, color: "#8c8c8c" }} />
                ) : (
                  <RightOutlined style={{ fontSize: 10, marginRight: 6, color: "#8c8c8c" }} />
                )}
                <FolderOutlined style={{ fontSize: 14, marginRight: 6, color: "#faad14" }} />
                <Text style={{ fontSize: 12 }}>{node.name}</Text>
              </div>
              {isExpanded && node.children && (
                <FileTree nodes={node.children} level={level + 1} skill={skill} />
              )}
            </div>
          );
        }

        return (
          <div
            key={node.path}
            onClick={() => selectFile(skill, node.path)}
            style={{
              display: "flex",
              alignItems: "center",
              padding: "4px 8px",
              paddingLeft: paddingLeft + 16,
              cursor: "pointer",
              borderRadius: 4,
              marginBottom: 2,
              backgroundColor: isSelected ? "#e6f4ff" : "transparent",
              border: isSelected ? "1px solid #1890ff" : "1px solid transparent",
            }}
          >
            <FileOutlined style={{ fontSize: 14, marginRight: 6, color: "#8c8c8c" }} />
            <Text style={{ fontSize: 12, color: isSelected ? "#1890ff" : "#262626" }}>
              {node.name}
            </Text>
          </div>
        );
      })}
    </div>
  );

  // Skill list item component
  const SkillListItem = ({ skill, isSelected }: { skill: MySkill; isSelected: boolean }) => {
    const isExpanded = expandedSkills.has(skill.skill_name);
    const files = skillFiles[skill.skill_name] || [];
    const isDisabled = !skill.enabled;

    return (
      <div
        style={{
          borderRadius: 8,
          border: "1px solid #f0f0f0",
          marginBottom: 4,
          overflow: "hidden",
          backgroundColor: isSelected ? "#e6f4ff" : "#fff",
        }}
      >
        <div
          onClick={() => !batchMode && toggleSkillExpand(skill)}
          style={{
            padding: "8px 10px",
            cursor: batchMode ? "default" : "pointer",
            display: "flex",
            alignItems: "center",
            gap: 8,
            minWidth: 0,
            borderBottom: isExpanded ? "1px solid #f0f0f0" : "none",
          }}
        >
          {batchMode && (
            <Checkbox
              style={{ marginRight: 8 }}
              checked={selectedForBatch.has(skill.skill_name)}
              onChange={(e) => {
                setSelectedForBatch((prev) => {
                  const next = new Set(prev);
                  if (e.target.checked) next.add(skill.skill_name);
                  else next.delete(skill.skill_name);
                  return next;
                });
              }}
              onClick={(e) => e.stopPropagation()}
            />
          )}
          {!batchMode && (isExpanded ? (
            <DownOutlined style={{ fontSize: 10, color: "#8c8c8c", flexShrink: 0 }} />
          ) : (
            <RightOutlined style={{ fontSize: 10, color: "#8c8c8c", flexShrink: 0 }} />
          ))}
          <Text
            strong={isSelected}
            style={{
              flex: 1,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              color: isDisabled ? "#8c8c8c" : isSelected ? "#1890ff" : "#262626",
              textDecoration: isDisabled ? "line-through" : "none",
            }}
          >
            {skill.display_name || skill.skill_name}
          </Text>
          {skill.is_received && (
            <Tag color="orange" style={{ fontSize: 10, margin: 0, borderRadius: 4 }}>接收的</Tag>
          )}
          {skill.has_update && (
            <Tag color="red" style={{ fontSize: 10, margin: 0, borderRadius: 4 }}>有更新</Tag>
          )}
        </div>
        {isExpanded && (
          <div style={{ padding: "4px 0" }}>
            {files.length === 0 ? (
              <Text type="secondary" style={{ padding: "0 16px", fontSize: 12 }}>没有文件</Text>
            ) : (
              <FileTree nodes={files} level={0} skill={skill} />
            )}
          </div>
        )}
      </div>
    );
  };

  // Skill group section
  const SkillGroup = ({
    title,
    skills,
    groupKey,
    style,
  }: {
    title: string;
    skills: MySkill[];
    groupKey: string;
    style?: React.CSSProperties;
  }) => {
    const isExpanded = expandedGroups.has(groupKey);

    const headerStyle = (() => {
      if (title.includes("创建")) {
        return {
          borderColor: "#d7e2f5",
          backgroundColor: "#eef4ff",
          color: "#365d97",
          dotColor: "#365d97",
        };
      }
      if (title.includes("接收")) {
        return {
          borderColor: "#c4e8d1",
          backgroundColor: "#edf7f0",
          color: "#2e7d4f",
          dotColor: "#2e7d4f",
        };
      }
      return {
        borderColor: "#e8e6dc",
        backgroundColor: "#f5f4ed",
        color: "#5e5d59",
        dotColor: "#87867f",
      };
    })();

    return (
      <div
        style={{
          borderRadius: 8,
          border: "1px solid #f0f0f0",
          backgroundColor: "#fff",
          padding: 6,
          ...style,
        }}
      >
        <div
          onClick={() => toggleGroup(groupKey)}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "6px 10px",
            borderRadius: 6,
            cursor: "pointer",
            border: `1px solid ${headerStyle.borderColor}`,
            backgroundColor: headerStyle.backgroundColor,
            transition: "background-color 0.15s ease",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            {isExpanded ? (
              <DownOutlined style={{ fontSize: 12, color: "#8c8c8c" }} />
            ) : (
              <RightOutlined style={{ fontSize: 12, color: "#8c8c8c" }} />
            )}
            <div
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                backgroundColor: headerStyle.dotColor,
                flexShrink: 0,
              }}
            />
            <Text style={{ fontSize: 13, fontWeight: 500, color: headerStyle.color }}>
              {title}
            </Text>
          </div>
          <Tag
            style={{
              height: 20,
              minWidth: 24,
              justifyContent: "center",
              padding: "0 6px",
              fontSize: 11,
              fontWeight: 500,
              margin: 0,
              borderRadius: 4,
              backgroundColor: "#fff",
              border: `1px solid ${headerStyle.borderColor}`,
              color: headerStyle.color,
            }}
          >
            {skills.length}
          </Tag>
        </div>
        {isExpanded && (
          <div style={{ padding: "8px 2px 2px 2px" }}>
            {skills.length === 0 ? (
              <Text style={{ fontSize: 12, color: "#8c8c8c", padding: "8px 10px", display: "block" }}>
                没有匹配的技能
              </Text>
            ) : (
              skills.map((skill) => (
                <SkillListItem
                  key={skill.skill_name}
                  skill={skill}
                  isSelected={selectedSkill?.skill_name === skill.skill_name}
                />
              ))
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ display: "flex", height: "100%", backgroundColor: "#fff" }}>
      {/* Left sidebar */}
      <div
        style={{
          width: 300,
          flexShrink: 0,
          borderRight: "1px solid #f0f0f0",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Search and actions */}
        <div style={{ padding: 16, borderBottom: "1px solid #f0f0f0" }}>
          <Input
            placeholder="搜索技能"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => handleSearchChange(e.target.value)}
            allowClear
            style={{ marginBottom: 8 }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <Button
              icon={<UploadOutlined />}
              onClick={handleUploadClick}
              style={{ flex: 1 }}
            >
              上传技能
            </Button>
            {isManager && (
              <Button
                icon={<ShopOutlined />}
                onClick={goToMarketplace}
                style={{ flex: 1 }}
              >
                去应用市场
                <RightOutlined style={{ fontSize: 10, marginLeft: 4 }} />
              </Button>
            )}
          </div>
        </div>

        {/* Batch operation bar */}
        <div style={{ padding: "8px 16px", borderBottom: "1px solid #f0f0f0", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Button
            size="small"
            onClick={() => {
              setBatchMode(!batchMode);
              setSelectedForBatch(new Set());
            }}
          >
            {batchMode ? "取消批量" : "批量管理"}
          </Button>
          {batchMode && (
            <>
              <Button size="small" type="primary" onClick={handleBatchEnable} disabled={selectedForBatch.size === 0}>
                批量启用 ({selectedForBatch.size})
              </Button>
              <Button size="small" onClick={handleBatchDisable} disabled={selectedForBatch.size === 0}>
                批量禁用
              </Button>
              <Popconfirm
                title="批量删除"
                description={`确定删除选中的 ${selectedForBatch.size} 个技能？删除后不可恢复。`}
                onConfirm={handleBatchDelete}
                okText="确定"
                cancelText="取消"
              >
                <Button size="small" danger disabled={selectedForBatch.size === 0}>
                  批量删除
                </Button>
              </Popconfirm>
              <Text type="secondary" style={{ marginLeft: 8 }}>
                已选择 {selectedForBatch.size} 个
              </Text>
            </>
          )}
        </div>

        {/* Skill groups */}
        <div style={{ flex: 1, overflow: "auto", padding: 8 }}>
          {loading ? (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 100 }}>
              <Spin />
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <SkillGroup
                title="我创建的"
                skills={filteredCreated}
                groupKey="created"
              />
              <SkillGroup
                title="我接收的"
                skills={filteredReceived}
                groupKey="received"
              />
            </div>
          )}
        </div>
      </div>

      {/* Right detail panel */}
      <div style={{ flex: 1, backgroundColor: "#fff", overflow: "hidden" }}>
        <SkillDetailPanel
          skill={selectedSkill}
          selectedFile={selectedFile}
          fileContent={fileContent}
          fileType={fileType}
          isEditing={isEditing}
          draftContent={draftContent}
          isSaving={isSaving}
          togglingSkill={togglingSkill}
          isManager={isManager}
          onEditStart={handleEditStart}
          onEditCancel={handleEditCancel}
          onSave={handleSaveContent}
          onDraftChange={setDraftContent}
          onToggleEnabled={handleToggleEnabled}
          onDelete={handleDelete}
          onSyncToMarket={handleSyncToMarket}
        />
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".zip"
        style={{ position: "absolute", left: -9999, opacity: 0 }}
        onChange={handleFileSelect}
      />

      {/* Sync to market modal */}
      <PublishModal
        open={publishModalOpen}
        sourceId={sourceId}
        userId={userId}
        onClose={() => {
          setPublishModalOpen(false);
          setPublishInitialData(null);
        }}
        onSuccess={() => {
          refresh();
        }}
        initialData={publishInitialData}
      />

      {/* Conflict rename modal */}
      {conflictRenameModal}
    </div>
  );
}
