# Sentinel-IQ v8 — Data Contracts

Field-level specification of the four cross-service data contracts. Every producer and consumer MUST validate at both boundaries.

Legend: `req` required, `opt` optional. `enum(...)` values are closed sets. Length caps are inclusive.

## 1. `DiffArtifact`

Canonical drift representation produced by the Normalizer Lambda from a raw CloudTrail event or Config-aggregator backfill.

| Field | Type | Required | Validation |
|---|---|---|---|
| `schema_version` | string | req | Semver; MUST equal `"8.0.0"` at v8 launch |
| `evidence_id` | string | req | ULID prefixed `ev_`; unique across evidence lake |
| `canonical_key` | string | req | `sha256(resource_arn ‖ change_hash ‖ actor_arn ‖ five_minute_window)` |
| `produced_at` | RFC 3339 datetime | req | Normalizer wall clock at write time |
| `resource_arn` | string | req | Full AWS ARN of the affected resource |
| `drift_surface` | enum | req | `IAMIdentityPolicy` \| `SCP` \| `PermissionBoundary` \| `TrustPolicy` \| `ResourcePolicy` \| `IdentityCenterPermissionSet` |
| `drift_type` | enum | req | `Addition` \| `Removal` \| `Modification` \| `ScopeExpansion` \| `ScopeContraction` \| `TrustWidening` \| `WildcardIntroduction` \| `CrossAccountIntroduction` \| `PublicExposure` |
| `actor_arn` | string | req | Full ARN of the change-making identity from CloudTrail `userIdentity` |
| `actor_identity_kind` | enum | req | `IAMUser` \| `IAMRole` \| `AssumedRole` \| `Root` \| `ServiceLinkedRole` \| `Unknown` |
| `actor_is_automation` | bool | req | True if `actor_arn` matches registered automation-envelope registry |
| `actor_on_call` | bool | req | True if the identity matches the on-call registry at the change timestamp |
| `baseline_hash` | string | req | Hash of the baseline entry the diff was computed against |
| `change_diff` | object | req | `{ "before": <policy-json>, "after": <policy-json>, "unified_diff": <string, max 100_000> }` |
| `scp_bytes_size` | int (≥0) | opt | Set ONLY when `drift_surface == "SCP"` and reflects the observed/candidate SCP size in bytes |
| `criticality_tier` | enum | req | `tier0` \| `tier1` \| `tier2` \| `tier3` \| `unknown` |
| `account_id` | string | req | 12-digit AWS account id |
| `region` | string | opt | Region if regional resource, otherwise omit |

### Invariants

- If `drift_surface == "SCP"` then `scp_bytes_size` MUST be present.
- If `criticality_tier == "tier0"` then Rule R5 MUST route `Escalate` for structural high-severity patterns, never `RequestApproval`.
- `canonical_key` is idempotent: repeat writes for the same underlying change MUST produce the same key so the Normalizer can dedup.

## 2. `SpecialistVerdict`

Structured output of a single specialist agent (IIA, CSA, BRA, CAA). Discriminated by `agent_id`. Agent-specific structured findings live under `structured_findings`.

| Field | Type | Required | Validation |
|---|---|---|---|
| `schema_version` | string | req | Semver |
| `agent_id` | enum | req | `IIA` \| `CSA` \| `BRA` \| `CAA` |
| `decision_id` | string | req | The DecisionRecord id this verdict feeds into |
| `produced_at` | RFC 3339 datetime | req | Agent wall clock at emit |
| `confidence` | float | req | Range [0.0, 1.0] |
| `rationale` | string | req | Max 2,000 chars; MUST reference evidence, not tenant strings |
| `cited_evidence_ids` | list[string] | req | Every entry MUST appear verbatim in the sanitized input |
| `structured_findings` | object | req | Agent-specific per section 2.1-2.4 |
| `latency_ms` | int (≥0) | req | Total agent runtime |
| `model_used` | enum | opt | `haiku` \| `sonnet`; agents record Bedrock model actually used |
| `guardrail_intervened` | bool | opt | True if the Guardrail intervened and the conservative default was returned |

### 2.1 IIA `structured_findings`

| Sub-field | Type | Required | Validation |
|---|---|---|---|
| `verdict` | enum | req | `aligned` \| `ambiguous` \| `violated` |
| `intent_reference_ids` | list[string] | opt | Baseline annotation ids the agent leaned on |

Conservative-default failure state: `verdict = "violated"`, `confidence = 0.0`.

### 2.2 CSA `structured_findings`

| Sub-field | Type | Required | Validation |
|---|---|---|---|
| `coherence_score` | float [0..1] | req | 1.0 means signals fully cohere; 0.0 means all signals missing |
| `key_facts` | list[string] | req | Each ≤ 300 chars |
| `contradictions` | list[string] | req | Each ≤ 300 chars |
| `missing_signals` | list[string] | req | Enum values: `IncidentState`, `ChangeWindow`, `OnCallIdentity`, `DeployState`, `OwnerTag`, `EnvTag`, `CriticalityTier` |

Conservative-default failure state: `coherence_score = 0.0`, `missing_signals = ["all"]`.

### 2.3 BRA `structured_findings`

| Sub-field | Type | Required | Validation |
|---|---|---|---|
| `aws_reachable_impact` | object | req | `{ principals: int≥0, resources: int≥0, cross_account: bool, public_exposure: bool }` |
| `runbook_cited_impact` | list[object] | req | Each `{ runbook_id, fragment (verbatim, ≤ 2000 chars), relevance ∈ [0..1] }` |
| `overall_severity` | enum | req | `low` \| `medium` \| `high` \| `critical` |
| `rollback_safety` | enum | req | `safe` \| `caution` \| `unsafe` |

Conservative-default failure state: `overall_severity = "critical"`, `rollback_safety = "unsafe"`.

### 2.4 CAA `structured_findings`

| Sub-field | Type | Required | Validation |
|---|---|---|---|
| `controls_affected` | list[object] | req | Each `{ framework: string, control_id: string, delta: string (≤1000) }` |
| `scope_change` | enum | req | `none` \| `expansion` \| `contraction` \| `unknown` |
| `audit_notes` | list[string] | opt | Each ≤ 500 chars |

Conservative-default failure state: `scope_change = "unknown"`, `controls_affected = []`.

### Global invariants

- Every string in `cited_evidence_ids` MUST appear verbatim in the sanitized input set (the Bedrock output validator rejects forgeries).
- No tenant-controlled strings may appear inside `rationale` without being present in `cited_evidence_ids`.
- `latency_ms` MUST be ≤ agent's SLO (IIA/CAA 2000, CSA 3000, BRA 5000). Values above SLO are permitted but must be alarmed.

## 3. `DecisionRecord`

Final signed decision produced by the Governance Council orchestrator.

| Field | Type | Required | Validation |
|---|---|---|---|
| `schema_version` | string | req | Semver |
| `decision_id` | string | req | ULID prefixed `dec_`; unique |
| `produced_at` | RFC 3339 datetime | req | Council wall clock at sign time |
| `diff_artifact_evidence_id` | string | req | Foreign key to `DiffArtifact.evidence_id` |
| `rule_that_matched` | string | opt | e.g. `"R1"`; `null` if Council path was taken |
| `council_invoked` | bool | req | True when Council orchestrator produced this record |
| `action` | enum | req | `NoOp` \| `LogAndMonitor` \| `ProposeBaselineUpdate` \| `RequestApproval` \| `Escalate` \| `AutoRemediate` |
| `chosen_strategy` | enum | opt | `Rollback` \| `TightenDifferently` \| `ProposeBaselineUpdate` \| `AddExceptionWindow` \| `RequestApproval` \| `Escalate` \| `NoOp` |
| `rationale` | string | req | Max 4,000 chars; MUST cite `cited_evidence_ids` |
| `cited_evidence_ids` | list[string] | req | Every entry MUST appear in the sanitized input set OR reference an existing evidence artifact |
| `overall_confidence` | float | req | Range [0.0, 1.0]; diagnostic only; NOT a gate on `action` |
| `dissenting_opinions` | list[object] | req | Each `{ agent: enum, verdict_summary: string ≤1000, why_not_chosen: string ≤1000 }` |
| `council_model` | enum | opt | `haiku` \| `sonnet`; recorded ONLY when `council_invoked == true` |
| `dissent_rate` | float | opt | Fraction of specialists disagreeing with the recommended action; range [0..1] |
| `remediation_plan_ref` | string | opt | S3 URI of the KMS-signed remediation plan (required when `action == "AutoRemediate"`) |
| `rollback_plan_ref` | string | opt | S3 URI of the KMS-signed rollback plan (required when `action == "AutoRemediate"`) |
| `zelkova_pre_check_ref` | string | opt | S3 URI of the pre-check output (required when `action == "AutoRemediate"`) |
| `kms_signature` | string | req | Base64-encoded KMS asymmetric signature over the canonicalized record body |

### Invariants

- Rule R0 (missing context) or Rule R5 (structural high-severity) fires ⇒ `action ∈ {RequestApproval, Escalate}`. Council MUST NOT emit `AutoRemediate` in these branches.
- Rule R6 fires ⇒ `zelkova_pre_check_ref` MUST be populated.
- `action == "AutoRemediate"` ⇒ `remediation_plan_ref` AND `rollback_plan_ref` AND `zelkova_pre_check_ref` all populated.
- `council_invoked == false` ⇒ `dissenting_opinions == []`.
- `council_model == "sonnet"` ⇒ `dissent_rate > 0.5`.
- `kms_signature` MUST verify against the current baseline signer public key at read time.

## 4. `IntentBaseline`

Customer-provided, signed enterprise Security Intent baseline.

| Field | Type | Required | Validation |
|---|---|---|---|
| `schema_version` | string | req | Semver |
| `intent_id` | string | req | Deterministic hash of the canonicalized body |
| `intent_version` | string | req | Semver; MUST strictly increase across successive updates |
| `approved_at` | RFC 3339 datetime | req | Time of two-signer approval |
| `approved_by` | list[string] | req | Min 2 distinct identities |
| `approval_artifact_ref` | string | req | S3 URI of the approval ticket (Change Manager or ServiceNow) |
| `scps` | list[object] | req | Each `{ policy_arn?, target_arn, canonical_hash, policy_document }` |
| `iam_policies` | list[object] | req | Same shape as `scps` |
| `permission_boundaries` | list[object] | req | Same shape |
| `trust_policies` | list[object] | req | Same shape |
| `resource_policies` | object[string, list[object]] | req | Keyed by service (`s3`, `kms`, `sns`, `sqs`, `lambda`, `ecr`, `secretsmanager`) |
| `identity_center_permission_sets` | list[object] | req | Each `{ permission_set_arn, target_accounts, canonical_hash, policy_document }` |
| `exception_windows` | list[object] | opt | Each `{ window_id, starts_at, ends_at, allows: [{ resource_arn, action_pattern, reason }] }` |
| `business_context` | object | req | `{ account_ownership: {accountId: ownerId}, environment_tags: [string], compliance_scope: {accountId: [framework]}, criticality_tiers: {tier: [accountId]} }` |
| `risk_appetite` | object | req | `{ auto_remediate_allowed: bool, max_blast_radius: enum('single-account','single-ou','organization') }` |
| `break_glass_procedures` | object | req | `{ issuer_role_arn, two_signer_required: bool, ttl_seconds: int (60..3600) }` |
| `approval_workflows` | object[string, string] | opt | Map from drift class → ApprovalProvider workflow id |
| `kms_signature` | string | req | KMS asymmetric signature over canonicalized body |

### Invariants

- `approved_by.length >= 2` and all identities distinct.
- Every `policy_document` MUST be a valid AWS IAM / Organizations policy JSON.
- For every account listed in `business_context.criticality_tiers.tier0`, `risk_appetite.max_blast_radius` MUST NOT permit `organization`.
- `intent_id` MUST equal `sha256(canonicalize(body without kms_signature))`.
- `kms_signature` MUST verify against the baseline signer public key configured in the security stack.
- Updates MUST pass a Zelkova regression check: `CheckNoNewAccess(new_baseline, prior_baseline)` MUST NOT return a widening witness, unless explicitly approved via a "scope-expansion" workflow that requires additional signers.

## 5. Canonicalization

Signatures are computed over the canonical JSON form:
- Keys sorted lexicographically.
- Whitespace stripped between tokens.
- UTF-8 encoded.
- Numeric values in shortest-round-trip form.

Producers MUST canonicalize before signing. Consumers MUST canonicalize before verifying.

## 6. Schema Parity

Every contract here has (or will have) a corresponding language-specific declaration under the module that consumes it. When Codex or an AI tool generates the code, it MUST derive from this document, not from any existing partial declaration in the repository.

## 7. Backwards Compatibility

Additive changes bump the schema minor version and are backward compatible: new optional fields are ignored by older consumers. Breaking changes bump the schema major version and require a coordinated producer/consumer deploy plan tracked in `docs/EPICS_AND_STORIES.md`.
