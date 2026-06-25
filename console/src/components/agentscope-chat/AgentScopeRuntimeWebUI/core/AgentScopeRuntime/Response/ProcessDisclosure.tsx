import { useId, useState } from "react";
import type { ReactNode } from "react";
import {
  SparkDownLine,
  SparkTimeLine,
  SparkTodoListLine,
  SparkToolLine,
  SparkUpLine,
} from "@agentscope-ai/icons";
import { useProviderContext } from "@/components/agentscope-chat";
import Style from "./style";

export interface ProcessDisclosureProps {
  children: ReactNode;
  defaultOpen?: boolean;
  durationText?: string;
  failedCount?: number;
  processCount: number;
  status?: "completed" | "running" | "canceled";
  toolCallCount?: number;
}

function buildStatusText(props: {
  failedCount: number;
  status: ProcessDisclosureProps["status"];
}) {
  if (props.status === "running") return "正在执行";
  if (props.failedCount > 0) return `操作失败 ${props.failedCount} 次`;
  if (props.status === "canceled") return "已取消";
  return null;
}

function getStatusTone(props: {
  failedCount: number;
  status: ProcessDisclosureProps["status"];
}) {
  if (props.failedCount > 0) return "failed";
  if (props.status === "running") return "running";
  if (props.status === "canceled") return "canceled";
  return "completed";
}

export default function ProcessDisclosure({
  children,
  defaultOpen = false,
  durationText,
  failedCount = 0,
  processCount,
  status = "completed",
  toolCallCount = 0,
}: ProcessDisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();
  const { getPrefixCls } = useProviderContext();
  const prefixCls = getPrefixCls("response-process-disclosure");
  const statusText = buildStatusText({ failedCount, status });
  const statusTone = getStatusTone({ failedCount, status });
  const stepText =
    status === "running"
      ? "过程记录"
      : processCount > 0
        ? `${processCount} 个步骤`
        : null;
  const titleText = open ? "执行过程" : "执行过程已折叠";
  const labelParts = ["执行过程"];
  if (stepText) labelParts.push(stepText);
  if (toolCallCount > 0) labelParts.push(`工具调用 ${toolCallCount} 次`);
  if (durationText) labelParts.push(`总耗时 ${durationText}`);
  if (statusText) labelParts.push(statusText);
  const label = labelParts.join(" · ");

  return (
    <>
      <Style />
      <div className={prefixCls}>
        <button
          type="button"
          className={`${prefixCls}-trigger`}
          aria-expanded={open}
          aria-controls={contentId}
          aria-label={`${open ? "收起" : "展开"}${label}`}
          data-status={statusTone}
          onClick={() => setOpen((current) => !current)}
        >
          <span className={`${prefixCls}-copy`}>
            <span className={`${prefixCls}-title`}>{titleText}</span>
            <span className={`${prefixCls}-meta`}>
              {stepText ? (
                <span className={`${prefixCls}-metric`}>
                  <SparkTodoListLine aria-hidden="true" />
                  {stepText}
                </span>
              ) : null}
              {toolCallCount > 0 ? (
                <span className={`${prefixCls}-metric`}>
                  <SparkToolLine aria-hidden="true" />
                  工具调用 {toolCallCount} 次
                </span>
              ) : null}
              {durationText ? (
                <span className={`${prefixCls}-metric`}>
                  <SparkTimeLine aria-hidden="true" />
                  总耗时 {durationText}
                </span>
              ) : null}
              {statusText ? (
                <span className={`${prefixCls}-status`}>{statusText}</span>
              ) : null}
            </span>
          </span>
          <span className={`${prefixCls}-action`}>
            {open ? "收起详情" : "展开详情"}
          </span>
          <span className={`${prefixCls}-chevron`} aria-hidden="true">
            {open ? <SparkUpLine /> : <SparkDownLine />}
          </span>
        </button>
        <div
          id={contentId}
          className={`${prefixCls}-body ${
            open ? `${prefixCls}-body-open` : ""
          }`}
          hidden={!open}
        >
          {children}
        </div>
      </div>
    </>
  );
}
