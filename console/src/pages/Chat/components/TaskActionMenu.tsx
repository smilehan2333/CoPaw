import React, { useMemo, useState } from "react";
import { Dropdown, type MenuProps } from "antd";
import {
  CircleStop,
  Pencil,
  Play,
  MoreVertical,
  RotateCcw,
  Trash2,
} from "lucide-react";
import type { CronJobSpecOutput } from "@/api/types";
import type { TaskSidebarMeta } from "../taskJobs";
import Style from "./TaskActionMenuStyle";

export interface TaskActionMenuProps {
  task: CronJobSpecOutput;
  sidebarMeta: TaskSidebarMeta;
  classNamePrefix: string;
  onTaskPause?: (task: CronJobSpecOutput) => void;
  onTaskRun?: (task: CronJobSpecOutput) => void;
  onTaskResume?: (task: CronJobSpecOutput) => void;
  onTaskDelete?: (task: CronJobSpecOutput) => void;
  onTaskEdit?: (task: CronJobSpecOutput) => void;
}

function TaskActionLabel({
  icon,
  title,
  description,
  danger = false,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  danger?: boolean;
}) {
  return (
    <div
      className={`task-action-menu-label${
        danger ? " task-action-menu-label--danger" : ""
      }`}
    >
      <span className="task-action-menu-label-icon">{icon}</span>
      <span className="task-action-menu-label-copy">
        <span className="task-action-menu-label-title">{title}</span>
        <span className="task-action-menu-label-description">
          {description}
        </span>
      </span>
    </div>
  );
}

export default function TaskActionMenu({
  task,
  sidebarMeta,
  classNamePrefix,
  onTaskPause,
  onTaskRun,
  onTaskResume,
  onTaskDelete,
  onTaskEdit,
}: TaskActionMenuProps) {
  const [open, setOpen] = useState(false);
  const items = useMemo<MenuProps["items"]>(() => {
    const nextItems: NonNullable<MenuProps["items"]> = [];

    if (onTaskEdit && sidebarMeta.canEdit) {
      nextItems.push({
        key: "edit",
        label: (
          <TaskActionLabel
            icon={<Pencil size={15} />}
            title="编辑"
            description="调整任务配置"
          />
        ),
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation();
          onTaskEdit(task);
        },
      });
    }

    if (sidebarMeta.canPause) {
      nextItems.push({
        key: "pause",
        label: (
          <TaskActionLabel
            icon={<CircleStop size={15} />}
            title="停止"
            description="暂停后不再按计划执行"
          />
        ),
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation();
          onTaskPause?.(task);
        },
      });
    }

    if (sidebarMeta.canRun) {
      nextItems.push({
        key: "run",
        label: (
          <TaskActionLabel
            icon={<Play size={15} />}
            title="执行"
            description="立即触发一次任务"
          />
        ),
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation();
          onTaskRun?.(task);
        },
      });
    }

    if (sidebarMeta.canResume) {
      nextItems.push({
        key: "resume",
        label: (
          <TaskActionLabel
            icon={<RotateCcw size={15} />}
            title="恢复"
            description="恢复后继续定时执行"
          />
        ),
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation();
          onTaskResume?.(task);
        },
      });
    }

    if (sidebarMeta.canDelete) {
      if (nextItems.length > 0) {
        nextItems.push({ type: "divider" });
      }
      nextItems.push({
        key: "delete",
        label: (
          <TaskActionLabel
            icon={<Trash2 size={15} />}
            title="删除"
            description="永久删除此任务"
            danger
          />
        ),
        danger: true,
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation();
          onTaskDelete?.(task);
        },
      });
    }

    return nextItems;
  }, [
    onTaskDelete,
    onTaskEdit,
    onTaskPause,
    onTaskResume,
    onTaskRun,
    sidebarMeta.canEdit,
    sidebarMeta.canDelete,
    sidebarMeta.canPause,
    sidebarMeta.canResume,
    sidebarMeta.canRun,
    task,
  ]);

  if (!items?.length) {
    return null;
  }

  const taskName = task.name || task.id;

  return (
    <>
      <Style />
      <Dropdown
        open={open}
        onOpenChange={setOpen}
        menu={{ items }}
        placement="bottomRight"
        trigger={["click"]}
        overlayClassName={`task-action-menu-dropdown ${classNamePrefix}-action-dropdown`}
      >
        <button
          type="button"
          className={`${classNamePrefix}-action-trigger${
            open ? ` ${classNamePrefix}-action-trigger--open` : ""
          }`}
          aria-label={`更多任务操作：${taskName}`}
          onClick={(event) => {
            event.stopPropagation();
          }}
        >
          <MoreVertical size={16} strokeWidth={2.1} />
        </button>
      </Dropdown>
    </>
  );
}
