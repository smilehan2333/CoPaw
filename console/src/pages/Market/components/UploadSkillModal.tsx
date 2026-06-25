import { useState, useEffect } from "react";
import { Modal, Upload, Select, Input, message, Spin, Button, Tooltip, Alert, Popover } from "antd";
import { InboxOutlined, PlusOutlined, InfoCircleOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import type { UploadProps } from "antd";
import { marketApi, type Category } from "../../../api/modules/market";

interface UploadSkillModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  onCategoryAdded?: () => void;
  sourceId: string;
}

const { Dragger } = Upload;

export default function UploadSkillModal({
  open,
  onClose,
  onSuccess,
  onCategoryAdded,
  sourceId,
}: UploadSkillModalProps) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [cnName, setCnName] = useState("");
  const [skillId, setSkillId] = useState("");
  const [skillName, setSkillName] = useState("");
  const [skillIdReused, setSkillIdReused] = useState(false);
  const [parsingZip, setParsingZip] = useState(false);
  const [skillIdUsedCount, setSkillIdUsedCount] = useState(0);
  const [skillIdUsedBy, setSkillIdUsedBy] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loadingCategories, setLoadingCategories] = useState(false);
  const [skillExists, setSkillExists] = useState(false);  // 同名技能已存在（允许覆盖）
  const [addCategoryModalOpen, setAddCategoryModalOpen] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [addingCategory, setAddingCategory] = useState(false);

  const loadCategories = async () => {
    setLoadingCategories(true);
    try {
      const data = await marketApi.listCategories(sourceId);
      setCategories(data);
      if (data.length > 0) {
        setSelectedCategory(data[0].id);
      }
    } catch (err) {
      console.error("Failed to load categories:", err);
    } finally {
      setLoadingCategories(false);
    }
  };

  useEffect(() => {
    if (open) {
      loadCategories();
      setFile(null);
      setCnName("");
      setSkillId("");
      setSkillName("");
      setSkillIdReused(false);
      setSkillIdUsedCount(0);
      setSkillIdUsedBy([]);
      setSelectedCategory(null);
      setSkillExists(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 解析 zip 文件
  const parseZipFile = async (selectedFile: File) => {
    setParsingZip(true);
    try {
      const result = await marketApi.parseSkillZip(sourceId, selectedFile, true);
      if (result.error) {
        message.error(result.error);
        setParsingZip(false);
        return;
      }

      // 设置预解析结果
      setCnName(result.cn_name || result.skill_name || "");
      setSkillId(result.skill_id || "");
      setSkillName(result.skill_name || "");
      setSkillIdReused(result.skill_id_reused || false);
      setSkillIdUsedCount(result.skill_id_used_count || 0);
      setSkillIdUsedBy(result.skill_id_used_by || []);
      setSkillExists(result.exists || false);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "解析失败";
      message.error(errorMsg);
    } finally {
      setParsingZip(false);
    }
  };

  const handleAddCategory = async () => {
    const trimmed = newCategoryName.trim();
    if (!trimmed) {
      message.error("请输入分类名称");
      return;
    }
    setAddingCategory(true);
    try {
      const newCat = await marketApi.createCategory(sourceId, trimmed);
      message.success(`分类 "${newCat.name}" 创建成功`);
      setAddCategoryModalOpen(false);
      setNewCategoryName("");
      await loadCategories();
      setSelectedCategory(newCat.id);
      onCategoryAdded?.();
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "创建失败";
      message.error(errorMsg);
    } finally {
      setAddingCategory(false);
    }
  };

  const handleUpload = async () => {
    if (!file) {
      message.error("请选择 zip 文件");
      return;
    }
    if (selectedCategory === null) {
      message.error("请选择技能分类");
      return;
    }
    if (!cnName.trim()) {
      message.error("请输入中文名称");
      return;
    }

    // 同名技能存在时自动覆盖
    const overwrite = skillExists;

    setUploading(true);

    try {
      message.loading({ content: `正在上传 ${file.name}...`, key: "upload" });
      const result = await marketApi.uploadSkillToMarket(
        sourceId,
        file,
        {
          category_id: selectedCategory,
          overwrite,
          cn_name: cnName.trim(),
          skill_id: skillId,  // 传入 parse-zip 生成的 skill_id
        }
      );

      // 成功
      if (result.version_unchanged) {
        message.info({ content: "当前内容已是最新，无需重复上传", key: "upload" });
      } else if (result.count > 0) {
        const actionText = overwrite ? "更新" : "导入";
        message.success({ content: `上传成功，${actionText} ${result.count} 个技能`, key: "upload" });
        onSuccess();
      } else {
        message.info({ content: "未导入新技能，可能已存在", key: "upload" });
      }
      onClose();
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "上传失败";
      message.error({ content: errorMsg, key: "upload" });
    } finally {
      setUploading(false);
    }
  };

  const uploadProps: UploadProps = {
    accept: ".zip",
    showUploadList: false,
    beforeUpload: (file) => {
      const isZip = file.name.toLowerCase().endsWith(".zip");
      if (!isZip) {
        message.error("仅支持 .zip 文件");
        return false;
      }
      setFile(file);
      setSkillExists(false);
      // 调用预解析
      parseZipFile(file);
      return false;
    },
    onRemove: () => {
      setFile(null);
      setSkillExists(false);
      setCnName("");
      setSkillId("");
      setSkillName("");
      setSkillIdReused(false);
      setSkillIdUsedCount(0);
      setSkillIdUsedBy([]);
    },
    fileList: file ? [file as any] : [],
  };

  return (
    <Modal
      title="上传技能到市场"
      open={open}
      onCancel={onClose}
      onOk={handleUpload}
      okText={skillExists ? "覆盖上传" : "上传"}
      okButtonProps={{
        loading: uploading || parsingZip,
        disabled: !file || selectedCategory === null || skillIdUsedCount > 0,
      }}
      cancelText="取消"
      destroyOnClose
    >
      <div style={{ marginBottom: 16 }}>
        <Dragger {...uploadProps} style={{ marginBottom: 16 }}>
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">拖拽 .zip 文件到此处</p>
          <p className="ant-upload-hint">或点击选择文件（需包含 SKILL.md）</p>
        </Dragger>
        {parsingZip && (
          <div style={{ textAlign: "center", marginTop: 8 }}>
            <Spin size="small" />
            <span style={{ marginLeft: 8, color: "#8c8c8c" }}>正在解析...</span>
          </div>
        )}
        {file && !parsingZip && (
          <p style={{ color: "#52c41a", marginTop: 8 }}>
            已选择: {file.name}
            {skillName && <span style={{ color: "#8c8c8c" }}> ({skillName})</span>}
          </p>
        )}
      </div>

      {/* 同名技能提示（允许覆盖上传） */}
      {skillExists && !parsingZip && skillIdUsedCount === 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`检测到同名技能 "${skillName}" 已存在`}
          description="覆盖将更新现有技能版本并创建版本快照，您可以在版本历史中查看和回滚。"
        />
      )}

      {/* skill_id 冲突提示（禁止上传） */}
      {skillIdUsedCount > 0 && !parsingZip && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={`skill_id '${skillId}' 已被占用`}
          description={
            skillIdUsedCount <= 3
              ? `已被其他技能占用：${skillIdUsedBy.join("、")}`
              : `已被 ${skillIdUsedCount} 个其他技能占用`
          }
        />
      )}

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: "block", marginBottom: 8 }}>
          技能分类 <span style={{ color: "#ff4d4f" }}>*</span>
        </label>
        {loadingCategories ? (
          <Spin size="small" />
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <Select
              style={{ flex: 1 }}
              value={selectedCategory}
              onChange={setSelectedCategory}
              placeholder="选择分类"
              options={categories.map((c) => ({ label: c.name, value: c.id }))}
            />
            <Button
              icon={<PlusOutlined />}
              onClick={() => setAddCategoryModalOpen(true)}
              title="新增分类"
            />
          </div>
        )}
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: "block", marginBottom: 8 }}>
          中文名称 <span style={{ color: "#ff4d4f" }}>*</span>
        </label>
        <Input
          placeholder="请输入技能中文展示名"
          value={cnName}
          onChange={(e) => setCnName(e.target.value)}
          maxLength={50}
          showCount
        />
      </div>

      {skillId && !parsingZip && (
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", marginBottom: 8 }}>
            技能唯一标识
            <Tooltip title={
              skillIdReused
                ? "同名技能已存在，复用其 skill_id"
                : "优先从 SKILL.md metadata.skill_id 提取，若无则自动生成"
            }>
              <InfoCircleOutlined style={{ marginLeft: 4, color: "#8c8c8c" }} />
            </Tooltip>
          </label>
          <Input value={skillId} disabled />
          {skillIdReused && (
            <p style={{ color: "#52c41a", fontSize: 12, marginTop: 4 }}>
              同名技能已存在，将复用此标识
            </p>
          )}
        </div>
      )}

      {/* 新增分类弹窗 */}
      <Modal
        title="新增分类"
        open={addCategoryModalOpen}
        onOk={handleAddCategory}
        onCancel={() => {
          setAddCategoryModalOpen(false);
          setNewCategoryName("");
        }}
        confirmLoading={addingCategory}
        okText="创建"
        cancelText="取消"
        destroyOnClose
      >
        <Input
          placeholder="请输入分类名称"
          value={newCategoryName}
          onChange={(e) => setNewCategoryName(e.target.value)}
          onPressEnter={handleAddCategory}
          maxLength={128}
          autoFocus
        />
      </Modal>
      <div style={{ color: "#8c8c8c", fontSize: 12, display: "flex", alignItems: "center", gap: 4 }}>
        <Popover
          trigger="click"
          placement="top"
          content={
            <div style={{ maxWidth: 320 }}>
              <div style={{ fontWeight: 500, marginBottom: 8 }}>SKILL.md Frontmatter 示例：</div>
              <pre style={{
                background: "#f5f5f5",
                padding: 8,
                borderRadius: 4,
                fontSize: 12,
                overflow: "auto",
                whiteSpace: "pre-wrap",
                margin: 0,
              }}>
{`---
name: "my_skill"
description: "技能功能简述"
metadata:
  skill_id: "skill_abc"  # 可选，自动生成
  cn_name: "我的技能"    # 可选，≤50字
---

# 技能说明
...`}
              </pre>
              <div style={{ marginTop: 8, fontSize: 12 }}>
                <div><b>name</b>: 技能英文名（必填）</div>
                <div><b>description</b>: 功能描述（必填）</div>
                <div><b>metadata.skill_id</b>: 唯一标识，跨租户共享，同名技能自动复用（可选）</div>
                <div><b>metadata.cn_name</b>: 中文展示名，不超过50字（可选）</div>
              </div>
            </div>
          }
        >
          <QuestionCircleOutlined style={{ cursor: "pointer", color: "#1890ff" }} />
        </Popover>
        <span>技能名称、描述和唯一标识从 SKILL.md frontmatter 自动解析，同名技能复用已有标识</span>
      </div>
    </Modal>
  );
}