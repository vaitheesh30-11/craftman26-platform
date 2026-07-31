"""Environment configuration, resolved once at module import.

Every Lambda handler imports `settings` from this module rather than calling
`os.environ` directly. Values are read once at cold start and never re-read
per invocation, per phase-00 §3.3.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Stage = Literal["dev", "staging", "prod"]


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        case_sensitive=False,
        extra="ignore",
    )

    stage: Stage = "dev"
    findings_table: str = "SentinelFindings-dev"
    evidence_bucket: str = "sentinel-evidence-dev"
    kms_key_arn: str = ""
    cross_account_role_name: str = "SentinelCrossAccountRole"
    # F3 (agents phase-04 §4 Step 1): "name from SSM" — no SSM Parameter
    # Store client exists yet in adapters/, so this carries the same
    # placeholder-default convention aws-infra ADR 0009 used for
    # `org_trail_bucket_name` (an external, not-yet-real resource this
    # phase only references, not provisions).
    org_trail_name: str = "sentinel-org-trail"
    athena_output_location: str = "s3://sentinel-athena-results-dev/f3/"
    log_level: str = "INFO"
    metric_namespace: str = "IAMSentinel"
    kb_manifest_path: str = ""
    kb_manifest_refresh_seconds: int = Field(default=3600, ge=60)
    kb_knowledge_base_id: str = ""
    region: str = "us-east-1"
    prime_agent_id: str = ""
    prime_agent_alias_id: str = ""
    security_hub_account_id: str = ""


settings = AgentSettings()
