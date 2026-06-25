# Skill readiness configs are global by skill id

Skill readiness configuration is stored in a dedicated SWE backend table keyed by `skill_id`, not inside source system configuration. The readiness rules describe a market skill itself, while `source_id` only scopes owner lookup, runtime directories, credentials, scheduled jobs, and run results; keeping the configuration in its own table avoids mixing global skill rules into source-scoped JSON and keeps future configuration management centered on the skill id.
