# Source User Version Display Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Always show a real source user version in version history, even when it numerically equals the marketplace version ID.

**Architecture:** Update frontend display helpers for Skill and MCP version history. Keep backend API and stored data unchanged; only remove the UI rule that treats `source_user_version === version_id` as duplicate information.

**Tech Stack:** React, TypeScript, Vite, Ant Design, existing version history modal components.

---

## File Structure

- Modify: `console/src/pages/Market/Skills/VersionHistoryModal.tsx`
  - Update `describeSource()` to hide only empty source versions and admin zip sentinel `v0.0.0`.
  - Update the comment to reflect that marketplace version and source user version are independent.
- Modify: `console/src/pages/Market/components/MCPVersionHistoryModal.tsx`
  - Apply the same display rule for MCP version history.

---

### Task 1: Update source user version display rules

**Files:**
- Modify: `console/src/pages/Market/Skills/VersionHistoryModal.tsx`
- Modify: `console/src/pages/Market/components/MCPVersionHistoryModal.tsx`

- [ ] **Step 1: Update Skill version history helper**

In `console/src/pages/Market/Skills/VersionHistoryModal.tsx`, replace:

```ts
/**
 * 把 SkillVersion 上的 source_user_* 拼成单行描述，避免与头部 version_id 重复。
 *
 * 规则（仅展示"用户同步版本"）：
 * - 无 source_user_version 或 = "v0.0.0"（admin zip 路径） → 不显示
 * - source_user_version == 市场 version_id → 不显示（信息重复）
 * - 否则 → "用户同步版本 vX.Y.Z"
 */
function describeSource(version: SkillVersion): string | null {
  const userVersion = version.source_user_version?.trim();
  if (!userVersion || userVersion === "v0.0.0") return null;
  if (userVersion === version.version_id) return null;
  return `用户同步版本 ${displayVersion(userVersion)}`;
}
```

with:

```ts
/**
 * 把 SkillVersion 上的 source_user_version 拼成单行描述。
 *
 * 市场版本和用户同步版本是独立语义，即使数值相同也展示用户同步版本。
 * 规则（仅展示"用户同步版本"）：
 * - 无 source_user_version 或 = "v0.0.0"（admin zip 路径） → 不显示
 * - 否则 → "用户同步版本 vX.Y.Z"
 */
function describeSource(version: SkillVersion): string | null {
  const userVersion = version.source_user_version?.trim();
  if (!userVersion || userVersion === "v0.0.0") return null;
  return `用户同步版本 ${displayVersion(userVersion)}`;
}
```

- [ ] **Step 2: Update MCP version history helper**

In `console/src/pages/Market/components/MCPVersionHistoryModal.tsx`, replace:

```ts
/**
 * 把 source_user_* 拼成单行描述，避免与头部 created_by + version_id 重复。
 *
 * 规则（仅展示"用户同步版本"）：
 * - 无 source_user_version 或 = "v0.0.0"（admin zip 路径） → 不显示
 * - source_user_version == 市场 version_id → 不显示（信息重复）
 * - 否则 → "用户同步版本 vX.Y.Z"
 */
function describeSource(version: MCPVersion): string | null {
  const userVersion = version.source_user_version?.trim();
  if (!userVersion || userVersion === "v0.0.0") return null;
  if (userVersion === version.version_id) return null;
  return `用户同步版本 ${displayVersion(userVersion)}`;
}
```

with:

```ts
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
```

- [ ] **Step 3: Run frontend type/build verification**

Run:

```bash
cd console && pnpm build
```

Expected: TypeScript build and Vite build complete successfully.

If dependencies are unavailable, report the exact error and do not mark verification as passed.

## Self-Review Notes

- Spec coverage: The plan implements the requested display rule and applies it to both Skill and MCP history components.
- Placeholder scan: No TBD/TODO placeholders.
- Type consistency: The plan uses existing `SkillVersion`, `MCPVersion`, `source_user_version`, and `version_id` fields.
