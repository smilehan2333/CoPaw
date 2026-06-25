# -*- coding: utf-8 -*-
"""Tracing data models.

Defines Trace, Span, EventType, and related models for tracing events.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


class EventType(str, Enum):
    """Event types for tracing."""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    LLM_INPUT = "llm_input"
    LLM_OUTPUT = "llm_output"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    SKILL_INVOCATION = "skill_invocation"


class TraceStatus(str, Enum):
    """Trace status."""

    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class Span(BaseModel):
    """Span represents a single operation within a trace.

    A span can be an LLM call, tool execution, or skill invocation.
    """

    model_config = ConfigDict(use_enum_values=True)

    span_id: str = Field(description="Unique span identifier")
    trace_id: str = Field(description="Parent trace identifier")
    source_id: str = Field(description="Source identifier for data isolation")
    name: str = Field(description="Span name/operation name")
    event_type: EventType = Field(description="Type of event")
    start_time: datetime = Field(description="Start timestamp")
    end_time: Optional[datetime] = Field(
        default=None,
        description="End timestamp",
    )
    duration_ms: Optional[int] = Field(
        default=None,
        description="Duration in milliseconds",
    )
    user_id: str = Field(default="", description="User identifier")
    user_name: Optional[str] = Field(default=None, description="User name")
    bbk_id: Optional[str] = Field(default=None, description="BBK identifier")
    session_id: str = Field(default="", description="Session identifier")
    channel: str = Field(default="", description="Channel identifier")
    model_name: Optional[str] = Field(
        default=None,
        description="Model name for LLM events",
    )
    input_tokens: Optional[int] = Field(
        default=None,
        description="Input token count",
    )
    output_tokens: Optional[int] = Field(
        default=None,
        description="Output token count",
    )
    tool_name: Optional[str] = Field(
        default=None,
        description="Tool name for tool events",
    )
    skill_name: Optional[str] = Field(
        default=None,
        description="Skill name for skill events",
    )
    skill_id: Optional[str] = Field(
        default=None,
        description="Skill unique identifier",
    )
    skill_cn_name: Optional[str] = Field(
        default=None,
        description="Skill Chinese display name",
    )
    skill_description: Optional[str] = Field(
        default=None,
        description="Skill description from SKILL.md",
    )
    mcp_server: Optional[str] = Field(
        default=None,
        description="MCP server name if this tool is from MCP",
    )
    tool_input: Optional[dict[str, Any]] = Field(
        default=None,
        description="Tool input (sanitized)",
    )
    tool_output: Optional[str] = Field(
        default=None,
        description="Tool output (truncated)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if failed",
    )


class Trace(BaseModel):
    """Trace represents a complete request/session trace.

    A trace contains multiple spans and represents the full lifecycle
    of a user request.
    """

    model_config = ConfigDict(use_enum_values=True)

    trace_id: str = Field(description="Unique trace identifier")
    source_id: str = Field(description="Source identifier for data isolation")
    user_id: str = Field(description="User identifier")
    user_name: Optional[str] = Field(default=None, description="User name")
    bbk_id: Optional[str] = Field(default=None, description="BBK identifier")
    session_id: str = Field(description="Session identifier")
    session_name: Optional[str] = Field(
        default=None,
        description="Session name (derived from first message)",
    )
    channel: str = Field(description="Channel identifier")
    start_time: datetime = Field(description="Trace start timestamp")
    end_time: Optional[datetime] = Field(
        default=None,
        description="Trace end timestamp",
    )
    duration_ms: Optional[int] = Field(
        default=None,
        description="Total duration in milliseconds",
    )
    model_name: Optional[str] = Field(
        default=None,
        description="Primary model used",
    )
    total_input_tokens: int = Field(
        default=0,
        description="Total input tokens",
    )
    total_output_tokens: int = Field(
        default=0,
        description="Total output tokens",
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="Tools used in trace",
    )
    skills_used: list[str] = Field(
        default_factory=list,
        description="Skills used in trace",
    )
    status: TraceStatus = Field(
        default=TraceStatus.RUNNING,
        description="Trace status",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if failed",
    )
    user_message: Optional[str] = Field(
        default=None,
        description="User's input message (truncated)",
    )
    model_output: Optional[str] = Field(
        default=None,
        description="Model's output message (from ES)",
    )


# API Response Models


class ModelUsage(BaseModel):
    """Model usage statistics."""

    model_name: str
    count: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class ToolUsage(BaseModel):
    """Tool usage statistics."""

    tool_name: str
    count: int = 0
    avg_duration_ms: int = 0
    error_count: int = 0


class SkillUsage(BaseModel):
    """Skill usage statistics with weighted attribution."""

    skill_name: str
    count: int = 0
    weighted_count: float = 0.0
    avg_duration_ms: int = 0
    weighted_duration_ms: int = 0
    tool_attribution: dict[str, float] = Field(
        default_factory=dict,
        description="Tool name -> weighted usage count mapping",
    )


class MCPToolUsage(BaseModel):
    """MCP tool usage statistics."""

    tool_name: str
    mcp_server: str
    count: int = 0
    avg_duration_ms: int = 0
    error_count: int = 0


class MCPServerUsage(BaseModel):
    """MCP server usage statistics."""

    server_name: str
    tool_count: int = 0
    total_calls: int = 0
    avg_duration_ms: int = 0
    error_count: int = 0
    tools: list[MCPToolUsage] = Field(default_factory=list)


class DailyStats(BaseModel):
    """Daily statistics."""

    date: str
    total_users: int = 0
    active_users: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    session_count: int = 0
    conversation_count: int = 0
    avg_duration_ms: int = 0


class OverviewStats(BaseModel):
    """Overview dashboard statistics."""

    online_users: int = 0
    online_user_ids: list[str] = Field(default_factory=list)
    total_users: int = 0
    model_distribution: list[ModelUsage] = Field(default_factory=list)
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_sessions: int = 0
    total_conversations: int = 0
    avg_duration_ms: int = 0
    top_tools: list[ToolUsage] = Field(default_factory=list)
    top_skills: list[SkillUsage] = Field(default_factory=list)
    top_mcp_tools: list[MCPToolUsage] = Field(default_factory=list)
    mcp_servers: list[MCPServerUsage] = Field(default_factory=list)
    daily_trend: list[DailyStats] = Field(default_factory=list)


class UserStats(BaseModel):
    """User-specific statistics."""

    user_id: str
    model_usage: list[ModelUsage] = Field(default_factory=list)
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_sessions: int = 0
    total_conversations: int = 0
    avg_duration_ms: int = 0
    tools_used: list[ToolUsage] = Field(default_factory=list)
    skills_used: list[SkillUsage] = Field(default_factory=list)


class ToolCall(BaseModel):
    """Tool call details in a trace."""

    tool_name: str
    tool_input: Optional[dict[str, Any]] = None
    tool_output: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None


class TraceDetail(BaseModel):
    """Detailed trace with spans."""

    trace: Trace
    spans: list[Span] = Field(default_factory=list)
    llm_duration_ms: int = 0
    tool_duration_ms: int = 0
    tools_called: list[dict[str, Any]] = Field(default_factory=list)


# Timeline models for hierarchical display


class ToolCallInSkill(BaseModel):
    """Tool call within a skill invocation."""

    span_id: str
    tool_name: str
    mcp_server: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: int = 0
    status: str = "success"  # success / error
    error: Optional[str] = None
    skill_weight: Optional[float] = None


class SkillCallTimeline(BaseModel):
    """Skill invocation in timeline with tool hierarchy."""

    span_id: str
    skill_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: int = 0
    confidence: float = 1.0
    trigger_reason: str = "declared"  # declared / inferred / keyword

    # Tools called within this skill (hierarchical)
    tools: list[ToolCallInSkill] = Field(default_factory=list)

    # Statistics
    total_tool_calls: int = 0
    tool_duration_ms: int = 0


class TimelineEvent(BaseModel):
    """Timeline event with hierarchical structure.

    Supports nested events for skill -> tool hierarchy.
    """

    event_type: str  # skill_invocation / tool_call / llm_call
    span_id: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: int = 0

    # Skill invocation fields
    skill_name: Optional[str] = None
    confidence: Optional[float] = None
    trigger_reason: Optional[str] = None

    # Tool call fields
    tool_name: Optional[str] = None
    mcp_server: Optional[str] = None
    skill_weight: Optional[float] = None

    # LLM call fields
    model_name: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

    # Hierarchical children (tools under skill)
    children: list["TimelineEvent"] = Field(default_factory=list)


# Update forward reference for recursive model
TimelineEvent.model_rebuild()


class TraceDetailWithTimeline(BaseModel):
    """Trace detail with hierarchical timeline.

    Provides both flat spans (backward compatible) and
    hierarchical timeline for enhanced visualization.
    """

    trace: Trace

    # Flat list (backward compatible)
    spans: list[Span] = Field(default_factory=list)

    # Hierarchical timeline
    timeline: list[TimelineEvent] = Field(default_factory=list)

    # Skill invocations summary
    skill_invocations: list[SkillCallTimeline] = Field(default_factory=list)

    # Statistics
    llm_duration_ms: int = 0
    tool_duration_ms: int = 0
    skill_duration_ms: int = 0
    total_skills: int = 0
    total_tools: int = 0
    total_llm_calls: int = 0


class UserListItem(BaseModel):
    """User list item with stats."""

    user_id: str
    user_name: Optional[str] = Field(default=None, description="User name")
    bbk_id: Optional[str] = Field(default=None, description="BBK identifier")
    total_sessions: int = 0
    total_conversations: int = 0
    total_tokens: int = 0
    total_skills: int = 0
    last_active: Optional[datetime] = None


class TraceListItem(BaseModel):
    """Trace list item."""

    trace_id: str
    source_id: str
    user_id: str
    user_name: Optional[str] = Field(default=None, description="User name")
    bbk_id: Optional[str] = Field(default=None, description="BBK identifier")
    session_id: str
    channel: str
    start_time: datetime
    duration_ms: Optional[int] = None
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model_name: Optional[str] = None
    status: str
    skills_count: int = 0
    feedback_content: Optional[str] = None
    feedback_updated_at: Optional[datetime] = None


class SessionListItem(BaseModel):
    """Session list item with stats."""

    session_id: str
    session_name: Optional[str] = Field(
        default=None,
        description="Session name (from first message)",
    )
    user_id: str
    user_name: Optional[str] = Field(default=None, description="User name")
    bbk_id: Optional[str] = Field(default=None, description="BBK identifier")
    channel: str
    total_traces: int = 0
    total_tokens: int = 0
    total_skills: int = 0
    first_active: Optional[datetime] = None
    last_active: Optional[datetime] = None


class SessionStats(BaseModel):
    """Session-specific statistics."""

    session_id: str
    user_id: str
    channel: str
    model_usage: list[ModelUsage] = Field(default_factory=list)
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_traces: int = 0
    avg_duration_ms: int = 0
    tools_used: list[ToolUsage] = Field(default_factory=list)
    skills_used: list[SkillUsage] = Field(default_factory=list)
    mcp_tools_used: list[MCPToolUsage] = Field(default_factory=list)
    first_active: Optional[datetime] = None
    last_active: Optional[datetime] = None


class UserMessageItem(BaseModel):
    """User message with token info for cost analysis."""

    trace_id: str
    source_id: str
    user_id: str
    user_name: Optional[str] = Field(default=None, description="User name")
    bbk_id: Optional[str] = Field(default=None, description="BBK identifier")
    session_id: str
    channel: str
    user_message: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    model_name: Optional[str] = None
    start_time: datetime
    duration_ms: Optional[int] = None
