# Skill readiness results live in SWE

Skill readiness run records and per-user readiness results are stored in dedicated SWE backend tables, not in Monitor. Monitor remains the cron reporting store and only needs the scheduled-job skill binding field for lookup; readiness runs are skill diagnostics that depend on SWE runtime state, source-scoped user directories, credentials, model configuration, and MCP availability.
