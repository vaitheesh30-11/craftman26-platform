# IAM Sentinel — Data Contracts

Canonical schemas for every producer→consumer boundary. Every producer validates before send; every consumer validates on receive. Contract drift is a P0 bug.

All schemas are Pydantic v2 (`from __future__ import annotations`, `from pydantic import BaseModel, Field, ConfigDict`).

## Common Types

```python
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, AwareDatetime

FeatureID = Literal["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]
Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
Verdict = Literal["CONFIRM", "REJECT", "ESCALATE", "INCONCLUSIVE", "REMEDIATED"]

class Base(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )
```

## 1. `SentinelQuery`

The user-facing entry contract for API Gateway and CLI.

```python
class SentinelQuery(Base):
    correlation_id: str = Field(pattern=r"^01[0-9A-HJKMNP-TV-Z]{24}$")   # ULID
    principal: str                                                        # authenticated IAM ARN
    query_text: str = Field(min_length=1, max_length=4096)
    hints: dict[str, str] = Field(default_factory=dict)                   # optional filters
    include_arns_in_output: bool = False
    submitted_at: AwareDatetime
```

`hints` may include `account_id`, `principal_arn`, `permission_set_arn`, `feature_id`. Prime uses hints as routing shortcuts but is not required to honor them.

## 2. `SpecialistTask`

Supervisor → Specialist handoff, encoded into the Bedrock collaborator invocation input.

```python
class UntrustedContextBlock(Base):
    type: str = Field(min_length=1, max_length=64)
    body: str = Field(max_length=32_768)

class SpecialistTask(Base):
    correlation_id: str
    feature_id: FeatureID
    tool_hint: Optional[str] = None
    trusted_input: dict[str, object]
    untrusted_context: list[UntrustedContextBlock] = Field(default_factory=list)
    retry_count: int = Field(ge=0, le=2)
```

`trusted_input` is passed through the XML fencer's `<trusted_input>` region. Each block in `untrusted_context` becomes a `<untrusted_context type="…">` region. Sanitizer runs on every string in both regions before serialization.

## 3. `SpecialistVerdict`

Specialist → Supervisor return. Every specialist MUST return exactly this shape. Prime rejects anything else.

```python
class ToolInvocation(Base):
    tool_name: str
    input_hash: str                                # sha256 of canonicalized input
    output_hash: str                               # sha256 of canonicalized output
    duration_ms: int = Field(ge=0)
    zelkova_check: Optional["ZelkovaCheck"] = None

class SpecialistVerdict(Base):
    correlation_id: str
    feature_id: FeatureID
    verdict: Verdict
    reason: str = Field(min_length=1, max_length=2048)
    findings: list["Finding"] = Field(default_factory=list)
    remediation: Optional["RemediationPlan"] = None
    tool_invocations: list[ToolInvocation] = Field(default_factory=list)
    duration_ms: int = Field(ge=0)
```

Rule: if `verdict == "CONFIRM"` and the specialist writes to any AWS resource, `remediation` MUST be present and MUST include a valid Zelkova `pass_=True` in every tool invocation that mutated policy.

## 4. `Finding` (universal)

Every specialist emits Findings through this shape. Findings are the persisted output of the platform.

```python
class AwsDocCitation(Base):
    gap_id: FeatureID
    quote: str = Field(min_length=1, max_length=1024)
    source: str = Field(min_length=1, max_length=256)
    url: str = Field(pattern=r"^https://docs\.aws\.amazon\.com/.+")
    retrieved_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

class Finding(Base):
    finding_id: str                                     # ULID
    feature_id: FeatureID
    account_id: str = Field(pattern=r"^\d{12}$")
    principal_arn: Optional[str] = None
    resource_arn: Optional[str] = None
    severity: Severity
    title: str = Field(min_length=1, max_length=256)
    detail: str = Field(min_length=1, max_length=8192)
    aws_doc_citation: AwsDocCitation
    payload: dict[str, object] = Field(default_factory=dict)
    detected_at: AwareDatetime
    expires_at: Optional[AwareDatetime] = None
    evidence_ref: Optional["EvidenceRef"] = None
```

Validators:
- `aws_doc_citation.quote` MUST exist verbatim in the ingested KB corpus (checked by a shared validator that hashes the quote against the KB manifest).
- `severity == "CRITICAL"` implies `principal_arn is not None`.
- `payload` is feature-scoped; per-feature payload schemas live in each phase doc under §Contracts.

## 5. `RemediationPlan`

Attached to Findings that propose a mutation.

```python
class ZelkovaCheck(Base):
    pass_: bool = Field(alias="pass")
    witness: Optional[str] = None
    latency_ms: int
    invoked_at: AwareDatetime
    baseline_hash: str
    candidate_hash: str

class RemediationPlan(Base):
    action: Literal[
        "attach_inline_policy",
        "detach_inline_policy",
        "update_scp",
        "archive_finding",
        "enable_cloudtrail_data_events",
        "auto_generate_policy",
    ]
    target_arn: str
    policy_document: Optional[dict[str, object]] = None
    ttl_seconds: Optional[int] = Field(default=None, ge=60, le=86_400 * 30)
    dry_run: bool = True
    zelkova_pre: Optional[ZelkovaCheck] = None
    zelkova_post: Optional[ZelkovaCheck] = None
```

Contract: `dry_run=False` requires `zelkova_pre.pass_ is True`. Application requires `zelkova_post.pass_ is True` within 3 poll iterations of a 15-second wait each.

## 6. `EvidenceRecord` / `EvidenceRef`

Canonicalized (RFC 8785 JCS), KMS-signed, S3-Object-Lock-persisted.

```python
class EvidenceRef(Base):
    bucket: str
    key: str                                       # content-addressed
    version_id: str
    kms_key_arn: str
    signature: str                                 # base64 RSASSA_PSS_SHA_256
    sha256: str
    stored_at: AwareDatetime

class EvidenceRecord(Base):
    ref: EvidenceRef
    kind: Literal[
        "specialist_input",
        "specialist_output",
        "zelkova_invocation",
        "policy_mutation",
        "guardrail_intervention",
    ]
    correlation_id: str
    feature_id: FeatureID
    body: dict[str, object]
```

## 7. `DecisionRecord`

Prime's synthesis. Written to `SentinelDecisions` DDB table. Sent to Security Hub as ASFF.

```python
class DecisionRecord(Base):
    decision_id: str                               # ULID
    correlation_id: str
    principal: str                                 # invoking human ARN
    query: SentinelQuery
    specialist_verdicts: list[SpecialistVerdict] = Field(min_length=1, max_length=8)
    findings: list[Finding] = Field(default_factory=list)
    remediations_proposed: list[RemediationPlan] = Field(default_factory=list)
    remediations_applied: list[RemediationPlan] = Field(default_factory=list)
    status: Literal["ANSWERED", "ESCALATED", "AUTO_REMEDIATED", "REJECTED"]
    narrative: str = Field(min_length=1, max_length=16_384)  # Prime's prose
    evidence_ref: EvidenceRef
    decided_at: AwareDatetime
```

## 8. Feature-Specific Payload Schemas (Index)

Per-feature payload subtypes live in the feature phase docs. The index below is authoritative:

| Feature | Payload class            | Defined in                                    |
|---------|--------------------------|-----------------------------------------------|
| F1      | `PassRoleBlastPayload`   | `agents/docs/phase-02-passrole-cartographer.txt` |
| F2      | `OrgContextPayload`      | `agents/docs/phase-03-org-context-validator.txt` |
| F3      | `DataEventPolicyPayload` | `agents/docs/phase-04-data-event-enricher.txt`   |
| F4      | `ScpImpactPayload`       | `agents/docs/phase-05-scp-impact-analyst.txt`    |
| F5      | `SessionKillPayload`     | `agents/docs/phase-06-session-terminator.txt`    |
| F6      | `ShadowViolationPayload` | `agents/docs/phase-07-shadow-guard.txt`          |
| F7      | `ScpCollisionPayload`    | `agents/docs/phase-08-collision-resolver.txt`    |
| F8      | `SlrImpactPayload`       | `agents/docs/phase-09-slr-guardian.txt`          |

Each payload class extends `Base` with `extra="forbid"`, adds feature-specific fields, and is validated at both producer and consumer.

## 9. DDB Storage Shapes

### `SentinelFindings`
- PK: `account_id#feature_id`
- SK: `finding_id#detected_at`
- GSI1 PK: `severity`; SK: `detected_at`
- GSI2 PK: `feature_id`; SK: `status#detected_at`
- Attributes: full `Finding` JSON in `body`, `evidence_ref`, `expires_at` (TTL).

### `SentinelDecisions`
- PK: `principal`
- SK: `decided_at`
- Attributes: full `DecisionRecord` JSON in `body`.

### `SentinelPolicies` (cache)
- PK: `org_id`
- SK: `policy_arn`
- Attributes: `policy_document`, `attached_targets`, `cached_at`, `ttl` (15 min TTL).

### `SentinelSLRs`
- PK: `service_principal`
- Attributes: `slr_name`, `required_actions` (list), `source`, `last_updated`.

### `SentinelRevocations` (F5)
- PK: `account_id`
- SK: `role_arn`
- Attributes: `revocation_policy_name`, `token_issue_time`, `ttl_expires_at` (TTL), `reason`, `operator_arn`.

## 10. Contract Change Policy

- All schema changes go through a PR that (a) updates this document, (b) increments a `schema_version` field in every affected model, (c) provides a Pydantic v2 `model_validator` for legacy versions during a two-week grace window.
- Removing a field is a breaking change; adding an optional field with a default is not.
- Consumers MUST tolerate unknown fields being present after grace-window sunset.
