# -*- coding: utf-8 -*-
"""Memory compaction hook for managing context window.

This hook monitors token usage and automatically compacts older messages
when the context window approaches its limit, preserving recent messages
and the system prompt.
"""

import logging
from typing import TYPE_CHECKING, Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock
from swe.constant import MEMORY_COMPACT_KEEP_RECENT

from ...app.source_system_config import resolve_tool_result_compact_config
from ..utils import (
    check_valid_messages,
    get_swe_token_counter,
)
from ...config.config import load_agent_config

if TYPE_CHECKING:
    from ..memory import BaseMemoryManager

logger = logging.getLogger(__name__)


class MemoryCompactionHook:
    """Hook for automatic memory compaction when context is full.

    This hook monitors the token count of messages and triggers compaction
    when it exceeds the threshold. It preserves the system prompt and recent
    messages while summarizing older conversation history.
    """

    def __init__(self, memory_manager: "BaseMemoryManager"):
        """Initialize memory compaction hook.

        Args:
            memory_manager: Memory manager instance for compaction
        """
        self.memory_manager = memory_manager

    @staticmethod
    async def _print_status_message(
        agent: ReActAgent,
        text: str,
    ) -> None:
        """Print a status message to the agent's output.

        Args:
            agent: The agent instance to print the message for.
            text: The text content of the status message.
        """
        msg = Msg(
            name=agent.name,
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )
        await agent.print(msg)

    async def _get_left_compact_threshold(
        self,
        agent: ReActAgent,
        running_config: Any,
        token_counter: Any,
    ) -> int | None:
        memory = agent.memory
        str_token_count = await token_counter.count(
            messages=[],
            text=(agent.sys_prompt or "")
            + (memory.get_compressed_summary() or ""),
        )
        left_compact_threshold = (
            running_config.memory_compact_threshold - str_token_count
        )
        if left_compact_threshold > 0:
            return left_compact_threshold

        logger.warning(
            "The memory_compact_threshold is set too low; "
            "the combined token length of system_prompt and "
            "compressed_summary exceeds the configured threshold. "
            "Alternatively, you could use /clear to reset the context "
            "and compressed_summary, ensuring the total remains "
            "below the threshold.",
        )
        return None

    async def _compact_tool_results_if_enabled(
        self,
        messages: list[Msg],
        running_config: Any,
    ) -> None:
        # source 显式覆盖只影响本请求，缺失字段继续继承 Agent 配置。
        trc = resolve_tool_result_compact_config(
            running_config.tool_result_compact,
        )
        if not trc.enabled:
            return

        await self.memory_manager.compact_tool_result(
            messages=messages,
            recent_n=trc.recent_n,
            old_max_bytes=trc.old_max_bytes,
            recent_max_bytes=trc.recent_max_bytes,
            retention_days=trc.retention_days,
        )

    @staticmethod
    def _compactable_messages_for_invalid_context(
        messages: list[Msg],
    ) -> list[Msg]:
        keep_length: int = MEMORY_COMPACT_KEEP_RECENT
        messages_length = len(messages)
        while keep_length > 0 and not check_valid_messages(
            messages[max(messages_length - keep_length, 0) :],
        ):
            keep_length -= 1

        if keep_length <= 0:
            return messages

        return messages[: max(messages_length - keep_length, 0)]

    async def _get_messages_to_compact(
        self,
        messages: list[Msg],
        running_config: Any,
        token_counter: Any,
        left_compact_threshold: int,
    ) -> list[Msg]:
        (
            messages_to_compact,
            _,
            is_valid,
        ) = await self.memory_manager.check_context(
            messages=messages,
            memory_compact_threshold=left_compact_threshold,
            memory_compact_reserve=running_config.memory_compact_reserve,
            as_token_counter=token_counter,
        )

        if is_valid or not messages_to_compact:
            return messages_to_compact

        logger.warning(
            "Please include the output of the /history command when "
            "reporting the bug to the community. Invalid messages=%s",
            messages,
        )
        return self._compactable_messages_for_invalid_context(messages)

    @staticmethod
    def _get_scope_id(agent: ReActAgent) -> str | None:
        scope_id = str(
            getattr(agent, "_request_context", {}).get(
                "session_id",
                "",
            )
            or "",
        )
        return scope_id or None

    def _add_summary_task_if_enabled(
        self,
        agent: ReActAgent,
        running_config: Any,
        messages_to_compact: list[Msg],
    ) -> None:
        if not running_config.memory_summary.memory_summary_enabled:
            return

        self.memory_manager.add_async_summary_task(
            messages=messages_to_compact,
            chat_model=agent.model,
            formatter=agent.formatter,
            scope_id=self._get_scope_id(agent),
        )

    async def _run_context_compaction(
        self,
        agent: ReActAgent,
        messages_to_compact: list[Msg],
        running_config: Any,
    ) -> str:
        if not running_config.context_compact.context_compact_enabled:
            await self._print_status_message(
                agent,
                "✅ Context compaction skipped",
            )
            return ""

        compact_content = await self.memory_manager.compact_memory(
            messages=messages_to_compact,
            previous_summary=agent.memory.get_compressed_summary(),
            _bound_chat_model=agent.model,
            _bound_formatter=agent.formatter,
        )
        await self._print_status_message(
            agent,
            (
                "✅ Context compaction completed"
                if compact_content
                else "⚠️ Context compaction failed."
            ),
        )
        return compact_content

    async def _persist_compaction_result(
        self,
        memory: Any,
        messages_to_compact: list[Msg],
        compact_content: str,
    ) -> None:
        updated_count = await memory.mark_messages_compressed(
            messages_to_compact,
        )
        logger.info("Marked %s messages as compacted", updated_count)
        await memory.update_compressed_summary(compact_content)

    async def __call__(
        self,
        agent: ReActAgent,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Pre-reasoning hook to check and compact memory if needed.

        This hook extracts system prompt messages and recent messages,
        builds an estimated full context prompt, and triggers compaction
        when the total estimated token count exceeds the threshold.

        Memory structure:
            [System Prompt (preserved)] + [Compactable (counted)] +
            [Recent (preserved)]

        Args:
            agent: The agent instance
            kwargs: Input arguments to the _reasoning method

        Returns:
            None (hook doesn't modify kwargs)
        """
        try:
            # Get hot-reloaded agent config
            agent_config = load_agent_config(
                self.memory_manager.agent_id,
                tenant_id=getattr(self.memory_manager, "tenant_id", None),
            )
            running_config = agent_config.running
            token_counter = get_swe_token_counter(agent_config)
            memory = agent.memory

            left_compact_threshold = await self._get_left_compact_threshold(
                agent,
                running_config,
                token_counter,
            )
            if left_compact_threshold is None:
                return None

            messages = await memory.get_memory(prepend_summary=False)
            await self._compact_tool_results_if_enabled(
                messages,
                running_config,
            )

            messages_to_compact = await self._get_messages_to_compact(
                messages,
                running_config,
                token_counter,
                left_compact_threshold,
            )
            if not messages_to_compact:
                return None

            self._add_summary_task_if_enabled(
                agent,
                running_config,
                messages_to_compact,
            )
            await self._print_status_message(
                agent,
                "🔄 Context compaction started...",
            )
            compact_content = await self._run_context_compaction(
                agent,
                messages_to_compact,
                running_config,
            )
            await self._persist_compaction_result(
                memory,
                messages_to_compact,
                compact_content,
            )

        except Exception as e:
            logger.exception(
                "Failed to compact memory in pre_reasoning hook: %s",
                e,
                exc_info=True,
            )

        return None
