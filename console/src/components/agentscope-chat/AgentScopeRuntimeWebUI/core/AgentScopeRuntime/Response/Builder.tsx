import { produce } from "immer";
import {
  IAgentScopeRuntimeResponse,
  AgentScopeRuntimeRunStatus,
  IAgentScopeRuntimeMessage,
  IContent,
  AgentScopeRuntimeContentType,
  ITextContent,
  IImageContent,
  IDataContent,
  AgentScopeRuntimeMessageType,
} from "../types";
import { uuid } from "@/components/agentscope-chat";
import {
  getToolMessageKey,
  maybeToolInput,
  maybeToolOutput,
  mergeToolMessages,
} from "./ToolMessageMerge";

const LIVE_TOOL_OUTPUT_MAX_BYTES = 64 * 1024;
const LIVE_TOOL_OUTPUT_MAX_LINES = 2000;
const LIVE_TOOL_OUTPUT_OMISSION_TEXT = "\n[早期实时输出已省略]\n";

interface IToolOutputFrame {
  object: "tool_output_frame";
  tool_call_id: string;
  tool_name?: string;
  sequence: number;
  source: "stdout" | "stderr" | "message";
  text: string;
  truncated?: boolean;
}

function trimLiveToolOutput(text: string) {
  const encoded = new TextEncoder().encode(text);
  let next = text;
  let truncated = false;

  if (encoded.length > LIVE_TOOL_OUTPUT_MAX_BYTES) {
    const start = Math.max(0, encoded.length - LIVE_TOOL_OUTPUT_MAX_BYTES);
    next = new TextDecoder().decode(encoded.slice(start));
    truncated = true;
  }

  const lines = next.split(/(?<=\n)/);
  if (lines.length > LIVE_TOOL_OUTPUT_MAX_LINES) {
    next = lines.slice(-LIVE_TOOL_OUTPUT_MAX_LINES).join("");
    truncated = true;
  }

  if (truncated && !next.startsWith(LIVE_TOOL_OUTPUT_OMISSION_TEXT)) {
    next = `${LIVE_TOOL_OUTPUT_OMISSION_TEXT}${next}`;
  }

  return {
    text: next,
    truncated,
  };
}

class AgentScopeRuntimeResponseBuilder {
  static mergeToolMessages(messages: IAgentScopeRuntimeMessage[]) {
    return mergeToolMessages(messages);
  }

  static maybeToolOutput(message: IAgentScopeRuntimeMessage) {
    return maybeToolOutput(message);
  }

  static maybeToolInput(message: IAgentScopeRuntimeMessage) {
    return maybeToolInput(message);
  }

  static maybeGenerating(data: { status: AgentScopeRuntimeRunStatus }) {
    return [
      AgentScopeRuntimeRunStatus.InProgress,
      AgentScopeRuntimeRunStatus.Created,
    ].includes(data.status);
  }

  static maybeDone(data: { status: AgentScopeRuntimeRunStatus }) {
    return [
      AgentScopeRuntimeRunStatus.Completed,
      AgentScopeRuntimeRunStatus.Canceled,
      AgentScopeRuntimeRunStatus.Failed,
    ].includes(data.status);
  }

  data: IAgentScopeRuntimeResponse;

  constructor({
    id,
    status,
    created_at,
  }: Pick<IAgentScopeRuntimeResponse, "id" | "status" | "created_at">) {
    this.data = {
      id: id,
      output: [],
      object: "response",
      status: status || AgentScopeRuntimeRunStatus.Created,
      created_at: created_at || Date.now(),
    };
  }

  handleResponse(data: IAgentScopeRuntimeResponse) {
    this.data = produce(this.data, (draft) => {
      const nextOutput = Array.isArray(data.output) ? data.output : [];

      // Terminal response frames may carry only status/completed_at without
      // repeating output. Preserve the latest rendered output in that case.
      if (nextOutput.length === 0 && draft.output.length > 0) {
        const rest = { ...data };
        delete rest.output;
        Object.assign(draft, rest);
        return;
      }

      if (!data.output) {
        data.output = [];
      }

      Object.assign(draft, data);
    });
  }

  handleMessage(data: IAgentScopeRuntimeMessage) {
    this.data = produce(this.data, (draft) => {
      if (!draft.output) {
        draft.output = [];
      }

      const existingIndex = draft.output.findIndex((msg) => msg.id === data.id);

      if (existingIndex >= 0) {
        const existingContent = draft.output[existingIndex].content;
        Object.assign(draft.output[existingIndex], data);
        if (!data.content || data.content.length === 0) {
          draft.output[existingIndex].content = existingContent;
        }
      } else {
        draft.output.push(data);
      }
    });
  }

  handleContent(data: IContent) {
    this.data = produce(this.data, (draft) => {
      const msg = draft.output.find((m) => m.id === data.msg_id);

      if (!msg) {
        console.warn("Message not found for content:", data.msg_id);
        return;
      }

      if (!msg.content) {
        msg.content = [];
      }

      if (data.delta) {
        const lastContent = msg.content[msg.content.length - 1];

        if (lastContent && lastContent.delta) {
          if (
            data.type === AgentScopeRuntimeContentType.TEXT &&
            lastContent.type === AgentScopeRuntimeContentType.TEXT
          ) {
            (lastContent as ITextContent).text += (data as ITextContent).text;
          } else if (data.type === AgentScopeRuntimeContentType.IMAGE) {
            (lastContent as IImageContent).image_url = (
              data as IImageContent
            ).image_url;
          } else if (data.type === AgentScopeRuntimeContentType.DATA) {
            (lastContent as IDataContent).data = (data as IDataContent).data;
          }
        } else {
          msg.content.push(data);
        }
      } else {
        if (msg.content.length > 0) {
          Object.assign(msg.content[msg.content.length - 1], data);
        } else {
          msg.content.push(data);
        }
      }
    });
  }

  handleToolOutputFrame(data: IToolOutputFrame) {
    this.data = produce(this.data, (draft) => {
      const message = draft.output.find((item) => {
        if (!maybeToolInput(item) || !item.content?.length) return false;
        const content = item.content[0] as IDataContent;
        return getToolMessageKey(content.data) === data.tool_call_id;
      });

      if (!message?.content?.length) {
        return;
      }

      const content = message.content[0] as IDataContent<Record<string, any>>;
      const currentText =
        typeof content.data.live_output === "string"
          ? content.data.live_output
          : "";
      const trimmed = trimLiveToolOutput(`${currentText}${data.text}`);
      content.data.live_output = trimmed.text;
      content.data.live_output_truncated =
        Boolean(content.data.live_output_truncated) ||
        Boolean(data.truncated) ||
        trimmed.truncated;
      content.data.live_output_frames = [
        ...(Array.isArray(content.data.live_output_frames)
          ? content.data.live_output_frames
          : []),
        {
          sequence: data.sequence,
          source: data.source,
          text: data.text,
          truncated: Boolean(data.truncated),
        },
      ].slice(-LIVE_TOOL_OUTPUT_MAX_LINES);
    });
  }

  handleError(data: IAgentScopeRuntimeMessage) {
    this.data = produce(this.data, (draft) => {
      draft.status = AgentScopeRuntimeRunStatus.Failed;

      draft.output.push({
        status: AgentScopeRuntimeRunStatus.Failed,
        type: AgentScopeRuntimeMessageType.ERROR,
        content: [],
        id: uuid(),
        role: "assistant",
        code: data.code,
        message:
          typeof data.message === "string"
            ? data.message
            : JSON.stringify(data.message),
      });
    });
  }

  handle(
    data:
      | IAgentScopeRuntimeResponse
      | IAgentScopeRuntimeMessage
      | IContent
      | IToolOutputFrame,
  ) {
    if (data.object === "response") {
      this.handleResponse(data);
    } else if (data.object === "message") {
      if (data.type === AgentScopeRuntimeMessageType.HEARTBEAT)
        return this.data;
      this.handleMessage(data);
    } else if (data.object === "content") {
      this.handleContent(data);
    } else if (data.object === "tool_output_frame") {
      this.handleToolOutputFrame(data);
    } else {
      this.handleError(data);
    }

    return this.data;
  }

  cancel() {
    this.data = produce(this.data, (draft) => {
      if (AgentScopeRuntimeResponseBuilder.maybeGenerating(draft)) {
        draft.status = AgentScopeRuntimeRunStatus.Canceled;
      }
      draft.output.forEach((msg) => {
        if (AgentScopeRuntimeResponseBuilder.maybeGenerating(msg)) {
          msg.status = AgentScopeRuntimeRunStatus.Canceled;
          msg.content.forEach((content) => {
            if (AgentScopeRuntimeResponseBuilder.maybeGenerating(content)) {
              content.status = AgentScopeRuntimeRunStatus.Canceled;
            }
          });
        }
      });
    });

    return this.data;
  }
}

export default AgentScopeRuntimeResponseBuilder;
