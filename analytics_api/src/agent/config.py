"""
config.py — AgentConfig

All tuneable parameters for the DomainExpertAgent pipeline, read from
environment variables with sensible defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    # Azure OpenAI
    azure_endpoint: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", "")
    )
    azure_api_key: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY", "")
    )
    azure_api_version: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    )
    azure_deployment: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-2025-04-14")
    )

    # BigQuery
    bq_project: str = field(
        default_factory=lambda: os.getenv("BQ_PROJECT", "ai-risk-workflow")
    )

    # Intent parser
    intent_max_tokens: int = 256
    intent_temperature: float = 0.0

    # Query guard
    max_result_rows: int = 10_000
    sql_timeout_seconds: int = 30

    # Feature flags
    enable_lineage: bool = field(
        default_factory=lambda: os.getenv("AGENT_LINEAGE_ENABLED", "true").lower() == "true"
    )
    enable_rule_validation: bool = field(
        default_factory=lambda: os.getenv("AGENT_RULE_VALIDATION", "true").lower() == "true"
    )
