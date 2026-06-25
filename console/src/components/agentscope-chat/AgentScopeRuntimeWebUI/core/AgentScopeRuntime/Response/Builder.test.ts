import { describe, expect, it, vi } from "vitest";
import AgentScopeRuntimeResponseBuilder from "./Builder";
import { mergeToolMessages } from "./ToolMessageMerge";
import {
  AgentScopeRuntimeContentType,
  type IDataContent,
  AgentScopeRuntimeMessageType,
  AgentScopeRuntimeRunStatus,
} from "../types";

vi.mock("@/components/agentscope-chat", () => ({
  uuid: () => "test-uuid",
}));

describe("AgentScopeRuntimeResponseBuilder tool merge", () => {
  it("merges MCP tool calls using tool_name and tool_call_id aliases", () => {
    const messages = mergeToolMessages([
      {
        id: "call-message",
        object: "message",
        role: "assistant",
        type: AgentScopeRuntimeMessageType.MCP_CALL,
        status: AgentScopeRuntimeRunStatus.Completed,
        content: [
          {
            type: AgentScopeRuntimeContentType.DATA,
            status: AgentScopeRuntimeRunStatus.Completed,
            data: {
              tool_call_id: "mcp-call-1",
              tool_name: "fetch_customer_profile",
              arguments: "{}",
            },
          },
        ],
      },
      {
        id: "output-message",
        object: "message",
        role: "tool",
        type: AgentScopeRuntimeMessageType.MCP_CALL_OUTPUT,
        status: AgentScopeRuntimeRunStatus.Completed,
        content: [
          {
            type: AgentScopeRuntimeContentType.DATA,
            status: AgentScopeRuntimeRunStatus.Completed,
            data: {
              tool_call_id: "mcp-call-1",
              tool_name: "fetch_customer_profile",
              output: "[]",
            },
          },
        ],
      },
    ]);

    expect(messages).toHaveLength(1);
    expect(messages[0].content).toHaveLength(2);
    expect((messages[0].content[0] as IDataContent).data.tool_name).toBe(
      "fetch_customer_profile",
    );
    expect((messages[0].content[1] as IDataContent).data.output).toBe("[]");
  });

  it("keeps unmatched MCP output messages visible", () => {
    const messages = mergeToolMessages([
      {
        id: "output-message",
        object: "message",
        role: "tool",
        type: AgentScopeRuntimeMessageType.MCP_CALL_OUTPUT,
        status: AgentScopeRuntimeRunStatus.Completed,
        content: [
          {
            type: AgentScopeRuntimeContentType.DATA,
            status: AgentScopeRuntimeRunStatus.Completed,
            data: {
              tool_name: "fetch_customer_profile",
              output: "[]",
            },
          },
        ],
      },
    ]);

    expect(messages).toHaveLength(1);
    expect((messages[0].content[0] as IDataContent).data.tool_name).toBe(
      "fetch_customer_profile",
    );
  });
});

describe("AgentScopeRuntimeResponseBuilder tool output frames", () => {
  it("attaches live output frames to the matching running tool call", () => {
    const builder = new AgentScopeRuntimeResponseBuilder({
      id: "response-1",
      status: AgentScopeRuntimeRunStatus.InProgress,
      created_at: 1,
    });

    builder.handle({
      id: "call-message",
      object: "message",
      role: "assistant",
      type: AgentScopeRuntimeMessageType.PLUGIN_CALL,
      status: AgentScopeRuntimeRunStatus.InProgress,
      content: [
        {
          type: AgentScopeRuntimeContentType.DATA,
          status: AgentScopeRuntimeRunStatus.InProgress,
          data: {
            call_id: "call-1",
            name: "execute_shell_command",
            arguments: '{"command":"pnpm test"}',
          },
        },
      ],
    });

    builder.handle({
      object: "tool_output_frame",
      tool_call_id: "call-1",
      tool_name: "execute_shell_command",
      sequence: 1,
      source: "stdout",
      text: "running tests\n",
      truncated: false,
    } as never);

    const data = builder.data.output[0].content[0] as IDataContent;
    expect(data.data.live_output).toBe("running tests\n");
    expect(data.data.live_output_truncated).toBe(false);
  });

  it("keeps final tool output authoritative after live frames", () => {
    const builder = new AgentScopeRuntimeResponseBuilder({
      id: "response-1",
      status: AgentScopeRuntimeRunStatus.InProgress,
      created_at: 1,
    });

    builder.handle({
      id: "call-message",
      object: "message",
      role: "assistant",
      type: AgentScopeRuntimeMessageType.PLUGIN_CALL,
      status: AgentScopeRuntimeRunStatus.InProgress,
      content: [
        {
          type: AgentScopeRuntimeContentType.DATA,
          status: AgentScopeRuntimeRunStatus.InProgress,
          data: {
            call_id: "call-1",
            name: "execute_shell_command",
            arguments: '{"command":"pnpm test"}',
          },
        },
      ],
    });
    builder.handle({
      object: "tool_output_frame",
      tool_call_id: "call-1",
      tool_name: "execute_shell_command",
      sequence: 1,
      source: "stdout",
      text: "partial\n",
      truncated: false,
    } as never);
    builder.handle({
      id: "output-message",
      object: "message",
      role: "tool",
      type: AgentScopeRuntimeMessageType.PLUGIN_CALL_OUTPUT,
      status: AgentScopeRuntimeRunStatus.Completed,
      content: [
        {
          type: AgentScopeRuntimeContentType.DATA,
          status: AgentScopeRuntimeRunStatus.Completed,
          data: {
            call_id: "call-1",
            name: "execute_shell_command",
            output: "final output\n",
          },
        },
      ],
    });

    const merged = mergeToolMessages(builder.data.output);
    expect((merged[0].content[0] as IDataContent).data.live_output).toBe(
      "partial\n",
    );
    expect((merged[0].content[1] as IDataContent).data.output).toBe(
      "final output\n",
    );
  });
});
