import { useEffect, useCallback, useRef, useMemo, useState } from "react";
import { Dropdown, Spin, Tooltip } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  CheckOutlined,
  LoadingOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { SparkDownLine } from "@agentscope-ai/icons";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import { useProviderModelStore } from "../../../stores/providerModelStore";
import styles from "./index.module.less";

interface EligibleProvider {
  id: string;
  name: string;
  models: Array<{ id: string; name: string }>;
}

export default function ModelSelector() {
  const { t } = useTranslation();
  const providers = useProviderModelStore((state) => state.providers);
  const activeModels = useProviderModelStore((state) => state.activeModels);
  const loading = useProviderModelStore((state) => state.loading);
  const loadModelData = useProviderModelStore((state) => state.loadModelData);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const savingRef = useRef(false);
  const location = useLocation();
  const { message } = useAppMessage();

  const fetchData = useCallback(async () => {
    try {
      // Use tenant-level scope (agent scope deprecated)
      await loadModelData({ scope: "effective" });
    } catch (err) {
      console.error("ModelSelector: failed to load data", err);
    }
  }, [loadModelData]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Re-sync active model whenever the route switches back to /chat
  const prevPathRef = useRef(location.pathname);
  useEffect(() => {
    const prev = prevPathRef.current;
    const curr = location.pathname;
    prevPathRef.current = curr;
    const comingToChat = curr.startsWith("/chat") && !prev.startsWith("/chat");
    if (comingToChat) {
      // Use tenant-level scope (agent scope deprecated)
      loadModelData({ scope: "effective" }).catch(() => {});
    }
  }, [loadModelData, location.pathname]);

  // Eligible providers: configured + has models
  const eligibleProviders: EligibleProvider[] = useMemo(
    () =>
      providers
        .filter((p) => {
          const hasModels =
            (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
          if (!hasModels) return false;
          if (p.require_api_key === false) return !!p.base_url;
          if (p.is_custom) return !!p.base_url;
          if (p.require_api_key ?? true) return !!p.api_key;
          return true;
        })
        .map((p) => ({
          id: p.id,
          name: p.name,
          models: [...(p.models ?? []), ...(p.extra_models ?? [])],
        })),
    [providers],
  );

  const activeProviderId = activeModels?.active_llm?.provider_id;
  const activeModelId = activeModels?.active_llm?.model;

  // Display label for trigger button
  const activeModelName = (() => {
    if (!activeProviderId || !activeModelId)
      return t("modelSelector.selectModel");
    for (const p of eligibleProviders) {
      if (p.id === activeProviderId) {
        const m = p.models.find((m) => m.id === activeModelId);
        if (m) return m.name || m.id;
      }
    }
    return activeModelId;
  })();

  const handleOpenChange = useCallback(
    async (next: boolean) => {
      setOpen(next);
      if (next) {
        // Re-fetch active model every time the dropdown opens
        // Use tenant-level scope (agent scope deprecated)
        try {
          await loadModelData({ scope: "effective" });
        } catch {
          // ignore
        }
      }
    },
    [loadModelData],
  );

  const handleSelect = async (providerId: string, modelId: string) => {
    if (savingRef.current) return;
    if (providerId === activeProviderId && modelId === activeModelId) {
      setOpen(false);
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setOpen(false);
    try {
      // Use 'global' scope - tenant-level active model (agent scope deprecated)
      await providerApi.setActiveLlm({
        provider_id: providerId,
        model: modelId,
        scope: "global",
      });
      // Notify ChatPage to refresh multimodal capabilities
      window.dispatchEvent(new CustomEvent("model-switched"));
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : t("modelSelector.switchFailed");
      message.error(msg);
    } finally {
      setSaving(false);
      savingRef.current = false;
    }
  };

  const dropdownContent = (
    <div className={styles.panel}>
      {loading ? (
        <div className={styles.spinWrapper}>
          <Spin size="small" />
        </div>
      ) : eligibleProviders.length === 0 ? (
        <div className={styles.emptyTip}>
          {t("modelSelector.noConfiguredModels")}
        </div>
      ) : (
        eligibleProviders.map((provider) => {
          const isProviderActive = provider.id === activeProviderId;
          return (
            <div
              key={provider.id}
              className={[
                styles.providerItem,
                isProviderActive ? styles.providerItemActive : "",
              ].join(" ")}
            >
              <span className={styles.providerName}>{provider.name}</span>
              <RightOutlined className={styles.providerArrow} />

              {/* Level-2 submenu — shown on parent hover via CSS */}
              <div className={`${styles.submenu} modelSubmenu`}>
                {provider.models.map((model) => {
                  const isActive =
                    isProviderActive && model.id === activeModelId;
                  return (
                    <div
                      key={model.id}
                      className={[
                        styles.modelItem,
                        isActive ? styles.modelItemActive : "",
                      ].join(" ")}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSelect(provider.id, model.id);
                      }}
                    >
                      <span className={styles.modelName}>
                        {model.name || model.id}
                      </span>
                      {isActive && (
                        <CheckOutlined className={styles.checkIcon} />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })
      )}
    </div>
  );

  return (
    <Dropdown
      open={open}
      onOpenChange={handleOpenChange}
      dropdownRender={() => dropdownContent}
      trigger={["click"]}
      placement="bottomLeft"
    >
      <Tooltip title={t("chat.modelSelectTooltip")} mouseEnterDelay={0.5}>
        <div
          className={[styles.trigger, open ? styles.triggerActive : ""].join(
            " ",
          )}
        >
          {saving && (
            <LoadingOutlined style={{ fontSize: 11, color: "#3769FC" }} />
          )}
          <span className={styles.triggerName}>{activeModelName}</span>
          <SparkDownLine
            className={[
              styles.triggerArrow,
              open ? styles.triggerArrowOpen : "",
            ].join(" ")}
          />
        </div>
      </Tooltip>
    </Dropdown>
  );
}
