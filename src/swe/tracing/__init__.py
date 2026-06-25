# -*- coding: utf-8 -*-
"""CoPaw Tracing Module - Link tracing and analytics.

This module provides tracing and analytics capabilities for CoPaw,
including event collection, storage, and aggregation.
"""

__all__ = [
    # Config
    "TracingConfig",
    # Backward compatibility (deprecated, use from copaw.database)
    "DatabaseConfig",
    "TDSQLConfig",
    "DatabaseConnection",
    "TDSQLConnection",
    # Models
    "EventType",
    "Span",
    "Trace",
    "TraceStatus",
    # Manager
    "TraceManager",
    "TraceContext",
    "get_trace_manager",
    "init_trace_manager",
    "close_trace_manager",
    "get_current_trace",
    "capture_current_trace_context",
    "set_current_trace",
    "has_trace_manager",
    # Store
    "TraceStore",
    # Model wrapper
    "TracingModelWrapper",
]


def __getattr__(name: str):
    """Lazily export tracing members to avoid heavy runtime imports."""
    if name == "TracingConfig":
        from .config import TracingConfig as _TracingConfig

        return _TracingConfig
    if name in {"EventType", "Span", "Trace", "TraceStatus"}:
        from .models import (
            EventType as _EventType,
            Span as _Span,
            Trace as _Trace,
            TraceStatus as _TraceStatus,
        )

        exports = {
            "EventType": _EventType,
            "Span": _Span,
            "Trace": _Trace,
            "TraceStatus": _TraceStatus,
        }
        return exports[name]
    if name in {
        "TraceManager",
        "TraceContext",
        "get_trace_manager",
        "init_trace_manager",
        "close_trace_manager",
        "get_current_trace",
        "capture_current_trace_context",
        "set_current_trace",
        "has_trace_manager",
    }:
        from .manager import (
            TraceManager as _TraceManager,
            TraceContext as _TraceContext,
            get_trace_manager as _get_trace_manager,
            init_trace_manager as _init_trace_manager,
            close_trace_manager as _close_trace_manager,
            get_current_trace as _get_current_trace,
            capture_current_trace_context as _capture_current_trace_context,
            set_current_trace as _set_current_trace,
            has_trace_manager as _has_trace_manager,
        )

        exports = {
            "TraceManager": _TraceManager,
            "TraceContext": _TraceContext,
            "get_trace_manager": _get_trace_manager,
            "init_trace_manager": _init_trace_manager,
            "close_trace_manager": _close_trace_manager,
            "get_current_trace": _get_current_trace,
            "capture_current_trace_context": _capture_current_trace_context,
            "set_current_trace": _set_current_trace,
            "has_trace_manager": _has_trace_manager,
        }
        return exports[name]
    if name == "TraceStore":
        from .store import TraceStore as _TraceStore

        return _TraceStore
    if name == "TracingModelWrapper":
        from .model_wrapper import TracingModelWrapper as _TracingModelWrapper

        return _TracingModelWrapper
    if name in {
        "DatabaseConfig",
        "DatabaseConnection",
        "TDSQLConfig",
        "TDSQLConnection",
    }:
        from ..database import (
            DatabaseConfig as _DatabaseConfig,
            DatabaseConnection as _DatabaseConnection,
            TDSQLConfig as _TDSQLConfig,
            TDSQLConnection as _TDSQLConnection,
        )

        exports = {
            "DatabaseConfig": _DatabaseConfig,
            "DatabaseConnection": _DatabaseConnection,
            "TDSQLConfig": _TDSQLConfig,
            "TDSQLConnection": _TDSQLConnection,
        }
        return exports[name]
    raise AttributeError(name)
