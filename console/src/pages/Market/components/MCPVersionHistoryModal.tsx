import { useEffect, useState } from "react";
import {
  Button,
  Modal,
  Spin,
  Tag,
  Typography,
  message,
  Popconfirm,
  Empty,
} from "antd";
import {
  UserOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
} from "@ant-design/icons";
import {
  marketMcpVersionApi,
  MCPVersion,
  MCPVersionsManifest,
} from "../../../api/modules/marketMcpVersion";
import { MCPVersionCompareDrawer } from "./MCPVersionCompareDrawer";

const { Text, Title } = Typography;

/**
 * 市场 MCP 版本历史 Modal（与 SkillVersionHistoryModal 对称）。
 *
 * 设计文档: docs/superpowers/specs/2026-06-13-skill-mcp-version-control-design.md §6.3
 *
 * 与 Skill 版本历史的差异：
 * - 没有 compare（设计文档未要求 MCP 版本 diff）
 * - 显示 source_user_* 信息（哪个用户提交的这个快照、用户那一侧版本号）
 */

interface MCPVersionHistoryModalProps {
  open: boolean;
  itemId: string;
  mcpName: string;
  currentVersion: string;
  sourceId: string;
  isManager?: boolean;
  onClose: () => void;
  onVersionSwitched?: () => void;
}

function formatDateTime(value: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function describeOperator(version: MCPVersion): string {
  const name = version.created_by_name?.trim();
  const id = version.created_by?.trim();
  // name 与 id 相同时只显示一次，避免出现 "80112233/80112233"
  if (name && id) {
    return name === id ? name : `${name}/${id}`;
  }
  if (name) return name;
  if (id) return id;
  return "-";
}

/** 在版本号字符串前补 "v"（仅用于展示，不改变请求/接口里的原值）。 */
function displayVersion(versionId: string): string {
  if (!versionId) return "";
  return /^v/i.test(versionId) ? versionId : `v${versionId}`;
}

/**
 * 把 source_user_version 拼成单行描述。
 *
 * 市场版本和用户同步版本是独立语义，即使数值相同也展示用户同步版本。
 * 规则（仅展示"用户同步版本"）：
 * - 无 source_user_version 或 = "v0.0.0"（admin zip 路径） → 不显示
 * - 否则 → "用户同步版本 vX.Y.Z"
 */
function describeSource(version: MCPVersion): string | null {
  const userVersion = version.source_user_version?.trim();
  if (!userVersion || userVersion === "v0.0.0") return null;
  return `用户同步版本 ${displayVersion(userVersion)}`;
}

export function MCPVersionHistoryModal(props: MCPVersionHistoryModalProps) {
  const {
    open,
    itemId,
    mcpName,
    sourceId,
    isManager,
    onClose,
    onVersionSwitched,
  } = props;

  const [loading, setLoading] = useState(false);
  const [versions, setVersions] = useState<MCPVersion[]>([]);
  const [nameFromManifest, setNameFromManifest] = useState("");
  const [switching, setSwitching] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [compareDrawerOpen, setCompareDrawerOpen] = useState(false);
  const [compareTargetVersion, setCompareTargetVersion] = useState<string>("");

  useEffect(() => {
    if (!open || !itemId || !sourceId) {
      return;
    }

    setLoading(true);
    marketMcpVersionApi
      .listVersions(sourceId, itemId)
      .then((data: MCPVersionsManifest) => {
        setVersions(data.versions || []);
        setNameFromManifest(data.name || mcpName);
      })
      .catch((err) => {
        console.error("Failed to load MCP versions:", err);
        message.error("加载 MCP 版本历史失败");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [open, itemId, sourceId, mcpName]);

  const currentVersionInfo = versions.find((v) => v.is_current);

  const handleSwitchVersion = async (versionId: string) => {
    if (!isManager) {
      message.warning("需要管理员权限才能切换版本");
      return;
    }

    setSwitching(true);
    try {
      const result = await marketMcpVersionApi.switchVersion(
        sourceId,
        itemId,
        versionId,
      );
      if (result.success) {
        message.success(`已切换到版本 ${displayVersion(versionId)}`);
        onVersionSwitched?.();
        const data = await marketMcpVersionApi.listVersions(sourceId, itemId);
        setVersions(data.versions || []);
      } else {
        message.error(result.message || "切换版本失败");
      }
    } catch (err) {
      console.error("Failed to switch MCP version:", err);
      message.error("切换版本失败");
    } finally {
      setSwitching(false);
    }
  };

  const handleDeleteVersion = async (versionId: string) => {
    if (!isManager) {
      message.warning("需要管理员权限才能删除版本");
      return;
    }

    setDeleting(true);
    try {
      const result = await marketMcpVersionApi.deleteVersion(
        sourceId,
        itemId,
        versionId,
      );
      if (result.success) {
        message.success(`已删除版本 ${displayVersion(versionId)}`);
        const data = await marketMcpVersionApi.listVersions(sourceId, itemId);
        setVersions(data.versions || []);
      } else {
        message.error(result.message || "删除版本失败");
      }
    } catch (err) {
      console.error("Failed to delete MCP version:", err);
      message.error("删除版本失败");
    } finally {
      setDeleting(false);
    }
  };

  // 点击比对时，打开比对 Drawer。基准 = 选中版本，目标 = 当前 is_current 版本
  const handleCompare = (versionId: string) => {
    if (!currentVersionInfo) {
      message.warning("未找到当前版本");
      return;
    }
    setCompareTargetVersion(versionId);
    setCompareDrawerOpen(true);
  };

  const handleCloseCompare = () => {
    setCompareDrawerOpen(false);
    setCompareTargetVersion("");
  };

  return (
    <>
      <Modal
        open={open}
        onCancel={onClose}
        footer={null}
        width={720}
        title={
          <Title level={4} style={{ margin: 0 }}>
            版本历史 - {nameFromManifest || mcpName}
          </Title>
        }
        styles={{
          body: { maxHeight: 480, overflow: "auto" },
        }}
      >
      {loading ? (
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
      ) : versions.length === 0 ? (
        <Empty description="暂无版本历史" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {versions.map((version) => {
            const isCurrent = version.is_current;
            const isInitial = version.is_initial;
            const canSwitch = !isCurrent && isManager;
            const canDelete = !isCurrent && !isInitial && isManager;
            const sourceLine = describeSource(version);

            return (
              <div
                key={version.version_id}
                style={{
                  padding: 14,
                  border: "1px solid #e1e4e8",
                  borderRadius: 8,
                  backgroundColor: isCurrent ? "#f6f8fa" : "#fff",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    {isCurrent && (
                      <Tag
                        style={{
                          backgroundColor: "#28a745",
                          color: "#fff",
                          borderRadius: 3,
                          fontSize: 12,
                        }}
                      >
                        当前
                      </Tag>
                    )}
                    {isInitial && (
                      <Tag
                        style={{
                          backgroundColor: "#0366d6",
                          color: "#fff",
                          borderRadius: 3,
                          fontSize: 12,
                        }}
                      >
                        初始
                      </Tag>
                    )}
                    <Text strong style={{ fontSize: 14 }}>
                      {displayVersion(version.version_id)}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      <ClockCircleOutlined style={{ marginRight: 4 }} />
                      {formatDateTime(version.created_at)}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      <UserOutlined style={{ marginRight: 4 }} />
                      {describeOperator(version)}
                    </Text>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    {canSwitch && (
                      <Popconfirm
                        title="确定切换到此版本？"
                        description={`将 MCP 从 ${
                          displayVersion(currentVersionInfo?.version_id || '') || "当前版本"
                        } 切换到 ${displayVersion(version.version_id)}`}
                        onConfirm={() =>
                          handleSwitchVersion(version.version_id)
                        }
                        okText="切换"
                        cancelText="取消"
                        icon={
                          <ExclamationCircleOutlined
                            style={{ color: "#faad14" }}
                          />
                        }
                      >
                        <Button
                          size="small"
                          type="primary"
                          ghost
                          loading={switching}
                          style={{ fontSize: 11 }}
                        >
                          切换到此版本
                        </Button>
                      </Popconfirm>
                    )}
                    {!isCurrent && (
                      <Button
                        size="small"
                        onClick={() => handleCompare(version.version_id)}
                        style={{ fontSize: 11 }}
                      >
                        比对
                      </Button>
                    )}
                    {canDelete && (
                      <Popconfirm
                        title="确定删除此版本？"
                        description="删除后无法恢复"
                        onConfirm={() =>
                          handleDeleteVersion(version.version_id)
                        }
                        okText="删除"
                        okButtonProps={{ danger: true }}
                        cancelText="取消"
                      >
                        <Button
                          size="small"
                          danger
                          loading={deleting}
                          style={{ fontSize: 11 }}
                        >
                          删除
                        </Button>
                      </Popconfirm>
                    )}
                  </div>
                </div>
                {version.description && (
                  <Text
                    type="secondary"
                    style={{ fontSize: 13, marginTop: 6, display: "block" }}
                  >
                    {version.description}
                  </Text>
                )}
                {sourceLine && (
                  <Text
                    type="secondary"
                    style={{ fontSize: 12, marginTop: 4, display: "block" }}
                  >
                    {sourceLine}
                  </Text>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div style={{ marginTop: 12, color: "#87867f", fontSize: 13 }}>
        <Text type="secondary">共 {versions.length} 个版本</Text>
      </div>
      </Modal>

      <MCPVersionCompareDrawer
        open={compareDrawerOpen}
        sourceId={sourceId}
        itemId={itemId}
        baseVersion={compareTargetVersion}
        targetVersion={currentVersionInfo?.version_id || ""}
        onClose={handleCloseCompare}
      />
    </>
  );
}
