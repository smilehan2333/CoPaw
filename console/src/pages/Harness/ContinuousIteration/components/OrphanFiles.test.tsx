import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OrphanFilesPage from "./OrphanFiles";

const mocks = vi.hoisted(() => ({
  dreamLogsApi: {
    archiveOrphanFiles: vi.fn(),
    autoArchiveOrphanFiles: vi.fn(),
    deleteOrphanFile: vi.fn(),
    getOrphanFileContent: vi.fn(),
    listOrphanFiles: vi.fn(),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "common.actions": "操作",
        "dreamLogs.orphanFiles.createdAt": "创建时间",
        "dreamLogs.orphanFiles.filePath": "文件路径",
        "dreamLogs.orphanFiles.filename": "文件名",
        "dreamLogs.orphanFiles.modifiedAt": "修改时间",
        "dreamLogs.orphanFiles.noFiles": "暂无临时文件",
        "dreamLogs.orphanFiles.previewFailed": "预览失败",
        "dreamLogs.orphanFiles.previewTitle": "文件预览",
        "dreamLogs.orphanFiles.size": "大小",
        "dreamLogs.orphanFiles.title": "用户临时文件",
        "dreamLogs.orphanFiles.totalFiles": "文件数",
        "dreamLogs.orphanFiles.totalSize": "总大小",
        "dreamLogs.orphanFiles.workspaceDir": "工作目录",
      })[key] || key,
  }),
}));

vi.mock("../../../../api/modules/dreamLogs", () => ({
  dreamLogsApi: mocks.dreamLogsApi,
}));

describe("OrphanFilesPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.dreamLogsApi.listOrphanFiles.mockResolvedValue({
      workspace_dir: "/workspace/alice",
      total_files: 1,
      total_size: 128,
      files: [
        {
          filename: "tmp.md",
          path: "memory/tmp.md",
          full_path: "/workspace/alice/memory/tmp.md",
          size: 128,
          created_at: "2026-06-01T10:00:00Z",
          modified_at: "2026-06-02T10:00:00Z",
        },
      ],
    });
  });

  it("offers view and archive actions without a delete action", async () => {
    render(<OrphanFilesPage />);

    const pathText = await screen.findByText("memory/tmp.md");
    const row = pathText.closest("tr");
    expect(row).not.toBeNull();

    const actionCell = row?.querySelector(".ant-table-cell-fix-right");
    expect(actionCell).not.toBeNull();
    const actions = within(actionCell as HTMLElement);
    expect(actions.getByRole("button", { name: "查看 memory/tmp.md" }))
      .toBeInTheDocument();
    expect(actions.getByRole("button", { name: "归档 memory/tmp.md" }))
      .toBeInTheDocument();
    expect(actions.queryByRole("button", { name: "删除 memory/tmp.md" }))
      .not.toBeInTheDocument();
    expect(actions.getAllByRole("button")).toHaveLength(2);
    expect(mocks.dreamLogsApi.deleteOrphanFile).not.toHaveBeenCalled();
  });
});
