# -*- coding: utf-8 -*-
"""Skill invocation detector for detecting skill boundaries.

This module provides the SkillInvocationDetector which detects when tool
calls belong to skill execution flows, manages skill execution boundaries,
and resolves multi-skill attribution conflicts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from inspect import isawaitable
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

from .skill_context_manager import (
    SkillContextManager,
    get_skill_context_manager,
)
from .skill_feature_inferencer import (
    SkillFeatureInferencer,
    get_skill_feature_inferencer,
)
from .skill_tool_registry import SkillToolRegistry, get_skill_tool_registry

if TYPE_CHECKING:
    from ..tracing.manager import TraceManager

logger = logging.getLogger(__name__)

# 技能描述缓存
_SKILL_DESCRIPTION_CACHE: dict[str, str] = {}


def _get_skill_description(skill_name: str) -> str:
    """从技能目录读取技能描述（fallback 方式）.

    从内置技能目录的 SKILL.md 文件中读取 description 字段。
    主要用于内置技能的描述获取。

    Args:
        skill_name: 技能名称

    Returns:
        技能描述字符串，如果未找到则返回空字符串
    """
    # 检查缓存
    if skill_name in _SKILL_DESCRIPTION_CACHE:
        return _SKILL_DESCRIPTION_CACHE[skill_name]

    description = ""

    # 尝试从内置技能目录读取
    try:
        from .skills_manager import get_builtin_skills_dir

        builtin_dir = get_builtin_skills_dir()
        skill_md_path = builtin_dir / skill_name / "SKILL.md"
        if skill_md_path.exists():
            description = _parse_skill_description(skill_md_path)
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"Failed to read builtin skill description: {e}")

    # 缓存结果
    _SKILL_DESCRIPTION_CACHE[skill_name] = description
    return description


def _parse_skill_description(skill_md_path: Path) -> str:
    """解析 SKILL.md 文件获取描述字段.

    Args:
        skill_md_path: SKILL.md 文件路径

    Returns:
        技能描述字符串
    """
    try:
        content = skill_md_path.read_text(encoding="utf-8")
        return _extract_description_from_frontmatter(content)
    except Exception as e:
        logger.debug(
            f"Failed to parse skill description from {skill_md_path}: {e}",
        )
    return ""


def _extract_description_from_frontmatter(content: str) -> str:
    """从 YAML frontmatter 提取 description 字段.

    Args:
        content: 文件内容

    Returns:
        技能描述字符串，未找到则返回空字符串
    """
    if not content.startswith("---"):
        return ""

    end_idx = content.find("---", 3)
    if end_idx == -1:
        return ""

    frontmatter = content[3:end_idx].strip()
    for line in frontmatter.split("\n"):
        if line.startswith("description:"):
            desc = line.split(":", 1)[1].strip()
            return _strip_quotes(desc)
    return ""


def _strip_quotes(text: str) -> str:
    """移除字符串两端可能的引号.

    Args:
        text: 原始字符串

    Returns:
        移除引号后的字符串
    """
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    return text


class SkillInvocationDetector:
    """Skill invocation detector.

    Responsible for:
    1. Detecting tool calls that belong to skill execution flows
    2. Managing skill execution start/end boundaries
    3. Resolving multi-skill attribution conflicts
    4. Tracking skill state and activity

    The detector uses multiple layers for attribution:
    - Layer 1: Explicit declaration (uses_tools in SKILL.md)
    - Layer 2: Feature matching (file extensions, keywords)
    - Layer 3: Tool sequence patterns
    - Layer 4: Skill-tool association hints

    Example:
        detector = SkillInvocationDetector(
            registry=get_skill_tool_registry(),
            context_manager=get_skill_context_manager(),
        )
        detector.set_enabled_skills(["xlsx", "pdf"])

        # On tool call
        primary_skill, weights = await detector.on_tool_call(
            "execute_shell_command",
            {"command": "python process.py data.xlsx"},
        )
        # Returns: ("xlsx", {"xlsx": 0.8, "pdf": 0.2})
    """

    def __init__(
        self,
        registry: Optional[SkillToolRegistry] = None,
        context_manager: Optional[SkillContextManager] = None,
        inferencer: Optional[SkillFeatureInferencer] = None,
        trace_manager: Optional["TraceManager"] = None,
        trace_id: Optional[str] = None,
        user_id: str = "",
        session_id: str = "",
        channel: str = "",
        source_id: str = "",
        idle_threshold: int = 3,
        user_name: Optional[str] = None,
        bbk_id: Optional[str] = None,
        workspace_dir: Optional[Path] = None,
        skill_hook_loader: (
            Callable[[str], Awaitable[None] | None] | None
        ) = None,
        confirmed_skill_callback: (
            Callable[[str], Awaitable[None] | None] | None
        ) = None,
    ) -> None:
        """Initialize the detector.

        Args:
            registry: Skill-tool registry for explicit declarations
            context_manager: Skill context manager for execution tracking
            inferencer: Feature inferencer for legacy skill support
            trace_manager: Optional trace manager for emitting events
            trace_id: Current trace ID
            user_id: User identifier
            session_id: Session identifier
            channel: Channel identifier
            source_id: Source identifier for data isolation
            idle_threshold: Number of non-skill tool calls before ending skill
            user_name: Optional user name
            bbk_id: Optional BBK identifier
            workspace_dir: Workspace directory for reading skill manifest
            skill_hook_loader: Optional session-scoped hook loader callback
            confirmed_skill_callback: Optional callback invoked when a skill
                reaches confirmed association and is activated
        """
        self._registry = registry or get_skill_tool_registry()
        self._context_manager = context_manager or get_skill_context_manager()
        self._inferencer = inferencer or get_skill_feature_inferencer()
        self._trace_manager = trace_manager
        self._trace_id = trace_id
        self._user_id = user_id
        self._session_id = session_id
        self._channel = channel
        self._source_id = source_id
        self._user_name = user_name
        self._bbk_id = bbk_id
        self._workspace_dir = workspace_dir
        self._skill_hook_loader = skill_hook_loader
        self._confirmed_skill_callback = confirmed_skill_callback

        # Configuration
        self._idle_threshold = idle_threshold

        # State tracking
        self._enabled_skills: set[str] = set()
        self._skill_descriptions: dict[str, str] = (
            {}
        )  # skill_name -> description
        self._skill_ids: dict[str, str] = {}  # skill_name -> skill_id
        self._skill_cn_names: dict[str, str] = {}  # skill_name -> cn_name
        self._skill_activation_time: dict[str, datetime] = {}
        self._skill_call_history: dict[str, int] = {}
        self._idle_counters: dict[str, int] = {}
        self._recent_tools: list[str] = []

        # Layer 0: User message detection cache
        self._message_detected_skill: Optional[str] = None
        self._message_detected_confidence: float = 0.0

    def set_enabled_skills(self, skills: list[str]) -> None:
        """Set the list of enabled skills and cache their descriptions.

        Reads skill descriptions from workspace skill.json manifest at
        setup time, so they're ready when start_skill is called.

        Args:
            skills: List of skill names that are currently enabled
        """
        self._enabled_skills = set(skills)

        # Pre-cache descriptions from workspace manifest
        if self._workspace_dir:
            skill_json_path = self._workspace_dir / "skill.json"

            if skill_json_path.exists():
                try:
                    with open(skill_json_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)

                    for skill_name in skills:
                        skill_entry = manifest.get("skills", {}).get(
                            skill_name,
                            {},
                        )
                        metadata = skill_entry.get("metadata", {})
                        description = metadata.get("description", "") or ""
                        if description:
                            self._skill_descriptions[skill_name] = str(
                                description,
                            )
                            logger.debug(
                                "Cached description for skill '%s'",
                                skill_name,
                            )
                        # Cache skill_id and cn_name
                        skill_id = metadata.get("skill_id", "")
                        cn_name = metadata.get("cn_name", "")
                        if skill_id:
                            self._skill_ids[skill_name] = str(skill_id)
                            logger.debug(
                                "Cached skill_id for '%s': %s",
                                skill_name,
                                skill_id,
                            )
                        else:
                            logger.debug(
                                "No skill_id in metadata for '%s'",
                                skill_name,
                            )
                        if cn_name:
                            self._skill_cn_names[skill_name] = str(cn_name)
                            logger.debug(
                                "Cached cn_name for '%s': %s",
                                skill_name,
                                cn_name,
                            )
                        else:
                            logger.debug(
                                "No cn_name in metadata for '%s'",
                                skill_name,
                            )
                except Exception as e:
                    logger.warning("Failed to read skill manifest: %s", e)

    def detect_from_user_message(
        self,
        user_message: str,
    ) -> tuple[Optional[str], float]:
        """Layer 0: Detect skill from user message content.

        This method should be called at the start of a trace, before any
        tool calls are made. The result is cached for use during tool
        call detection.

        Args:
            user_message: User's message text

        Returns:
            Tuple of (skill_name, confidence) or (None, 0.0)
        """
        enabled_skills = list(self._enabled_skills)

        skill, confidence = self._inferencer.infer_skill_from_user_message(
            user_message,
            enabled_skills,
        )

        if skill:
            self._message_detected_skill = skill
            self._message_detected_confidence = confidence

        return skill, confidence

    def set_tracing_context(
        self,
        trace_manager: "TraceManager",
        trace_id: str,
        user_id: str,
        session_id: str,
        channel: str,
        source_id: str = "",
    ) -> None:
        """Set tracing context for emitting events.

        Args:
            trace_manager: Trace manager instance
            trace_id: Current trace ID
            user_id: User identifier
            session_id: Session identifier
            channel: Channel identifier
        """
        self._trace_manager = trace_manager
        self._trace_id = trace_id
        self._user_id = user_id
        self._session_id = session_id
        self._channel = channel
        self._source_id = source_id

    async def on_tool_call(
        self,
        tool_name: str,
        tool_input: Optional[dict[str, Any]] = None,
        mcp_server: Optional[str] = None,
    ) -> tuple[Optional[str], dict[str, float]]:
        """Process a tool call and determine skill attribution.

        This is the main entry point for skill detection. It:
        1. Queries the registry for explicit declarations
        2. Falls back to feature inference if needed
        3. Manages skill activation/deactivation
        4. Returns attribution with weights

        Args:
            tool_name: Name of the tool being called
            tool_input: Tool input parameters (for inference)
            mcp_server: MCP server name if this is an MCP tool

        Returns:
            Tuple of (primary_skill, weights_dict)
            - primary_skill: The main skill to attribute this call to
            - weights: Dict mapping skill_name -> weight (sum = 1.0)
        """
        tool_input = tool_input or {}

        # Track recent tools for sequence matching
        self._recent_tools.append(tool_name)
        if len(self._recent_tools) > 10:
            self._recent_tools.pop(0)

        # Step 0: Check if Agent is reading a skill's SKILL.md (highest priority)
        # 当Agent主动读取某技能的SKILL.md文件时，直接激活该技能
        skill_from_md_read = self._detect_skill_from_skill_md_read(
            tool_name,
            tool_input,
        )
        if skill_from_md_read:
            await self._ensure_skill_active(
                skill_from_md_read,
                1.0,
                tool_name,
            )
            self._context_manager.record_tool_call(tool_name, mcp_server)
            return skill_from_md_read, {skill_from_md_read: 1.0}

        # Step 1: Check for explicit declaration
        declared_skills = self._registry.get_skills_for_tool(tool_name)

        # Filter to enabled skills only
        declared_skills = [
            s for s in declared_skills if s in self._enabled_skills
        ]

        if declared_skills:
            return await self._handle_declared_skills(
                declared_skills,
                tool_name,
                tool_input,
            )

        # Step 2-4: Fallback to inference for legacy skills
        return await self._infer_skill_attribution(
            tool_name,
            tool_input,
            mcp_server,
        )

    async def _handle_declared_skills(
        self,
        skills: list[str],
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> tuple[Optional[str], dict[str, float]]:
        """Handle tool call with explicit skill declarations.

        Args:
            skills: Skills that declare using this tool
            tool_name: Tool name
            tool_input: Tool input

        Returns:
            Tuple of (primary_skill, weights)
        """
        current = self._context_manager.current_skill

        # Check if current active skill is in the list
        if current and current in skills:
            # Continue current skill
            self._update_skill_state(current)
            self._context_manager.record_tool_call(tool_name)
            return current, {current: 1.0}

        # Check if current skill should end (idle threshold)
        if current:
            self._idle_counters[current] = (
                self._idle_counters.get(current, 0) + 1
            )
            if self._idle_counters[current] >= self._idle_threshold:
                await self._end_skill(current)
                current = None

        # Calculate weights for multi-skill attribution
        weights = self._calculate_weights(skills, tool_name, tool_input)

        # Select primary skill (highest weight)
        primary_skill = (
            max(weights, key=lambda k: weights[k]) if weights else None
        )

        # Start new skill if none active
        if not current and primary_skill:
            await self.start_skill(
                primary_skill,
                trigger_tool=tool_name,
                trigger_reason="declared",
                confidence=weights[primary_skill],
            )
            self._context_manager.record_tool_call(tool_name)

        return primary_skill, weights

    async def _infer_skill_attribution(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        mcp_server: Optional[str] = None,
    ) -> tuple[Optional[str], dict[str, float]]:
        """Infer skill attribution for tools without explicit declarations.

        Uses multiple layers:
        0. Cached user message detection (if available)
        1. MCP server matching
        2. Feature matching (file extensions, keywords)
        3. Tool sequence patterns
        4. Tool-skill hints

        Args:
            tool_name: Tool name
            tool_input: Tool input
            mcp_server: MCP server if applicable

        Returns:
            Tuple of (primary_skill, weights)
        """
        enabled_skills = list(self._enabled_skills)

        # Layer 0: Check cached user message detection
        if (
            self._message_detected_skill
            and self._message_detected_confidence >= 0.7
        ):
            skill = self._message_detected_skill
            confidence = self._message_detected_confidence
            await self._ensure_skill_active(skill, confidence, tool_name)
            self._context_manager.record_tool_call(tool_name, mcp_server)
            return skill, {skill: confidence}

        # Layer 1: MCP server matching
        if mcp_server:
            skill, confidence = self._inferencer.infer_skill_from_mcp_server(
                mcp_server,
                enabled_skills,
            )
            if skill and confidence >= 0.8:
                await self._ensure_skill_active(skill, confidence, tool_name)
                self._context_manager.record_tool_call(tool_name, mcp_server)
                return skill, {skill: confidence}

        # Layer 2: Feature matching
        skill, confidence = self._inferencer.infer_skill_from_tool_input(
            tool_name,
            tool_input,
            enabled_skills,
        )
        if skill and confidence >= 0.6:
            await self._ensure_skill_active(skill, confidence, tool_name)
            self._context_manager.record_tool_call(tool_name, mcp_server)
            return skill, {skill: confidence}

        # Layer 3: Tool sequence patterns
        skill, confidence = self._inferencer.infer_skill_from_tool_sequence(
            self._recent_tools,
            enabled_skills,
        )
        if skill and confidence >= 0.5:
            await self._ensure_skill_active(skill, confidence, tool_name)
            self._context_manager.record_tool_call(tool_name, mcp_server)
            return skill, {skill: confidence}

        # Layer 4: Tool hints
        inferred = self._inferencer.get_skills_for_tool(
            tool_name,
            enabled_skills,
        )
        if inferred:
            primary_skill = inferred[0][0]
            weights = dict(inferred)
            await self._ensure_skill_active(
                primary_skill,
                weights.get(primary_skill, 0.4),
                tool_name,
            )
            self._context_manager.record_tool_call(tool_name, mcp_server)
            return primary_skill, weights

        # No attribution possible
        return None, {}

    async def _ensure_skill_active(
        self,
        skill_name: str,
        confidence: float,
        trigger_tool: str,
    ) -> None:
        """Ensure a skill is active, starting it if needed.

        Args:
            skill_name: Skill to ensure active
            confidence: Attribution confidence
            trigger_tool: Tool that triggered this skill
        """
        current = self._context_manager.current_skill

        if current == skill_name:
            # Already active, just update state
            self._update_skill_state(skill_name)
            return

        if current:
            # Different skill active, end it first
            await self._end_skill(current)

        # Start the new skill
        await self.start_skill(
            skill_name,
            trigger_tool=trigger_tool,
            trigger_reason="inferred",
            confidence=confidence,
        )

    def _calculate_weights(
        self,
        skills: list[str],
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, float]:
        """Calculate attribution weights for multi-skill scenarios.

        Uses multiple factors:
        - Recency of activation (0-0.4)
        - Input feature matching (0-0.3)
        - Call frequency (0-0.2)
        - Enabled status (0-0.1)

        Args:
            skills: Skills claiming this tool
            tool_name: Tool name
            tool_input: Tool input

        Returns:
            Dict mapping skill_name -> weight (sum = 1.0)
        """
        if len(skills) == 1:
            return {skills[0]: 1.0}

        scores: dict[str, float] = {}

        for skill in skills:
            score = 0.0

            # Factor 1: Recent activation (decays over 5 minutes)
            if skill in self._skill_activation_time:
                elapsed = (
                    datetime.now() - self._skill_activation_time[skill]
                ).seconds
                recency = max(0, 0.4 * (1 - elapsed / 300))
                score += recency

            # Factor 2: Input feature matching
            input_score = self._match_tool_input(skill, tool_name, tool_input)
            score += input_score * 0.3

            # Factor 3: Call frequency
            calls = self._skill_call_history.get(skill, 0)
            frequency = min(0.2, calls * 0.02)
            score += frequency

            # Factor 4: Enabled status
            if skill in self._enabled_skills:
                score += 0.1

            scores[skill] = score

        # Normalize to sum = 1.0
        total = sum(scores.values())
        if total > 0:
            return {k: v / total for k, v in scores.items()}
        else:
            # Equal distribution if no factors apply
            n = len(skills)
            return {s: 1.0 / n for s in skills}

    def _match_tool_input(
        self,
        skill: str,
        _tool_name: str,
        tool_input: dict[str, Any],
    ) -> float:
        """Match tool input against skill features.

        Args:
            skill: Skill name
            tool_name: Tool name
            tool_input: Tool input parameters

        Returns:
            Match score (0.0-1.0)
        """
        feature = self._inferencer.get_feature(skill)
        if not feature:
            return 0.5  # No feature info, neutral score

        input_str = str(tool_input).lower()
        matches = sum(
            1 for f in feature.file_extensions if f.lower() in input_str
        )
        matches += sum(1 for kw in feature.keywords if kw.lower() in input_str)

        if not feature.file_extensions and not feature.keywords:
            return 0.5

        total_features = len(feature.file_extensions) + len(feature.keywords)
        if total_features == 0:
            return 0.5

        return matches / total_features

    def _detect_skill_from_skill_md_read(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> Optional[str]:
        """检测Agent是否在读取某个技能的SKILL.md文件.

        当Agent调用read_file工具读取某个启用技能的SKILL.md时，
        这表明Agent正在主动了解该技能的使用方法，应将该技能激活。

        Args:
            tool_name: 工具名称
            tool_input: 工具输入参数

        Returns:
            技能名称，如果未检测到则返回None
        """
        if tool_name != "read_file":
            return None

        file_path = tool_input.get("file_path", "")
        if not file_path:
            return None

        path = Path(file_path)
        if path.name != "SKILL.md":
            return None

        skill_name = path.parent.name
        if skill_name in self._enabled_skills:
            logger.info(
                "Detected skill '%s' from SKILL.md read: %s",
                skill_name,
                file_path,
            )
            return skill_name

        return None

    def _update_skill_state(self, skill: str) -> None:
        """Update skill state after a tool call.

        Args:
            skill: Skill name to update
        """
        self._skill_activation_time[skill] = datetime.now()
        self._skill_call_history[skill] = (
            self._skill_call_history.get(skill, 0) + 1
        )
        if skill in self._idle_counters:
            self._idle_counters[skill] = 0

    def get_skill_description(self, skill_name: str) -> str:
        """获取技能描述.

        从缓存的 _skill_descriptions 中获取，如果缓存中没有则尝试从
        内置技能目录的 SKILL.md 文件中获取。

        Args:
            skill_name: 技能名称

        Returns:
            技能描述字符串，如果未找到则返回空字符串
        """
        # 优先从缓存获取
        description = self._skill_descriptions.get(skill_name, "")
        if description:
            return description

        # Fallback 到内置技能目录
        return _get_skill_description(skill_name)

    async def start_skill(
        self,
        skill_name: str,
        trigger_tool: str,
        trigger_reason: str = "inferred",
        confidence: float = 1.0,
    ) -> None:
        """Start a new skill invocation.

        Args:
            skill_name: Skill to start
            trigger_tool: Tool that triggered this skill
            trigger_reason: How the skill was detected
            confidence: Attribution confidence
        """
        # Get skill description - prefer cached manifest, fallback to SKILL.md
        skill_description = self.get_skill_description(skill_name)

        # Get skill_id and cn_name from cache
        skill_id = self._skill_ids.get(skill_name)
        cn_name = self._skill_cn_names.get(skill_name)

        # Debug log for skill_id and cn_name
        logger.debug(
            "start_skill: skill_name=%s, skill_id=%s, cn_name=%s, description=%s",
            skill_name,
            skill_id,
            cn_name,
            skill_description[:50] if skill_description else None,
        )

        # Emit tracing event first to get span_id
        span_id = None
        if self._trace_manager and self._trace_id:
            try:
                span_id = await self._trace_manager.emit_skill_invocation(
                    trace_id=self._trace_id,
                    skill_name=skill_name,
                    user_id=self._user_id,
                    session_id=self._session_id,
                    channel=self._channel,
                    source_id=self._source_id,
                    skill_input={
                        "trigger_tool": trigger_tool,
                        "trigger_reason": trigger_reason,
                        "confidence": confidence,
                    },
                    user_name=self._user_name,
                    bbk_id=self._bbk_id,
                    skill_id=skill_id,
                    skill_cn_name=cn_name,
                    skill_description=skill_description,
                )
            except Exception as e:
                logger.warning("Failed to emit skill start event: %s", e)

        # Push to context manager with span_id
        self._context_manager.push_skill(
            skill_name,
            trigger_reason=trigger_reason,
            confidence=confidence,
            span_id=span_id,
        )

        # Update state
        self._update_skill_state(skill_name)

        if self._confirmed_skill_callback is not None:
            try:
                result = self._confirmed_skill_callback(skill_name)
                if isawaitable(result):
                    await result
            except Exception as e:
                logger.warning(
                    "Failed to persist confirmed skill '%s': %s",
                    skill_name,
                    e,
                )

        if self._skill_hook_loader is not None:
            try:
                result = self._skill_hook_loader(skill_name)
                if isawaitable(result):
                    await result
            except Exception as e:
                logger.warning(
                    "Failed to load hooks for skill '%s': %s",
                    skill_name,
                    e,
                )

        logger.info(
            "Started skill '%s' (reason: %s, confidence: %.2f)",
            skill_name,
            trigger_reason,
            confidence,
        )

    async def _end_skill(self, _skill_name: str) -> None:
        """End a skill invocation.

        Args:
            _skill_name: Skill to end (unused, kept for API consistency)
        """
        # Pop from context manager
        context = self._context_manager.pop_skill()

        if context is None:
            return

        # Emit tracing event with span_id from context
        if self._trace_manager and self._trace_id and context.span_id:
            try:
                await self._trace_manager.end_skill_invocation(
                    trace_id=self._trace_id,
                    span_id=context.span_id,
                    skill_output=json.dumps(
                        {
                            "tools_called": context.tools_called,
                            "mcp_tools_called": context.mcp_tools_called,
                            "total_tools": len(context.tools_called)
                            + len(context.mcp_tools_called),
                        },
                    ),
                )
            except Exception as e:
                logger.warning("Failed to emit skill end event: %s", e)

    async def on_reasoning_end(self) -> None:
        """Handle end of LLM reasoning.

        Ends all active skills when reasoning completes.
        """
        # End all skills in the stack (from top to bottom)
        while self._context_manager.skill_depth > 0:
            current = self._context_manager.current_skill
            if current:
                await self._end_skill(current)
            else:
                break

        # Clear any remaining state
        self._context_manager.clear()

    def reset(self) -> None:
        """Reset detector state for a new request."""
        self._skill_activation_time.clear()
        self._skill_call_history.clear()
        self._idle_counters.clear()
        self._recent_tools.clear()
        self._context_manager.clear()
        # Clear Layer 0 cache
        self._message_detected_skill = None
        self._message_detected_confidence = 0.0


# Global detector instance (per-request, should be reset)
_skill_invocation_detector: Optional[SkillInvocationDetector] = None


def get_skill_invocation_detector() -> SkillInvocationDetector:
    """Get the global skill invocation detector.

    Returns:
        SkillInvocationDetector instance
    """
    global _skill_invocation_detector
    if _skill_invocation_detector is None:
        _skill_invocation_detector = SkillInvocationDetector()
    return _skill_invocation_detector


def reset_skill_invocation_detector() -> None:
    """Reset the global detector (for testing or new request)."""
    global _skill_invocation_detector
    if _skill_invocation_detector is not None:
        _skill_invocation_detector.reset()
    _skill_invocation_detector = None
