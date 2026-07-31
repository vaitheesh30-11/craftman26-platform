"""DI-style FastAPI dependencies (phase-00 §2-3): auth, adapter singletons,
correlation. Every adapter client below is constructed once at cold start
and reused across invocations within the same Lambda execution environment
(phase-00 §3 step 3) -- routers never construct their own adapter clients.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import Depends, Request, status
from iam_sentinel_adapters.apigw.management import ManagementApiClient
from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
from iam_sentinel_adapters.compute.lambda_client import LambdaInvokeClient
from iam_sentinel_adapters.compute.step_functions_client import StepFunctionsClient
from iam_sentinel_adapters.ddb.connections import ConnectionsClient
from iam_sentinel_adapters.ddb.decisions import DecisionsClient
from iam_sentinel_adapters.ddb.decisions_in_flight import DecisionsInFlightClient
from iam_sentinel_adapters.ddb.divergence import DivergenceClient
from iam_sentinel_adapters.ddb.faults import FaultsClient
from iam_sentinel_adapters.ddb.findings import FindingsClient
from iam_sentinel_adapters.ddb.idempotency import IdempotencyClient
from iam_sentinel_adapters.evidence.client import EvidenceClient
from iam_sentinel_adapters.llm.factory import get_provider
from iam_sentinel_adapters.s3.reports import ReportsClient
from iam_sentinel_adapters.settings import settings as adapter_settings
from iam_sentinel_adapters.sqs.dlq import DlqClient
from iam_sentinel_adapters.ssm.params import SsmParameterClient

from iam_sentinel_backend.auth.breakglass import (
    BreakGlassVerificationError,
    verify_breakglass_header,
)
from iam_sentinel_backend.auth.cognito import CognitoJwtVerifier, CognitoVerificationError
from iam_sentinel_backend.auth.sigv4 import (
    from_apigw_identity,
    SigV4VerificationError,
    SigV4Verifier,
)
from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.services.approval_service import ApprovalService
from iam_sentinel_backend.services.chat_service import ChatService
from iam_sentinel_backend.services.decisions_service import DecisionsService
from iam_sentinel_backend.services.evidence_service import EvidenceService
from iam_sentinel_backend.services.findings_service import FindingsService
from iam_sentinel_backend.services.operations_service import OperationsService
from iam_sentinel_backend.services.reports_service import ReportsService
from iam_sentinel_backend.services.router_bridge_service import RouterBridgeService
from iam_sentinel_backend.settings import settings
from iam_sentinel_backend.ws.fanout import StreamFanoutService

if TYPE_CHECKING:
    from iam_sentinel_adapters.llm.types import LLMProvider

    from iam_sentinel_backend.auth.principal import Principal

_cognito_verifier = CognitoJwtVerifier()
_sigv4_verifier = SigV4Verifier()


def get_correlation_id(request: Request) -> str:
    correlation_id = getattr(request.state, "correlation_id", None)
    if not correlation_id:
        # Middleware always sets this before a handler runs; a missing value
        # means a route was reached outside the normal request pipeline
        # (e.g. a unit test calling the dependency directly).
        raise SentinelHTTPException(
            code="MISSING_CORRELATION_ID",
            message="correlation_id was not established for this request",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return str(correlation_id)


def _apigw_user_arn(request: Request) -> str | None:
    aws_event = request.scope.get("aws.event")
    if not isinstance(aws_event, dict):
        return None
    identity = aws_event.get("requestContext", {}).get("identity", {})
    user_arn = identity.get("userArn")
    return str(user_arn) if user_arn else None


def get_principal(request: Request) -> Principal:
    """Resolve the caller's `Principal` (phase-00 §3).

    Order: trust API Gateway's own IAM-auth pass-through first (no STS call
    needed); else inspect the `Authorization` header to pick SigV4-relay vs
    Cognito JWT verification.
    """
    apigw_arn = _apigw_user_arn(request)
    if apigw_arn is not None:
        return from_apigw_identity(apigw_arn)

    auth_header = request.headers.get("authorization")
    if not auth_header:
        raise SentinelHTTPException(
            code="UNAUTHENTICATED",
            message="missing Authorization header",
            http_status=status.HTTP_401_UNAUTHORIZED,
        )

    if auth_header.startswith("AWS4-HMAC-SHA256"):
        try:
            return _sigv4_verifier.verify_signed_headers(dict(request.headers))
        except SigV4VerificationError as exc:
            raise SentinelHTTPException(
                code="UNAUTHENTICATED", message=str(exc), http_status=status.HTTP_401_UNAUTHORIZED
            ) from exc

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        return _cognito_verifier.verify(token)
    except CognitoVerificationError as exc:
        raise SentinelHTTPException(
            code="UNAUTHENTICATED", message=str(exc), http_status=status.HTTP_401_UNAUTHORIZED
        ) from exc


def require_breakglass(
    request: Request, principal: Principal = Depends(get_principal)
) -> Principal:
    """Additional gate for `/emergency/*` routes (phase-00 §3 BreakGlass).

    Depends on `get_principal` directly (rather than requiring the caller to
    wire both) so FastAPI's per-request dependency cache resolves `Principal`
    exactly once even when a route also depends on `get_principal` itself.
    """
    header_value = request.headers.get(settings.breakglass_header_name)
    try:
        verify_breakglass_header(header_value)
    except BreakGlassVerificationError as exc:
        raise SentinelHTTPException(
            code="BREAKGLASS_REQUIRED", message=str(exc), http_status=status.HTTP_403_FORBIDDEN
        ) from exc
    return principal.model_copy(update={"breakglass_verified": True})


@lru_cache(maxsize=1)
def get_findings_client() -> FindingsClient:
    return FindingsClient()


@lru_cache(maxsize=1)
def get_decisions_client() -> DecisionsClient:
    return DecisionsClient()


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    return get_provider()


@lru_cache(maxsize=1)
def get_faults_client() -> FaultsClient:
    return FaultsClient()


@lru_cache(maxsize=1)
def get_reports_client() -> ReportsClient:
    return ReportsClient()


@lru_cache(maxsize=1)
def get_lambda_invoke_client() -> LambdaInvokeClient:
    return LambdaInvokeClient()


@lru_cache(maxsize=1)
def get_decisions_in_flight_client() -> DecisionsInFlightClient:
    return DecisionsInFlightClient()


@lru_cache(maxsize=1)
def get_connections_client() -> ConnectionsClient:
    return ConnectionsClient()


@lru_cache(maxsize=1)
def get_management_client() -> ManagementApiClient:
    return ManagementApiClient()


@lru_cache(maxsize=1)
def get_idempotency_client() -> IdempotencyClient:
    return IdempotencyClient()


@lru_cache(maxsize=1)
def get_step_functions_client() -> StepFunctionsClient:
    return StepFunctionsClient()


@lru_cache(maxsize=1)
def get_ssm_parameter_client() -> SsmParameterClient:
    return SsmParameterClient()


@lru_cache(maxsize=1)
def get_divergence_client() -> DivergenceClient:
    return DivergenceClient()


@lru_cache(maxsize=1)
def get_breaker_accessor() -> BreakerAccessor:
    return BreakerAccessor()


@lru_cache(maxsize=1)
def get_dlq_client() -> DlqClient:
    return DlqClient()


@lru_cache(maxsize=1)
def get_evidence_client() -> EvidenceClient:
    return EvidenceClient()


def get_findings_service(
    findings_client: FindingsClient = Depends(get_findings_client),
) -> FindingsService:
    return FindingsService(findings_client)


def get_decisions_service(
    decisions_client: DecisionsClient = Depends(get_decisions_client),
) -> DecisionsService:
    return DecisionsService(decisions_client)


def get_operations_service(
    faults_client: FaultsClient = Depends(get_faults_client),
    reports_client: ReportsClient = Depends(get_reports_client),
    divergence_client: DivergenceClient = Depends(get_divergence_client),
    breaker_accessor: BreakerAccessor = Depends(get_breaker_accessor),
    dlq_client: DlqClient = Depends(get_dlq_client),
) -> OperationsService:
    return OperationsService(
        faults_client, reports_client, divergence_client, breaker_accessor, dlq_client
    )


def get_reports_service(
    reports_client: ReportsClient = Depends(get_reports_client),
) -> ReportsService:
    return ReportsService(reports_client)


def get_evidence_service(
    evidence_client: EvidenceClient = Depends(get_evidence_client),
) -> EvidenceService:
    return EvidenceService(evidence_client)


def get_router_bridge_service(
    lambda_client: LambdaInvokeClient = Depends(get_lambda_invoke_client),
) -> RouterBridgeService:
    return RouterBridgeService(lambda_client, function_name=adapter_settings.router_function_name)


def get_chat_service(
    provider: LLMProvider = Depends(get_llm_provider),
    decisions_client: DecisionsClient = Depends(get_decisions_client),
) -> ChatService:
    return ChatService(provider=provider, decisions_client=decisions_client)


def get_approval_service(
    decisions_client: DecisionsClient = Depends(get_decisions_client),
    idempotency_client: IdempotencyClient = Depends(get_idempotency_client),
    step_functions_client: StepFunctionsClient = Depends(get_step_functions_client),
    ssm_client: SsmParameterClient = Depends(get_ssm_parameter_client),
    evidence_client: EvidenceClient = Depends(get_evidence_client),
) -> ApprovalService:
    return ApprovalService(
        decisions_client,
        idempotency_client=idempotency_client,
        step_functions_client=step_functions_client,
        ssm_client=ssm_client,
        evidence_client=evidence_client,
    )


@lru_cache(maxsize=1)
def get_stream_fanout_service() -> StreamFanoutService:
    """Plain composition, not a FastAPI `Depends()` chain: `ws/default.py`'s
    Lambda `handler()` is invoked directly by API Gateway WebSocket, never
    through `create_app()`'s FastAPI/Mangum request cycle (phase-02's three
    routes are their own Lambdas per §2, not REST proxy routes) -- so there
    is no per-request dependency graph for this to plug into.
    """
    return StreamFanoutService(
        provider=get_llm_provider(),
        decisions_client=get_decisions_client(),
        decisions_in_flight_client=get_decisions_in_flight_client(),
        management_client=get_management_client(),
    )
