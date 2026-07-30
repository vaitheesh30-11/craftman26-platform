"""Exception hierarchy every adapter translates boto3 errors into.

Callers never see a raw `botocore.exceptions.ClientError`; each adapter
surface method maps it to one of these at the boundary (phase-00 §3).
"""

from __future__ import annotations


class SentinelAdapterError(Exception):
    """Base for every exception raised by the adapters package."""


class TransientError(SentinelAdapterError):
    """Retryable failure: the same call may succeed if retried."""


class ThrottlingError(TransientError):
    """AWS API throttled the request."""


class NetworkError(TransientError):
    """Connection-level failure reaching an AWS API."""


class NonRetryableError(SentinelAdapterError):
    """Failure that retrying will not fix; short-circuits every retry policy."""


class AccessDeniedError(NonRetryableError):
    """The caller's credentials lack permission for the requested action."""


class ValidationError(NonRetryableError):
    """The request was rejected as malformed by the AWS API or a local check."""


class GuardrailInterventionError(NonRetryableError):
    """A Bedrock Guardrail intervened; `stopReason == "guardrail_intervened"`."""


class ZelkovaError(SentinelAdapterError):
    """Base for Access Analyzer Zelkova adapter failures."""


class ZelkovaViolationError(ZelkovaError):
    """`CheckNoNewAccess` returned a witness counter-example."""


class BudgetExceededError(SentinelAdapterError):
    """A cost-meter check would push spend past its SSM-configured cap."""


class CircuitOpenError(SentinelAdapterError):
    """The named circuit breaker is open; the call was not attempted."""


class SanitizerRejection(SentinelAdapterError):  # noqa: N818 -- contract name, phase-00 §3
    """Untrusted input failed the prompt sanitizer's forbidden-pattern check."""


class PromptTooLargeError(SentinelAdapterError):
    """A composed prompt exceeded the Bedrock request-size accommodation cap."""


class EvidenceVerificationError(SentinelAdapterError):
    """Stored evidence failed KMS signature verification or is not valid JSON."""
