import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Modal } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BackupFiles from "./BackupFiles";

const mocks = vi.hoisted(() => ({
  dreamLogsApi: {
    listBackups: vi.fn(),
    deleteAllBackups: vi.fn(),
    deleteBackup: vi.fn(),
    getBackupContent: vi.fn(),
    rollback: vi.fn(),
  },
}));

vi.mock("../../../../api/modules/dreamLogs", () => ({
  dreamLogsApi: mocks.dreamLogsApi,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? key,
  }),
}));

describe("BackupFiles", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.dreamLogsApi.listBackups.mockResolvedValue({
      total_files: 2,
      total_size: 300,
      files: [
        {
          filename: "memory_backup_20260526.md",
          original_file: "MEMORY.md",
          record_id: "record-1",
          timestamp: "2026-05-26T10:00:00",
          size: 100,
          created_at: "2026-05-26T10:00:01",
        },
        {
          filename: "agents_backup_20260526.md",
          original_file: "AGENTS.md",
          record_id: "record-1",
          timestamp: "2026-05-26T10:00:00",
          size: 200,
          created_at: "2026-05-26T10:00:02",
        },
      ],
    });
    mocks.dreamLogsApi.rollback.mockResolvedValue({
      success: true,
      message: "ok",
      files_rolled_back: [],
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("groups backup files under their governance task and expands files", async () => {
    render(<BackupFiles />);

    expect(await screen.findByText("治理任务 record-1")).toBeInTheDocument();
    expect(screen.getByText("2 个备份文件")).toBeInTheDocument();
    expect(
      screen.queryByText("memory_backup_20260526.md"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("展开治理任务 record-1"));

    expect(
      await screen.findByText("memory_backup_20260526.md"),
    ).toBeInTheDocument();
    expect(screen.getByText("agents_backup_20260526.md")).toBeInTheDocument();
  });

  it("supports task rollback and single-file rollback", async () => {
    vi.spyOn(Modal, "confirm").mockImplementation((config) => {
      void config.onOk?.();
      return { destroy: vi.fn(), update: vi.fn() };
    });

    render(<BackupFiles />);

    await screen.findByText("治理任务 record-1");
    fireEvent.click(screen.getByLabelText("按任务回退 record-1"));

    await waitFor(() => {
      expect(mocks.dreamLogsApi.rollback).toHaveBeenCalledWith("record-1");
    });

    fireEvent.click(screen.getByLabelText("展开治理任务 record-1"));
    fireEvent.click(await screen.findByLabelText("回退 MEMORY.md"));

    await waitFor(() => {
      expect(mocks.dreamLogsApi.rollback).toHaveBeenCalledWith("record-1", [
        "MEMORY.md",
      ]);
    });
  });
});
