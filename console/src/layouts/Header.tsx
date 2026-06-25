import { Layout, Space, Select, Switch } from "antd";
// import ThemeToggleButton from "../components/ThemeToggleButton";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { useBrandTheme } from "../contexts/BrandThemeContext";
import { useState, useEffect } from "react";
import { useIframeStore } from "../stores/iframeStore";
import { DEFAULT_BBK_ID, DEFAULT_USER_ID, DEFAULT_USER_NAME } from "../constants/identity";
import { fetchTenantsBySource, TenantSourceInfo } from "@/api/modules/userInfo.ts";

const { Header: AntHeader } = Layout;

export const OPS_MODE_KEY = "swe-ops-mode";
const REAL_USER_ID_KEY = "swe-real-user-id";
const REAL_USER_NAME_KEY = "swe-real-user-name";
const REAL_USER_BBK_KEY = "swe-real-user-bbk";
export default function Header() {
  const { isDark } = useTheme();
  // 获取动态品牌配置，用于显示正确的 logo
  const { theme: brandTheme } = useBrandTheme();

  const isSuperManager = useIframeStore((state) => state.isSuperManager);
  const manager = useIframeStore((state) => state.manager);
  const userId = useIframeStore((state) => state.userId);
  const userName = useIframeStore((state) => state.userName);
  const bbk = useIframeStore((state) => state.bbk);
  const source = useIframeStore((state) => state.source);
  const setContext = useIframeStore((state) => state.setContext);
  const sourceForSwitch = source;
  const canUseOpsMode = (manager || isSuperManager) && source === "ruice";

  const [opsMode, setOpsMode] = useState(
    () => sessionStorage.getItem(OPS_MODE_KEY) === "true",
  );
  const [realUserId, setRealUserId] = useState<string | null>(
    () => sessionStorage.getItem(REAL_USER_ID_KEY),
  );
  const [realUserName, setRealUserName] = useState<string | null>(
    () => sessionStorage.getItem(REAL_USER_NAME_KEY),
  );
  const [realBbk, setRealBbk] = useState<string | null>(
    () => sessionStorage.getItem(REAL_USER_BBK_KEY),
  );
  const [userList, setUserList] = useState<TenantSourceInfo[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!canUseOpsMode || !opsMode) {
      setUserList([]);
      return;
    }

    setLoading(true);
    fetchTenantsBySource(source)
      .then((users) => {
        setUserList(users);
      })
      .catch((err) => {
        console.error("[Header] Failed to fetch source users:", err);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [canUseOpsMode, opsMode, sourceForSwitch, userId]);

  const handleOpsModeChange = (checked: boolean) => {
    if (checked) {
      const currentRealUserId = userId || DEFAULT_USER_ID;
      const currentRealUserName = userName || DEFAULT_USER_NAME;
      const currentRealUserBbk = bbk || DEFAULT_BBK_ID
      sessionStorage.setItem(REAL_USER_ID_KEY, currentRealUserId);
      sessionStorage.setItem(REAL_USER_NAME_KEY, currentRealUserName);
      sessionStorage.setItem(REAL_USER_BBK_KEY, currentRealUserBbk);
      sessionStorage.setItem(OPS_MODE_KEY, "true");
      setRealUserId(currentRealUserId);
      setRealUserName(currentRealUserName)
      setRealBbk(currentRealUserBbk)
      setOpsMode(true);
      return;
    }

    const nextUserId = realUserId || sessionStorage.getItem(REAL_USER_ID_KEY) || DEFAULT_USER_ID;
    const nextUserName = realUserName || sessionStorage.getItem(REAL_USER_NAME_KEY) || DEFAULT_USER_NAME;
    const nextUserBbk = realBbk || sessionStorage.getItem(REAL_USER_BBK_KEY) || DEFAULT_BBK_ID;
    setOpsMode(false);
    setRealUserId(null);
    setRealUserName(null)
    setRealBbk(null)
    sessionStorage.removeItem(OPS_MODE_KEY);
    sessionStorage.removeItem(REAL_USER_ID_KEY);
    sessionStorage.removeItem(REAL_USER_NAME_KEY);
    sessionStorage.removeItem(REAL_USER_BBK_KEY)
    console.log(nextUserName, nextUserId, nextUserBbk)
    if (userId !== nextUserId) {
      setContext({
        userId: nextUserId,
        userName: nextUserName,
        bbk: nextUserBbk,
      });
    }
  };

  const handleUserChange = (newUserId: string | undefined) => {
    const newUser = userList.find(item => item.tenant_id === newUserId)
    console.log('newUser', newUser)
    const nextUserId = newUser?.tenant_id || realUserId || sessionStorage.getItem(REAL_USER_ID_KEY) || DEFAULT_USER_ID;
    const nextUserName = newUser?.tenant_name || realUserName || sessionStorage.getItem(REAL_USER_NAME_KEY) || DEFAULT_USER_NAME;
    const nextUserBbk = newUser?.bbk_id || realBbk || sessionStorage.getItem(REAL_USER_BBK_KEY) || DEFAULT_BBK_ID;
    if (newUser?.tenant_id && !userList.includes(newUser)) return;
    console.log(nextUserName, nextUserId, nextUserBbk)
    setContext({
      userId: nextUserId,
      userName: nextUserName,
      bbk: nextUserBbk,
    });
  };

  return (
    <>
      <AntHeader className={styles.header}>
        <div className={styles.logoWrapper}>
          {/* ==================== 品牌主题 (Kun He) ==================== */}
          {/* 使用动态品牌 logo，根据 source 和明暗主题切换 */}
          <img
            src={
              isDark
                ? `${import.meta.env.BASE_URL}${brandTheme.darkLogo.replace(
                  /^\//,
                  "",
                )}`
                : `${import.meta.env.BASE_URL}${brandTheme.logo.replace(
                  /^\//,
                  "",
                )}`
            }
            alt={brandTheme.brandName}
            className={styles.logoImg}
          />
          {/* ==================== 品牌主题结束 ==================== */}
        </div>
        <Space size="middle">
          {/* <ThemeToggleButton /> */}
          {canUseOpsMode && (
            <Switch
              checked={opsMode}
              checkedChildren="运维模式"
              unCheckedChildren="运维模式"
              onChange={handleOpsModeChange}
            />
          )}
          {canUseOpsMode && opsMode && (
            <Select
              allowClear
              value={userId ?? undefined}
              onChange={handleUserChange}
              loading={loading}
              showSearch
              optionFilterProp="label"
              style={{ minWidth: 180 }}
              placeholder="切换用户"
              options={userList.map((item) => ({
                label: item.tenant_id + "/" + item.tenant_name,
                value: item.tenant_id,
              }))}
            />
          )}
        </Space>
      </AntHeader>
    </>
  );
}
