import type { IDataContent, IAgentScopeRuntimeMessage } from "../types";
import { AgentScopeRuntimeMessageType } from "../types";

export function getToolMessageKey(data: {
  call_id?: string;
  id?: string;
  tool_call_id?: string;
  name?: string;
  tool_name?: string;
  tool?: string;
  mcp_tool_name?: string;
}) {
  return (
    data.call_id ||
    data.id ||
    data.tool_call_id ||
    data.name ||
    data.tool_name ||
    data.tool ||
    data.mcp_tool_name
  );
}

export function maybeToolOutput(message: IAgentScopeRuntimeMessage) {
  return [
    AgentScopeRuntimeMessageType.FUNCTION_CALL_OUTPUT,
    AgentScopeRuntimeMessageType.PLUGIN_CALL_OUTPUT,
    AgentScopeRuntimeMessageType.COMPONENT_CALL_OUTPUT,
    AgentScopeRuntimeMessageType.MCP_CALL_OUTPUT,
  ].includes(message.type);
}

export function maybeToolInput(message: IAgentScopeRuntimeMessage) {
  return [
    AgentScopeRuntimeMessageType.FUNCTION_CALL,
    AgentScopeRuntimeMessageType.PLUGIN_CALL,
    AgentScopeRuntimeMessageType.COMPONENT_CALL,
    AgentScopeRuntimeMessageType.MCP_CALL,
  ].includes(message.type);
}

export function mergeToolMessages(messages: IAgentScopeRuntimeMessage[]) {
  const bufferMessagesMap = new Map<string, IDataContent>();
  let resMessages: IAgentScopeRuntimeMessage[] = [];

  for (const message of messages) {
    if (maybeToolInput(message) && message.content?.length) {
      const content = message.content[0] as IDataContent;
      const key = getToolMessageKey(content.data);
      if (key) {
        bufferMessagesMap.set(key, content);
      }
      resMessages.push(message);
    } else if (maybeToolOutput(message) && message.content?.length) {
      const content = message.content[0] as IDataContent;
      const key = getToolMessageKey(content.data);
      const bufferContent = key ? bufferMessagesMap.get(key) : undefined;

      if (bufferContent) {
        resMessages = resMessages.map((item) => {
          if (!maybeToolInput(item)) return item;
          const preContent = item.content[0] as IDataContent;
          const preKey = getToolMessageKey(preContent.data);

          if (preKey === key) {
            return { ...message, content: [...item.content, content] };
          }
          return item;
        });
      } else {
        resMessages.push(message);
      }
    } else {
      resMessages.push(message);
    }
  }

  return resMessages;
}
