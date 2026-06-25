import type { CronJobSpecOutput } from "../../api/types";
import { formatListTime } from "./listTimeFormat.ts";

export interface TaskSidebarMeta {
  state: "active" | "running" | "auto-paused" | "manual-paused";
  unreadCount: number;
  canPause: boolean;
  canRun: boolean;
  canResume: boolean;
  canDelete: boolean;
  canEdit: boolean;
}

export interface TaskGroups {
  runnableTasks: CronJobSpecOutput[];
  pausedTasks: CronJobSpecOutput[];
}

const AUTO_PAUSE_REASON = "auto_unread_threshold";
export const TASK_COMPLETED_STATUS_TEXT = "已完成";

export function isVisibleTask(job: CronJobSpecOutput): boolean {
  return Boolean(job.task?.visible_in_my_tasks);
}

export function getTaskSidebarMeta(job: CronJobSpecOutput): TaskSidebarMeta {
  const unreadCount = Math.max(
    0,
    Number(job.task?.unread_execution_count || 0),
  );
  const pauseReason = job.task?.pause_reason;
  const isPaused = Boolean(job.task?.is_paused || pauseReason);
  const isRunning = Boolean(job.task?.is_running);

  if (isRunning) {
    return {
      state: "running",
      unreadCount,
      canPause: false,
      canRun: false,
      canResume: false,
      canDelete: false,
      canEdit: !job.enabled,
    };
  }

  if (pauseReason === AUTO_PAUSE_REASON) {
    return {
      state: "auto-paused",
      unreadCount,
      canPause: false,
      canRun: false,
      canResume: true,
      canDelete: !job.enabled,
      canEdit: !job.enabled,
    };
  }

  if (isPaused) {
    return {
      state: "manual-paused",
      unreadCount,
      canPause: false,
      canRun: false,
      canResume: true,
      canDelete: !job.enabled,
      canEdit: !job.enabled,
    };
  }

  return {
    state: "active",
    unreadCount,
    canPause: true,
    canRun: true,
    canResume: false,
    canDelete: !job.enabled,
    canEdit: !job.enabled,
  };
}

export function partitionTasksByPauseState(
  jobs: CronJobSpecOutput[],
): TaskGroups {
  return jobs.reduce<TaskGroups>(
    (groups, job) => {
      const state = getTaskSidebarMeta(job).state;
      if (state === "auto-paused" || state === "manual-paused") {
        groups.pausedTasks.push(job);
      } else {
        groups.runnableTasks.push(job);
      }
      return groups;
    },
    { runnableTasks: [], pausedTasks: [] },
  );
}

export function getTaskPauseStatusText(
  sidebarMeta: TaskSidebarMeta,
): string | null {
  if (sidebarMeta.state === "auto-paused") {
    if (sidebarMeta.unreadCount <= 0) {
      return "已自动暂停 · 已清理";
    }
    return `已自动暂停 · 连续 ${sidebarMeta.unreadCount} 次未读`;
  }
  if (sidebarMeta.state === "manual-paused") {
    return "已手动暂停";
  }
  return null;
}

export function shouldMarkTaskReadOnOpen(job: CronJobSpecOutput): boolean {
  return !getTaskSidebarMeta(job).canResume;
}

export function getTaskNextRunText(job: CronJobSpecOutput): string | null {
  const sidebarMeta = getTaskSidebarMeta(job);
  if (sidebarMeta.state === "running") {
    return "运行中...";
  }

  if (sidebarMeta.canResume) {
    return null;
  }

  const formatted = formatListTime(job.state?.next_run_at);
  if (!formatted) {
    return null;
  }

  return `下次运行：${formatted}`;
}

export function getTaskNextRunTooltipText(
  job: CronJobSpecOutput,
): string | undefined {
  const runTimes = getTaskNextRunTooltipTimes(job);

  if (runTimes.length === 0) {
    return undefined;
  }

  return ["之后三次运行时间", ...runTimes].join("\n");
}

export function getTaskNextRunTooltipTimes(job: CronJobSpecOutput): string[] {
  const runTimes = (job.state?.next_run_times || [])
    .map(formatListTime)
    .filter(Boolean)
    .slice(0, 3);

  if (runTimes.length === 0) {
    const nextRun = formatListTime(job.state?.next_run_at);
    if (nextRun) {
      runTimes.push(nextRun);
    }
  }

  return runTimes;
}

export function getTaskOpenTarget(job: CronJobSpecOutput): string | null {
  const normalize = (value: string | null | undefined): string | null => {
    const text = String(value || "").trim();
    return text || null;
  };

  return (
    normalize(job.task?.chat_id) ||
    normalize(job.task?.session_id) ||
    normalize(job.request?.session_id as string | null | undefined) ||
    normalize(job.dispatch?.target?.session_id)
  );
}

export function deriveChatTaskState(
  jobs: CronJobSpecOutput[],
  chatId: string | undefined,
): {
  tasks: CronJobSpecOutput[];
  currentTask: CronJobSpecOutput | null;
} {
  return {
    tasks: jobs.filter(isVisibleTask),
    currentTask: chatId
      ? jobs.find((job) => job.task?.chat_id === chatId) || null
      : null,
  };
}
