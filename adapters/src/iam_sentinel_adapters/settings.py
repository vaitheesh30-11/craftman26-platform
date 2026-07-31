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
    slrs_table: str = "SentinelSLRs-dev"
    decisions_table: str = "SentinelDecisions-dev"
    decisions_in_flight_table: str = "SentinelDecisionsInFlight-dev"
    idempotency_table: str = "SentinelIdempotency-dev"
    critical_findings_topic_arn: str = ""
    memory_episodic_table: str = "SentinelMemoryEpisodic-dev"
    memory_semantic_table: str = "SentinelMemorySemantic-dev"
    memory_procedural_table: str = "SentinelMemoryProcedural-dev"
    budget_table: str = "SentinelBudget-dev"
    breakers_table: str = "SentinelBreakers-dev"
    log_level: str = "INFO"
    metric_namespace: str = "IAMSentinel"
    model_haiku_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"
    model_sonnet_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    llm_provider: Literal["grok", "bedrock"] = "bedrock"
    grok_model_id: str = "grok-4-latest"
    xai_api_key: str = ""
    correlation_dollar_cap: float = 1.00
    # agents-phase-16 §3 (docs/decisions/0032): the per-correlation cap
    # above is phase-01's; these three are the phase-16 layers phase-01
    # didn't need -- per-principal daily spend, per-correlation tool-call
    # count, and the fast/slow-path cost estimate table §5 step 2 uses for
    # the pre-invocation gate before any real Bedrock usage is known.
    principal_daily_dollar_cap: float = 50.00
    correlation_tool_invocation_cap: int = 30
    estimated_cost_fast: float = 0.001
    estimated_cost_slow_single: float = 0.10
    estimated_cost_slow_multi: float = 0.30
    kb_manifest_bucket: str = "sentinelkb-manifest-dev"
    kb_manifest_key: str = "manifest.json"
    kb_manifest_kms_key_arn: str = ""
    faults_table: str = "SentinelFaults-dev"
    reports_bucket: str = "sentinel-reports-dev"
    router_function_name: str = ""
    connections_table: str = "SentinelConnections-dev"
    policies_table: str = "SentinelPolicies-dev"
    divergence_table: str = "SentinelDivergence-dev"
    revocations_table: str = "SentinelRevocations-dev"
    session_kill_queue_url: str = ""
    emergency_revocations_topic_arn: str = ""
    never_revoke_ssm_param: str = "/sentinel/never-revoke-role-patterns"

    # backend phase-04 §2 step 2 / ADR 0029: no runtime registry of "every
    # breaker that exists" or "every DLQ that exists" is provisioned anywhere
    # in the codebase (`SentinelBreakers` is a bare key-value table with no
    # scan-all convention, and DLQ queue URLs are only known inside CDK synth
    # output, not published to SSM by any deployed stack yet) -- both lists
    # are therefore settings-driven (comma-separated) rather than
    # dynamically discovered. Defaults cover the breaker names already real
    # in code today (every `DynamoDbHelper`-backed table name, `bedrock`,
    # `zelkova`); `dlq_queue_urls` defaults empty until aws-infra publishes
    # real queue URLs for this environment.
    known_breaker_names: str = (
        "SentinelFindings-dev,SentinelDecisions-dev,SentinelDecisionsInFlight-dev,"
        "SentinelMemoryEpisodic-dev,SentinelMemorySemantic-dev,SentinelMemoryProcedural-dev,"
        "SentinelBudget-dev,SentinelFaults-dev,SentinelDivergence-dev,SentinelConnections-dev,"
        "SentinelIdempotency-dev,bedrock,zelkova"
    )
    dlq_queue_urls: str = ""


settings = AdapterSettings()
