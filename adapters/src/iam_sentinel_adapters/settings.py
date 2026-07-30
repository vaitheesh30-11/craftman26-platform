"""Environment configuration for every adapter, resolved once at import.

Adapters never call `os.environ` directly; they import `settings` from here.
Values are read once at cold start and cached for the process lifetime, per
phase-00 §7.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Stage = Literal["dev", "staging", "prod"]


class AdapterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
    )

    stage: Stage = "dev"
    region: str = "us-east-1"
    guardrail_id: str = ""
    guardrail_version: str = "DRAFT"
    evidence_bucket: str = "sentinel-evidence-dev"
    evidence_kms_key_arn: str = ""
    findings_table: str = "SentinelFindings-dev"
    decisions_table: str = "SentinelDecisions-dev"
    decisions_in_flight_table: str = "SentinelDecisionsInFlight-dev"
    memory_episodic_table: str = "SentinelMemoryEpisodic-dev"
    memory_semantic_table: str = "SentinelMemorySemantic-dev"
    memory_procedural_table: str = "SentinelMemoryProcedural-dev"
    budget_table: str = "SentinelBudget-dev"
    breakers_table: str = "SentinelBreakers-dev"
    log_level: str = "INFO"
    metric_namespace: str = "IAMSentinel"
    model_haiku_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"
    model_sonnet_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"


settings = AdapterSettings()
