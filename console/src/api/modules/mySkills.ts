import { request } from "../request";
import { mergeHeaders } from "../mergeHeaders";

export interface MySkill {
  skill_name: string;  // 目录名，用于 API 操作标识
  display_name: string;  // 展示名称
  source: string;
  description: string;
  version: string | null;
  received_version: string | null;
  distributed_by: string | null;
  is_received: boolean;
  has_update: boolean;
  enabled: boolean;
  category?: string;
  creator_name?: string;
  created_at?: string;  // 技能创建/接收时间
  updated_at?: string;  // 技能最后更新时间
  skill_id?: string;  // 唯一标识符
  cn_name?: string;  // 中文展示名
}

export interface FileTreeNode {
  name: string;
  type: "file" | "directory";
  path: string;
  children?: FileTreeNode[];
}

export interface FileContentResponse {
  content: string;
  file_type: string;
}

export interface BatchOperationResponse {
  results: Record<string, { success: boolean; reason?: string }>;
  success_count: number;
  failed_count: number;
}

export const mySkillsApi = {
  getCreatedSkills: async (): Promise<MySkill[]> => {
    const opts = mergeHeaders();
    const all = await request<MySkill[]>("/market/skills/mine", opts);
    return all.filter((s) => !s.is_received);
  },

  getReceivedSkills: async (): Promise<MySkill[]> => {
    const opts = mergeHeaders();
    const all = await request<MySkill[]>("/market/skills/received", opts);
    return all.filter((s) => s.is_received);
  },

  listSkillFiles: async (skillName: string): Promise<FileTreeNode[]> => {
    const opts = mergeHeaders();
    const encodedName = encodeURIComponent(skillName);
    return request<FileTreeNode[]>(
      `/market/skills/mine/${encodedName}/files`,
      opts
    );
  },

  readSkillFile: async (
    skillName: string,
    filePath: string
  ): Promise<FileContentResponse> => {
    const opts = mergeHeaders();
    const encodedName = encodeURIComponent(skillName);
    const encodedPath = filePath
      .split("/")
      .map((segment) => encodeURIComponent(segment))
      .join("/");
    return request<FileContentResponse>(
      `/market/skills/mine/${encodedName}/files/${encodedPath}`,
      opts
    );
  },

  saveSkillFile: async (
    skillName: string,
    filePath: string,
    content: string,
    cnName?: string
  ): Promise<void> => {
    const encodedName = encodeURIComponent(skillName);
    const encodedPath = filePath
      .split("/")
      .map((segment) => encodeURIComponent(segment))
      .join("/");
    const opts: RequestInit = {
      method: "PUT",
      ...(mergeHeaders({
        "Content-Type": "application/json",
      })),
      body: JSON.stringify({ content, cn_name: cnName }),
    };
    await request<void>(`/market/skills/mine/${encodedName}/files/${encodedPath}`, opts);
  },

  deleteSkill: async (skillName: string): Promise<void> => {
    const opts: RequestInit = {
      method: "DELETE",
      ...mergeHeaders(),
    };
    const encodedName = encodeURIComponent(skillName);
    await request<void>(`/market/skills/mine/${encodedName}`, opts);
  },

  enableSkill: async (skillName: string): Promise<void> => {
    const opts: RequestInit = {
      method: "POST",
      ...mergeHeaders(),
    };
    const encodedName = encodeURIComponent(skillName);
    await request<void>(`/market/skills/mine/${encodedName}/enable`, opts);
  },

  disableSkill: async (skillName: string): Promise<void> => {
    const opts: RequestInit = {
      method: "POST",
      ...mergeHeaders(),
    };
    const encodedName = encodeURIComponent(skillName);
    await request<void>(`/market/skills/mine/${encodedName}/disable`, opts);
  },

  batchDeleteSkills: async (
    skillNames: string[]
  ): Promise<BatchOperationResponse> => {
    const opts: RequestInit = {
      method: "POST",
      ...(mergeHeaders({
        "Content-Type": "application/json",
      })),
      body: JSON.stringify({ skills: skillNames }),
    };
    return request<BatchOperationResponse>(`/market/skills/mine/batch-delete`, opts);
  },

  batchEnableSkills: async (
    skillNames: string[]
  ): Promise<BatchOperationResponse> => {
    const opts: RequestInit = {
      method: "POST",
      ...(mergeHeaders({
        "Content-Type": "application/json",
      })),
      body: JSON.stringify({ skills: skillNames }),
    };
    return request<BatchOperationResponse>(`/market/skills/mine/batch-enable`, opts);
  },

  batchDisableSkills: async (
    skillNames: string[]
  ): Promise<BatchOperationResponse> => {
    const opts: RequestInit = {
      method: "POST",
      ...(mergeHeaders({
        "Content-Type": "application/json",
      })),
      body: JSON.stringify({ skills: skillNames }),
    };
    return request<BatchOperationResponse>(`/market/skills/mine/batch-disable`, opts);
  },
};
