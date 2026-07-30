"""Environment configuration for the backend service, resolved once at
import (same convention as `adapters.settings` -- values are read once at
cold start and cached for the process lifetime, phase-00 §7).

Resource identifiers (table names, region, stage) live in
`iam_sentinel_adapters.settings`; this module only carries settings that
are specific to the HTTP surface itself (Cognito, correlation, break-glass).
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Stage = Literal["dev", "staging", "prod"]


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
    )

    stage: Stage = "dev"
    region: str = "us-east-1"
    commit_sha: str = "unknown"

    aws_account_id: str = ""
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_jwks_ttl_seconds: int = 900  # 15 min, per phase-00 §3
    cognito_group_auditors: str = "SentinelAuditors"
    cognito_group_operators: str = "SentinelOperators"
    cognito_group_breakglass: str = "SentinelBreakGlassInitiators"

    sigv4_caller_identity_ttl_seconds: int = 300  # 5 min, per phase-00 §3
    breakglass_session_tag_key: str = "BreakGlass"
    breakglass_session_tag_value: str = "IAMSentinel-Two-Signer"
    breakglass_header_name: str = "X-BreakGlass-Session-Tag"

    correlation_header_name: str = "X-Correlation-Id"

    log_level: str = "INFO"
    service_name: str = "iam-sentinel-backend"


settings = BackendSettings()
