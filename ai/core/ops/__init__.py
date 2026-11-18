"""Production configuration of the AI services (AI-21): environments, the startup check,
metadata-only event logs, quality sampling and the log-to-metric aggregator.

    from core.ops.settings import startup
    profile = startup()      # SKILLFORGE_ENV; raises StartupError in staging/production on errors

Kept import-free so low-level modules (core.knowledge, core.pipeline) can import
core.ops.events without a cycle. See docs/ai/production-config.md and docs/ai/runbook.md.
"""
