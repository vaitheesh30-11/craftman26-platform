"""Prime's post-turn processing (phase-01 §4 step 3): compose a
`DecisionRecord`, sign+persist evidence, write it to DDB, and escalate
CRITICAL findings to SNS + Security Hub -- exactly once per turn.

Per docs/decisions/0013, this runs synchronously right after
`PrimeSupervisor` gets a completed turn back from `LLMProvider.invoke_agent`
(which already carries the Bedrock trace in `BedrockAgentResponse.trace`),
not as a separate EventBridge-triggered Lambda watching for a
speculative "Agent Trace Post-turn" custom event that phase-01 §4 step 3
itself flags as unverified ("implemented as a self-invoked action-group
placeholder if Bedrock trace stream is not enough -- verify... before
shipping"). The processing logic is identical either way; only the
trigger differs, and a real trigger decision needs a deployed agent to
inspect trace shapes against.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.decisions import DecisionsClient
from iam_sentinel_adapters.ddb.idempotency import IdempotencyClient
from iam_sentinel_adapters.evidence.client import EvidenceClient
from iam_sentinel_adapters.evidence.client import EvidenceRef as AdapterEvidenceRef
from iam_sentinel_adapters.security_hub.asff_mapper import AsffFindingInput, finding_to_asff
from iam_sentinel_adapters.security_hub.client import SecurityHubClient
from iam_sentinel_adapters.sns.client import SnsClient

from iam_sentinel_agents.contracts.decision import DecisionRecord
from iam_sentinel_agents.contracts.evidence import EvidenceRef as AgentsEvidenceRef
from iam_sentinel_agents.ids import new_ulid
from iam_sentinel_agents.prime.decision_composer import compose_status, has_critical_finding
from iam_sentinel_agents.settings import settings

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.finding import Finding
    from iam_sentinel_agents.contracts.query import SentinelQuery
    from iam_sentinel_agents.contracts.remediation import RemediationPlan
    from iam_sentinel_agents.contracts.verdict import SpecialistVerdict


class PrimePostTurnProcessor:
    def __init__(
        self,
        *,
        idempotency: IdempotencyClient | None = None,
        decisions: DecisionsClient | None = None,
        evidence: EvidenceClient | None = None,
        security_hub: SecurityHubClient | None = None,
        sns: SnsClient | None = None,
    ) -> None:
        self._idempotency = idempotency or IdempotencyClient()
        self._decisions = decisions or DecisionsClient()
        self._evidence = evidence or EvidenceClient()
        self._security_hub = security_hub or SecurityHubClient()
        self._sns = sns or SnsClient()

    def process(
        self,
        *,
        query: SentinelQuery,
        verdicts: list[SpecialistVerdict],
        narrative: str,
        remediations_proposed: list[RemediationPlan] | None = None,
        remediations_applied: list[RemediationPlan] | None = None,
    ) -> DecisionRecord | None:
        """Returns the composed `DecisionRecord`, or `None` if this
        `correlation_id` was already processed (idempotent replay --
        the caller must not re-run any side effect a second time).
        """
        if not self._idempotency.claim(query.correlation_id):
            return None

        status = compose_status(verdicts)
        critical = has_critical_finding(verdicts)
        findings: list[Finding] = [finding for verdict in verdicts for finding in verdict.findings]
        decided_at = datetime.now(UTC)

        # Evidence keys partition by a single `feature_id` (adapters/evidence/
        # keys.py). A multi-specialist turn has no one "true" owner, so the
        # first-invoked verdict's feature_id is used as the storage-path
        # grouping key -- it has no bearing on the record's own contents.
        primary_feature_id = verdicts[0].feature_id

        decision_id = new_ulid()
        evidence_body = {
            "decision_id": decision_id,
            "correlation_id": query.correlation_id,
            "principal": query.principal,
            "status": status,
            "narrative": narrative,
            "specialist_verdicts": [v.model_dump(mode="json") for v in verdicts],
        }
        evidence_ref = self._evidence.put_signed_evidence(
            kind="specialist_output",
            body=evidence_body,
            correlation_id=query.correlation_id,
            feature_id=primary_feature_id,
        )

        decision = DecisionRecord(
            decision_id=decision_id,
            correlation_id=query.correlation_id,
            principal=query.principal,
            query=query,
            specialist_verdicts=verdicts,
            findings=findings,
            remediations_proposed=remediations_proposed or [],
            remediations_applied=remediations_applied or [],
            status=status,
            narrative=narrative,
            evidence_ref=_to_agents_evidence_ref(evidence_ref),
            decided_at=decided_at,
        )

        self._decisions.put(
            {
                "decision_id": decision.decision_id,
                "correlation_id": decision.correlation_id,
                "principal": decision.principal,
                "status": decision.status,
                "narrative": decision.narrative,
                "decided_at": decision.decided_at.isoformat(),
            }
        )

        if critical:
            self._escalate_critical(decision, findings)

        return decision

    def _escalate_critical(self, decision: DecisionRecord, findings: list[Finding]) -> None:
        self._sns.publish_critical_finding(
            subject=f"IAM Sentinel: CRITICAL finding for {decision.principal}",
            message=decision.narrative,
        )
        asff_findings = [
            finding_to_asff(
                AsffFindingInput(
                    finding_id=finding.finding_id,
                    feature_id=finding.feature_id,
                    account_id=finding.account_id,
                    severity=finding.severity,
                    title=finding.title,
                    detail=finding.detail,
                    aws_doc_citation_quote=finding.aws_doc_citation.quote,
                    principal_arn=finding.principal_arn,
                    resource_arn=finding.resource_arn,
                ),
                region=settings.region,
                security_hub_account_id=settings.security_hub_account_id,
                updated_at=decision.decided_at.isoformat(),
            )
            for finding in findings
            if finding.severity == "CRITICAL"
        ]
        self._security_hub.import_findings(asff_findings)


def _to_agents_evidence_ref(ref: AdapterEvidenceRef) -> AgentsEvidenceRef:
    """Bridges adapters' `EvidenceRef` dataclass into the agents contract's
    frozen Pydantic `EvidenceRef` -- same fields, two separate types on
    either side of the module boundary (adapters never imports agents/).
    """
    return AgentsEvidenceRef(
        bucket=ref.bucket,
        key=ref.key,
        version_id=ref.version_id or "unversioned",
        kms_key_arn=ref.kms_key_arn,
        signature=ref.signature,
        sha256=ref.sha256,
        stored_at=ref.stored_at,
    )
