# Sentinel-IQ v8 — API Specification

Complete REST and WebSocket contract for the management API exposed by `backend/`. Frontend, agent runners, and third-party integrators MUST validate against this document. Data models referenced here are defined in `docs/DATA_CONTRACTS.md`.

## Conventions

- Base URL: `https://<host>/api/v1`
- Content type: `application/json; charset=utf-8`
- Timestamps: RFC 3339 UTC (`2026-07-25T18:03:22.113Z`)
- Pagination: cursor-based via `?cursor=<opaque>&limit=<1..200>`
- Authentication: AWS SigV4 or Cognito bearer token per `Authorization: Bearer <jwt>`
- All error responses share the envelope defined in section 8

## 1. `GET /api/v1/drift`

List real-time IAM/SCP drift, most recent first.

### Query parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `cursor` | string | no | Opaque cursor from a previous response `nextCursor` |
| `limit` | int (1..200) | no | Default 50 |
| `severity` | `low`\|`medium`\|`high`\|`critical` | no | Filter by BRA-reported severity |
| `driftSurface` | enum | no | `IAMIdentityPolicy`\|`SCP`\|`PermissionBoundary`\|`TrustPolicy`\|`ResourcePolicy`\|`IdentityCenterPermissionSet` |
| `accountId` | string | no | AWS account 12-digit ID |
| `since` | RFC 3339 timestamp | no | Return items with `producedAt >= since` |

### Response 200

```json
{
  "items": [
    {
      "diffArtifact": { "…DiffArtifact…": true },
      "latestDecisionId": "dec_01HABCXYZ...",
      "latestAction": "AutoRemediate"
    }
  ],
  "nextCursor": "opaque-string-or-null"
}
```

### Error codes

`400` invalid query, `401` unauthenticated, `403` insufficient scope, `500` upstream error.

## 2. `GET /api/v1/drift/{id}`

Deep-dive on a single drift, including all agent verdicts and the final decision.

### Path parameters

| Name | Type | Description |
|---|---|---|
| `id` | string | `DiffArtifact.evidence_id` |

### Response 200

```json
{
  "diffArtifact": { "…DiffArtifact…": true },
  "specialistVerdicts": [
    { "…SpecialistVerdict[IIA]…": true },
    { "…SpecialistVerdict[CSA]…": true },
    { "…SpecialistVerdict[BRA]…": true },
    { "…SpecialistVerdict[CAA]…": true }
  ],
  "decision": { "…DecisionRecord…": true },
  "zelkovaPreCheck": { "pass": true, "witness": null },
  "zelkovaPostCheck": { "pass": true, "witness": null },
  "actionRecord": { "appliedAt": "…", "verifiedAt": "…", "rollbackPlanRef": "s3://…" }
}
```

### Error codes

`404` unknown id, `401`, `403`, `500`.

## 3. `GET /api/v1/decisions`

Historical DecisionRecords feed.

### Query parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `cursor` | string | no | Cursor |
| `limit` | int (1..200) | no | Default 50 |
| `action` | enum | no | `NoOp`\|`LogAndMonitor`\|`ProposeBaselineUpdate`\|`RequestApproval`\|`Escalate`\|`AutoRemediate` |
| `councilInvoked` | bool | no | Filter to Council-decided cases only |
| `dissentGteRate` | float 0..1 | no | Filter to cases where `dissent_rate >= value` |

### Response 200

```json
{
  "items": [ { "…DecisionRecord…": true } ],
  "nextCursor": "opaque-string-or-null"
}
```

## 4. `POST /api/v1/decisions/{id}/approve`

Human-in-the-loop confirmation or override for a `RequestApproval` decision.

### Path parameters

| Name | Type | Description |
|---|---|---|
| `id` | string | `DecisionRecord.decision_id` |

### Request body

```json
{
  "outcome": "approve" | "reject",
  "approverIdentity": "arn:aws:sts::123456789012:assumed-role/SecurityApprover/alice",
  "justification": "PCI scope reviewed; rollback safe per BRA",
  "callbackToken": "<Step Functions callback token from the RequestApproval flow>",
  "twoSignerCorroboration": {
    "secondSigner": "arn:aws:sts::123456789012:assumed-role/SecurityApprover/bob",
    "corroboratedAt": "2026-07-25T18:12:00Z"
  }
}
```

Notes:
- `twoSignerCorroboration` is required when the DecisionRecord's affected resource is Tier-0 OR when the action would modify Sentinel-IQ's own resources (which is denied by SCP anyway but the API rejects the request early).
- `justification` max length 2,000.

### Response 200

```json
{
  "decisionId": "dec_01HABCXYZ",
  "resolutionState": "resolved",
  "resumingStepFunctions": true,
  "workflowExecutionArn": "arn:aws:states:…"
}
```

### Error codes

`400` invalid body, `401`, `403`, `404` unknown decision, `409` decision already resolved, `410` callback token expired, `422` two-signer corroboration missing for Tier-0, `500`.

## 5. `GET /api/v1/baselines`

Return currently active Security Intent baselines and version history.

### Query parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `includeHistory` | bool | no | Default false. When true, returns all prior signed versions |
| `limit` | int | no | Number of history entries; default 20 |

### Response 200

```json
{
  "active": { "…IntentBaseline…": true },
  "history": [ { "intentId": "…", "intentVersion": "…", "approvedAt": "…", "approvedBy": ["…","…"] } ]
}
```

## 6. `POST /api/v1/baselines`

Upload a signed baseline update.

### Request body

```json
{
  "baseline": { "…IntentBaseline…": true },
  "changeManagerTicketRef": "arn:aws:ssm-change:…",
  "twoSignerApprovals": [
    { "approver": "arn:aws:sts::…:assumed-role/SecurityLead/alice",  "signedAt": "…" },
    { "approver": "arn:aws:sts::…:assumed-role/SecurityLead/bob",    "signedAt": "…" }
  ]
}
```

### Response 202

```json
{
  "intentId": "b_01HAB…",
  "intentVersion": "8.1.2",
  "acceptedAt": "2026-07-25T18:12:00Z",
  "activationScheduledAt": "2026-07-25T18:14:00Z",
  "zelkovaBaselineRegressionCheck": {
    "state": "pending",
    "expectedCompletionAt": "2026-07-25T18:13:30Z"
  }
}
```

### Error codes

`400` invalid schema, `401`, `403`, `409` version conflict with active baseline, `422` KMS signature verification failed, `422` two-signer corroboration missing, `500`.

## 7. WebSocket — `/ws/drift`

Real-time event stream for the governance dashboard.

### Connection handshake

Client connects with:
- `Authorization` header carrying a Cognito JWT (preferred) OR SigV4 signed URL.
- Query parameter `?subscribeTo=DRIFT_DETECTED,DECISION_EMITTED,REMEDIATION_COMPLETE,VERIFICATION_FAILED` (optional; default subscribes to all).

Server responds with `101 Switching Protocols` on success. On auth failure, connection is closed with WebSocket close code `4401`.

### Keepalive

Server sends `{"type":"PING","serverTime":"<iso8601>"}` every 30 seconds. Client MUST respond with `{"type":"PONG","clientTime":"<iso8601>"}` within 10 seconds. Missed pong → server closes with close code `4408`.

### Event frames

All frames share the envelope:

```json
{
  "type": "DRIFT_DETECTED" | "DECISION_EMITTED" | "REMEDIATION_COMPLETE" | "VERIFICATION_FAILED" | "PING" | "PONG",
  "eventId": "evt_01HAB…",
  "timestamp": "2026-07-25T18:12:00.123Z",
  "payload": { … }
}
```

#### `DRIFT_DETECTED`

Emitted when the Normalizer writes a NormalizedChange.

```json
{
  "type": "DRIFT_DETECTED",
  "eventId": "evt_…",
  "timestamp": "…",
  "payload": {
    "diffArtifact": { "…DiffArtifact…": true }
  }
}
```

#### `DECISION_EMITTED`

Emitted when the Council or the deterministic fast path signs a DecisionRecord.

```json
{
  "type": "DECISION_EMITTED",
  "eventId": "evt_…",
  "timestamp": "…",
  "payload": {
    "decision": { "…DecisionRecord…": true },
    "specialistVerdicts": [ { "…SpecialistVerdict…": true } ]
  }
}
```

#### `REMEDIATION_COMPLETE`

Emitted after Zelkova post-check passes on an AutoRemediate.

```json
{
  "type": "REMEDIATION_COMPLETE",
  "eventId": "evt_…",
  "timestamp": "…",
  "payload": {
    "decisionId": "dec_…",
    "appliedAt": "…",
    "verifiedAt": "…",
    "iterations": 1,
    "actionRecordRef": "s3://sentineliq-evidence/…"
  }
}
```

#### `VERIFICATION_FAILED`

Emitted when Zelkova post-check fails on all 3 polling iterations and the rollback plan is executed.

```json
{
  "type": "VERIFICATION_FAILED",
  "eventId": "evt_…",
  "timestamp": "…",
  "payload": {
    "decisionId": "dec_…",
    "failureReason": "ZelkovaWitnessOfWidening",
    "witness": { "principal": "…", "action": "…", "resource": "…" },
    "rollbackExecuted": true,
    "rollbackState": "success" | "failure",
    "pagerDutyIncidentRef": "…"
  }
}
```

## 8. Error Envelope

All non-2xx REST responses:

```json
{
  "error": {
    "code": "InvalidQueryParameter" | "Unauthenticated" | "Forbidden" | "NotFound" |
            "Conflict" | "Gone" | "UnprocessableEntity" | "Internal",
    "message": "Human-readable summary",
    "requestId": "req_01HAB…",
    "details": { … optional field-specific error info … }
  }
}
```

Client-visible codes are stable; internal codes are logged with `requestId` for correlation.

## 9. Rate Limits

- Default per-account: 100 req/s burst 200 for GET endpoints; 10 req/s for POST endpoints.
- WebSocket: 1 open connection per authenticated identity per browser session.
- Exceeded: `429 TooManyRequests` with `Retry-After` header (seconds).

## 10. Versioning

Path-versioned (`/api/v1/…`). Non-breaking additive changes bump minor field-level version headers (`X-API-Minor: 3`). Breaking changes require `/api/v2/…` and a deprecation window announced through the ApprovalProvider channel.
