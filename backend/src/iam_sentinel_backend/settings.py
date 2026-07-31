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

    # Duplicated from `agents.settings` rather than imported -- same module
    # boundary as `ids.py` (backend never depends on `agents/`). Two plain
    # strings, not shared business logic.
    prime_agent_id: str = ""
    prime_agent_alias_id: str = ""

    # backend phase-01 §4 step 5: poll `decisions.get(...)` with exponential
    # backoff up to this budget after `invoke_agent` returns.
    chat_poll_budget_seconds: float = 25.0
    chat_poll_initial_delay_seconds: float = 0.5
    chat_poll_max_delay_seconds: float = 5.0

    # backend phase-02 §4 step 2/§6: once `invoke_agent_stream`'s final chunk
    # arrives, the same out-of-band-poll pattern as `chat_poll_budget_seconds`
    # applies, but bounded much tighter -- the client is already watching a
    # live socket, so there is no REST-style "come back later" fallback.
    ws_result_poll_budget_seconds: float = 5.0
    ws_result_poll_initial_delay_seconds: float = 0.2
    ws_result_poll_max_delay_seconds: float = 1.0
    # phase-02 §4 step 4: ~50 msgs/s per connection to avoid API GW throttling.
    ws_rate_limit_per_second: float = 50.0
    # phase-02 §4 step 4: 128 KB per WebSocket frame.
    ws_max_frame_bytes: int = 128 * 1024

    @property
    def approval_state_machine_ssm_param(self) -> str:
        """backend phase-03 §3 step 3: `SentinelApprovalApply`'s ARN is
        resolved at call time from SSM rather than a required env var, so
        `aws-infra` can publish it once the state machine is actually built
        (it is not yet) without a backend redeploy.
        """
        return f"/sentinel/{self.stage}/approval/state-machine-arn"


settings = BackendSettings()
