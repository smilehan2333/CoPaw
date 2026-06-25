import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Collapse, Input, Radio, Select } from "@agentscope-ai/design";
import { Alert, Spin, Tag } from "antd";
import { CheckOutlined, CloseOutlined, SearchOutlined, UserOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useIframeStore } from "@/stores/iframeStore";
import {
  fetchTenantsBySource,
  type TenantSourceInfo,
} from "@/api/modules/userInfo";
import { BBK_ID_MAP, BBK_ID_TO_NAME_MAP } from "@/constants/bbk";
import { DEFAULT_SOURCE_ID } from "@/constants/identity";
import type { TenantSelectorProps } from "./types";
import styles from "./index.module.less";

/**
 * 解析手动输入的租户 ID 文本
 */
function parseManualTenantIds(input: string): string[] {
  return Array.from(
    new Set(
      input
        .split(/[\s,]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

/**
 * 判断两个租户 ID 数组是否相同
 */
function haveSameTenantIds(left: string[], right: string[]): boolean {
  const leftTenantIds = Array.from(new Set(left));
  const rightTenantIds = Array.from(new Set(right));

  if (leftTenantIds.length !== rightTenantIds.length) {
    return false;
  }

  const rightSet = new Set(rightTenantIds);
  return leftTenantIds.every((tenantId) => rightSet.has(tenantId));
}

/**
 * 统一租户选择组件
 *
 * 特点：
 * - 自动从 useIframeStore 获取 sourceId，fallback 到 DEFAULT_SOURCE_ID
 * - 自动调用 fetchTenantsBySource 加载租户信息
 * - 支持按机构/按用户双模式切换
 * - 支持 excludeTenantId 过滤当前租户
 * - 支持 onLoadError 回调处理加载错误
 * - 筛选输入框：搜索租户，帮助快速定位
 * - 额外ID输入框：输入不在列表中的租户ID
 * - 顶部标签展示已选中的租户
 */
export function TenantSelector({
  selectedTenantIds,
  onChange,
  onSelectionInfoChange,
  hint,
  excludeTenantId,
  onLoadError,
}: TenantSelectorProps) {
  const { t } = useTranslation();
  const sourceId = useIframeStore((state) => state.source) || DEFAULT_SOURCE_ID;

  // 加载状态
  const [loading, setLoading] = useState(false);
  // 错误状态
  const [error, setError] = useState<Error | null>(null);

  // 租户选项数据
  const [tenantOptions, setTenantOptions] = useState<TenantSourceInfo[]>([]);

  // 分发模式
  const [targetMode, setTargetMode] = useState<"bbk_id" | "user_id">("bbk_id");

  // 机构选择
  const [selectedBbkIds, setSelectedBbkIds] = useState<string[]>([]);

  // 用户模式：筛选关键字
  const [filterText, setFilterText] = useState("");

  // 用户模式：卡片选中的租户ID（列表中的）
  const [selectedInListTenantIds, setSelectedInListTenantIds] = useState<string[]>([]);

  // 用户模式：额外输入的租户ID（不在列表中的）
  const [extraTenantIdsText, setExtraTenantIdsText] = useState("");

  // 用户是否正在编辑额外输入框（避免输入时被外部状态覆盖）
  const [isEditingExtra, setIsEditingExtra] = useState(false);

  // 打开时自动加载租户信息
  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchTenantsBySource(sourceId)
      .then((items) => {
        const filtered = excludeTenantId
          ? items.filter((item) => item.tenant_id !== excludeTenantId)
          : items;
        setTenantOptions(filtered);
      })
      .catch((err) => {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        onLoadError?.(error);
      })
      .finally(() => setLoading(false));
  }, [sourceId, excludeTenantId, onLoadError]);

  // 可用租户 ID 列表
  const availableTenantIds = useMemo(() => {
    return tenantOptions.map((item) => item.tenant_id);
  }, [tenantOptions]);

  // 租户查询表
  const tenantLookup = useMemo(() => {
    return new Map(tenantOptions.map((item) => [item.tenant_id, item]));
  }, [tenantOptions]);

  // 按机构过滤的用户 ID 列表
  const filteredTenantIds = useMemo(() => {
    if (targetMode !== "bbk_id") {
      return availableTenantIds;
    }
    if (selectedBbkIds.length === 0) {
      return [];
    }
    return availableTenantIds.filter((tenantId) => {
      const tenant = tenantLookup.get(tenantId);
      return selectedBbkIds.includes(tenant?.bbk_id || "");
    });
  }, [availableTenantIds, selectedBbkIds, targetMode, tenantLookup]);

  // 根据筛选关键字过滤的租户ID列表（用于显示卡片）
  const displayedTenantIds = useMemo(() => {
    if (!filterText.trim()) {
      return availableTenantIds;
    }
    const keyword = filterText.toLowerCase();
    return availableTenantIds.filter((tenantId) => {
      const tenant = tenantLookup.get(tenantId);
      const name = tenant?.tenant_name?.toLowerCase() || "";
      const id = tenantId.toLowerCase();
      return name.includes(keyword) || id.includes(keyword);
    });
  }, [availableTenantIds, filterText, tenantLookup]);

  // 解析额外输入的租户ID
  const parsedExtraTenantIds = useMemo(() => {
    return parseManualTenantIds(extraTenantIdsText);
  }, [extraTenantIdsText]);

  // 额外ID中，不在列表中的部分（真正的额外ID）
  const extraTenantIds = useMemo(() => {
    return parsedExtraTenantIds.filter((id) => !availableTenantIds.includes(id));
  }, [parsedExtraTenantIds, availableTenantIds]);

  // 额外ID中，已在列表中的部分（需要自动选中卡片）
  const inListExtraTenantIds = useMemo(() => {
    return parsedExtraTenantIds.filter((id) => availableTenantIds.includes(id));
  }, [parsedExtraTenantIds, availableTenantIds]);

  // 实际的卡片选中列表（手动选中 + 额外输入中已存在于列表的自动选中）
  const effectiveInListTenantIds = useMemo(() => {
    return Array.from(new Set([...selectedInListTenantIds, ...inListExtraTenantIds]));
  }, [selectedInListTenantIds, inListExtraTenantIds]);

  // 最终合并的用户 ID 列表
  const mergedTenantIds = useMemo(() => {
    if (targetMode === "bbk_id") {
      return filteredTenantIds;
    }
    // 用户模式：卡片选中的 + 额外输入的（额外输入中已在列表的通过 effectiveInListTenantIds 合并）
    return Array.from(new Set([...effectiveInListTenantIds, ...extraTenantIds]));
  }, [targetMode, filteredTenantIds, effectiveInListTenantIds, extraTenantIds]);

  const selectedTenantInfos = useMemo(() => {
    return mergedTenantIds.map(
      (tenantId) =>
        tenantLookup.get(tenantId) ?? {
          tenant_id: tenantId,
          tenant_name: null,
          bbk_id: null,
        },
    );
  }, [mergedTenantIds, tenantLookup]);

  // 按机构分组的用户列表（用于展示具体用户）
  const groupedTenants = useMemo(() => {
    if (targetMode !== "bbk_id" || selectedBbkIds.length === 0) return [];
    return selectedBbkIds
      .map((bbkId) => {
        const users = availableTenantIds
          .map((tenantId) => tenantLookup.get(tenantId))
          .filter(
            (tenant): tenant is TenantSourceInfo =>
              Boolean(tenant) && tenant?.bbk_id === bbkId,
          );
        return {
          bbkId,
          bbkName: BBK_ID_TO_NAME_MAP[bbkId] || bbkId,
          users,
        };
      })
      .filter((group) => group.users.length > 0);
  }, [availableTenantIds, selectedBbkIds, targetMode, tenantLookup]);

  // 同步外部选中状态到内部（仅在 user_id 模式下）
  useEffect(() => {
    if (targetMode === "bbk_id") return;

    // 如果外部状态为空，清空内部状态（避免循环）
    if (selectedTenantIds.length === 0) {
      setSelectedInListTenantIds((current) =>
        current.length === 0 ? current : []
      );
      // 用户正在编辑时不重置额外输入框
      if (!isEditingExtra) {
        setExtraTenantIdsText((current) =>
          current === "" ? current : ""
        );
      }
      return;
    }

    // 拆分：列表中的 → 卡片选中，不在列表中的 → 额外ID
    const inList = selectedTenantIds.filter((id) => availableTenantIds.includes(id));
    const extra = selectedTenantIds.filter((id) => !availableTenantIds.includes(id));

    setSelectedInListTenantIds((current) =>
      haveSameTenantIds(current, inList) ? current : inList
    );
    // 用户正在编辑时不重置额外输入框内容
    if (!isEditingExtra) {
      setExtraTenantIdsText((current) => {
        const nextText = extra.join("\n");
        return current === nextText ? current : nextText;
      });
    }
  }, [availableTenantIds, selectedTenantIds, targetMode, isEditingExtra]);

  // 内部状态变更通知外部
  // 注意：只在 user_id 模式下，且 mergedTenantIds 真正变化时才通知
  const prevMergedTenantIdsRef = useRef<string[]>([]);

  useEffect(() => {
    // bbk_id 模式下，直接使用 filteredTenantIds
    if (targetMode === "bbk_id") {
      if (!haveSameTenantIds(prevMergedTenantIdsRef.current, filteredTenantIds)) {
        prevMergedTenantIdsRef.current = filteredTenantIds;
        onChange(filteredTenantIds);
      }
      return;
    }

    // user_id 模式下，检查 mergedTenantIds 是否变化
    if (!haveSameTenantIds(prevMergedTenantIdsRef.current, mergedTenantIds)) {
      prevMergedTenantIdsRef.current = mergedTenantIds;
      onChange(mergedTenantIds);
    }
  }, [targetMode, filteredTenantIds, mergedTenantIds, onChange]);

  useEffect(() => {
    onSelectionInfoChange?.(selectedTenantInfos);
  }, [onSelectionInfoChange, selectedTenantInfos]);

  // 切换模式时清空选择
  const handleModeChange = useCallback((mode: "bbk_id" | "user_id") => {
    setTargetMode(mode);
    setSelectedBbkIds([]);
    setFilterText("");
    setSelectedInListTenantIds([]);
    setExtraTenantIdsText("");
    setIsEditingExtra(false);
  }, []);

  // 全选/清空按钮（使用函数式更新避免依赖）
  const handleSelectAll = useCallback(() => {
    setSelectedInListTenantIds(Array.from(new Set(displayedTenantIds)));
  }, [displayedTenantIds]);

  const handleClearAll = useCallback(() => {
    setSelectedInListTenantIds([]);
    setExtraTenantIdsText("");
    setIsEditingExtra(false);
  }, []);

  // 用户卡片点击（使用函数式更新）
  const handleUserCardClick = useCallback(
    (tenantId: string, selected: boolean) => {
      setSelectedInListTenantIds((prev) =>
        selected ? prev.filter((id) => id !== tenantId) : [...prev, tenantId]
      );
    },
    []
  );

  // 移除已选租户（使用函数式更新）
  // 同时清除手动选中和额外输入中的该ID
  const handleRemoveSelected = useCallback(
    (tenantId: string) => {
      // 从手动选中列表移除
      setSelectedInListTenantIds((prev) => prev.filter((id) => id !== tenantId));
      // 从额外输入文本中移除
      setExtraTenantIdsText((prev) => {
        const ids = parseManualTenantIds(prev).filter((id) => id !== tenantId);
        return ids.join("\n");
      });
    },
    []
  );

  // 渲染租户名称
  const renderTenantName = useCallback(
    (tenantId: string) => {
      const tenant = tenantLookup.get(tenantId);
      return tenant?.tenant_name
        ? `${tenant.tenant_name} (${tenantId})`
        : tenantId;
    },
    [tenantLookup]
  );

  // 加载错误时显示提示
  if (error) {
    return (
      <Alert
        type="error"
        message={t("tenantSelector.loadError")}
        description={error.message}
      />
    );
  }

  return (
    <div className={styles.tenantSelector}>
      {/* 分发目标模式选择 */}
      <div className={styles.modeSection}>
        <div className={styles.sectionLabel}>{t("tenantSelector.targetMode")}</div>
        <Radio.Group
          value={targetMode}
          onChange={(event) => handleModeChange(event.target.value)}
        >
          <Radio value="bbk_id">{t("tenantSelector.byOrganization")}</Radio>
          <Radio value="user_id">{t("tenantSelector.byUser")}</Radio>
        </Radio.Group>
      </div>

      {loading ? (
        <Spin size="small" className={styles.loadingSpin} />
      ) : (
        <>
          {/* 按机构：多选机构 */}
          {targetMode === "bbk_id" && (
            <div className={styles.orgSection}>
              <div className={styles.sectionLabel}>
                {t("tenantSelector.selectOrganization")}
              </div>
              <Select
                mode="multiple"
                placeholder={t("tenantSelector.selectOrganizationPlaceholder")}
                value={selectedBbkIds}
                onChange={setSelectedBbkIds}
                options={BBK_ID_MAP}
                className={styles.orgSelect}
              />
              <div className={styles.hint}>
                {t("tenantSelector.organizationSelectionHint", {
                  count: selectedBbkIds.length,
                  userCount: filteredTenantIds.length,
                })}
              </div>
              {/* 机构下用户明细 */}
              {groupedTenants.length > 0 && (
                <Collapse
                  size="small"
                  items={groupedTenants.map((group) => ({
                    key: group.bbkId,
                    label: (
                      <span className={styles.collapseLabel}>
                        <UserOutlined className={styles.collapseIcon} />
                        {group.bbkName}
                        <span className={styles.collapseCount}>
                          {t("tenantSelector.userCount", { count: group.users.length })}
                        </span>
                      </span>
                    ),
                    children: (
                      <div className={styles.userDetailGrid}>
                        {group.users.map((user) => (
                          <div
                            key={user.tenant_id}
                            className={styles.userDetailItem}
                            title={renderTenantName(user.tenant_id)}
                          >
                            {renderTenantName(user.tenant_id)}
                          </div>
                        ))}
                      </div>
                    ),
                  }))}
                />
              )}
            </div>
          )}

          {/* 按用户：网格卡片选择 */}
          {targetMode === "user_id" && (
            <>
              {/* 标题栏 + 全选/清空 */}
              <div className={styles.userHeader}>
                <div className={styles.sectionLabel}>
                  {t("tenantSelector.selectUsers")}
                </div>
                <div className={styles.actionButtons}>
                  <Button size="small" onClick={handleSelectAll}>
                    {t("tenantSelector.selectAll")}
                  </Button>
                  <Button size="small" onClick={handleClearAll}>
                    {t("tenantSelector.clearAll")}
                  </Button>
                </div>
              </div>
              {hint ? <div className={styles.hint}>{hint}</div> : null}

              {/* 筛选输入框 */}
              <div className={styles.filterSection}>
                <Input
                  placeholder={t("tenantSelector.filterPlaceholder")}
                  value={filterText}
                  onChange={(e) => setFilterText(e.target.value)}
                  prefix={<SearchOutlined />}
                  allowClear
                />
                {filterText.trim() && (
                  <div className={styles.hint}>
                    {t("tenantSelector.filterHint", {
                      count: displayedTenantIds.length,
                      total: availableTenantIds.length,
                    })}
                  </div>
                )}
              </div>

              {/* 已选中租户标签 */}
              {mergedTenantIds.length > 0 && (
                <div className={styles.selectedTags}>
                  <span className={styles.selectedCount}>
                    {t("tenantSelector.selectedCount", {
                      count: mergedTenantIds.length,
                    })}
                  </span>
                  <div className={styles.tagList}>
                    {[...effectiveInListTenantIds, ...extraTenantIds].map((tenantId) => {
                      const isInList = availableTenantIds.includes(tenantId);
                      const displayName = isInList
                        ? renderTenantName(tenantId)
                        : tenantId;
                      return (
                        <Tag
                          key={tenantId}
                          className={styles.selectedTag}
                          closable
                          closeIcon={<CloseOutlined />}
                          onClose={(e) => {
                            e.preventDefault();
                            handleRemoveSelected(tenantId);
                          }}
                        >
                          {displayName}
                        </Tag>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* 用户卡片网格 */}
              <div className={styles.userGrid}>
                {displayedTenantIds.map((tenantId) => {
                  const selected = effectiveInListTenantIds.includes(tenantId);
                  return (
                    <button
                      key={tenantId}
                      type="button"
                      onClick={() => handleUserCardClick(tenantId, selected)}
                      className={`${styles.userCard} ${
                        selected ? styles.userCardSelected : ""
                      }`}
                    >
                      {selected ? (
                        <span className={styles.checkIcon}>
                          <CheckOutlined />
                        </span>
                      ) : null}
                      <span>{renderTenantName(tenantId)}</span>
                    </button>
                  );
                })}
                {displayedTenantIds.length === 0 && filterText.trim() && (
                  <div className={styles.noMatchHint}>
                    {t("tenantSelector.noMatchHint")}
                  </div>
                )}
              </div>

              {/* 额外租户ID输入 */}
              <div className={styles.extraInputSection}>
                <div className={styles.sectionLabel}>
                  {t("tenantSelector.extraInput")}
                </div>
                <div className={styles.hint}>
                  {t("tenantSelector.extraInputHint")}
                </div>
                <textarea
                  rows={3}
                  value={extraTenantIdsText}
                  onChange={(e) => {
                    setIsEditingExtra(true);
                    setExtraTenantIdsText(e.target.value);
                  }}
                  onBlur={() => {
                    setIsEditingExtra(false);
                    // 编辑结束后，解析并通知外部
                    const parsed = parseManualTenantIds(extraTenantIdsText);
                    const extraIds = parsed.filter((id) => !availableTenantIds.includes(id));
                    const inListIds = parsed.filter((id) => availableTenantIds.includes(id));
                    setSelectedInListTenantIds((prev) =>
                      Array.from(new Set([...prev, ...inListIds]))
                    );
                    // 整理文本格式
                    setExtraTenantIdsText(extraIds.join("\n"));
                  }}
                  placeholder={t("tenantSelector.extraInputPlaceholder")}
                  className={styles.manualInput}
                />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

export default TenantSelector;
