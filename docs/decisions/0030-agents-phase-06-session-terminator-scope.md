# ADR 0030 — agents phase-06: F5 Session Terminator scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-06-session-terminator.txt` is F5's spec: a Bedrock
Agent (`SessionTerminator`, Haiku 3.5) plus three Lambdas
(`session_kill_dispatch`, `session_kill_worker`, `session_kill_cleanup`)
that fan out an emergency `Deny *` inline policy, conditioned on
`aws:TokenIssueTime`, across every `AWSReservedSSO_*` role a compromised
permission set is assigned to, with TTL-driven auto-cleanup. Same shape of
gap as F1 (ADR 0015): the algorithmic core is buildable and testable
offline (moto-mocked IAM/SQS/DDB, injectable SSO Admin client), only a
handful of downstream integration points need a live AWS account, a
deployed Prime, or infrastructure this repo hasn't built yet. F5 is the
only specialist that writes to member accounts, so several of its own
spec's implementation details didn't survive contact with the real AWS
API surface. Six scoping/deviation decisions were made building this
phase.

## Decision

- **`sso-admin:ListAccountAssignments` cannot enumerate accounts on its
  own, contradicting §4 Step 2's pseudocode** ("ListAccountAssignments
  (InstanceArn, PermissionSetArn)" paginated, with no `AccountId`). The
  real API signature is `ListAccountAssignments(InstanceArn, AccountId,
  PermissionSetArn)` — scoped to one already-known account per call.
  `tools/f5/discovery.list_assignments` resolves this by calling
  `sso-admin:ListAccountsForProvisionedPermissionSet` first to get the
  account list, then fanning out `ListAccountAssignments` per account —
  callers still get one flat assignment list, matching what the spec's
  pseudocode implied the API already did.
- **Filtering discovery to one `principal_arn` cannot be done exactly.**
  `ListAccountAssignments` returns Identity Store `PrincipalId`s (opaque
  UUIDs), not ARNs, and resolving an ARN to a PrincipalId needs
  `identitystore:DescribeUser`/`DescribeGroup` — not present in §7's IAM
  policy for this Lambda's role, and not mentioned anywhere else in the
  spec. `list_assignments` matches only when the caller already passes a
  bare PrincipalId as `principal_arn`'s last path segment; true ARN
  resolution (adding `identitystore:Describe*` to the policy and wiring the
  lookup) is deferred to whichever phase actually needs a human to target
  one principal rather than a whole permission set.
- **Real bug fixed, not just worked around: §4 Step 2's own
  `MessageDeduplicationId=revocation_policy_name` would silently drop
  every message but the first.** SQS FIFO deduplication is scoped to the
  whole queue for a 5-minute window, not per `MessageGroupId` — reusing
  one dedup id across every fanned-out message (one `revocation_policy_name`
  per *invocation*, shared by every account/role in that invocation) means
  SQS treats messages 2..N as duplicates of message 1 and drops them,
  defeating the fan-out for every account after the first. `tools/f5/
  dispatch.py` scopes `MessageDeduplicationId` to
  `{revocation_policy_name}#{account_id}#{role_arn}` instead: unique per
  message, still traceable back to the revocation. Caught by
  `test_dispatch_sends_one_deduplicated_fifo_message_per_account`, which
  would fail (2 of 3 messages missing) against the spec's literal reading.
- **§4 Step 4's "extend TTL instead of cleaning" is implemented via the
  single-item-per-`(account_id, role_arn)` key `SentinelRevocations`
  already has** (docs/DATA_CONTRACTS.md §9), not a separate versioning
  scheme. A new dispatch on a role mid-revocation overwrites the DDB item
  forward (later `ttl_expires_at`, new `revocation_policy_name`);
  `session_kill_cleanup` re-reads each expired candidate immediately
  before deleting, and skips it if the live item no longer matches the
  snapshot it queried. Documented consequence, not silently accepted: the
  *superseded* policy's own `PolicyName` is never explicitly
  `iam:DeleteRolePolicy`'d, because the DDB row that named it is gone.
  This is harmless rather than merely deferred — every emergency Deny is a
  `DateLessThan` condition on `aws:TokenIssueTime`, so an orphaned earlier
  -cutoff Deny denies a *subset* of what the newer, later-cutoff Deny
  already denies; it can never re-permit anything, and it stops mattering
  once no live session predates its own cutoff.
- **Three adapters/ clients added on-demand, per ADR 0006's precedent**
  ("add on-demand per consumer" rather than pre-building unused surface):
  `sqs/client.py` (`SqsClient.send_fifo_message`, F5's first and only SQS
  caller), `ssm/client.py` (`SsmClient.get_string_list`, for the
  never-revoke denylist parameter — §5 SAFETY), and `ddb/revocations.py`
  (`RevocationsClient`, the `SentinelRevocations` table client §9
  describes but no phase had built yet). `adapters/pyproject.toml` gained
  the `sqs` boto3-stubs extra (`ssm` was already present, unused until
  now); `agents/pyproject.toml` gained `sso-admin` and `ssm`.
- **CDK wiring for `SessionTerminator`'s `CfnAgent`, its three Lambdas, and
  the three EventBridge trigger rules (GuardDuty filter, `DeleteAccount
  Assignment` event, `rate(1 minute)` cleanup schedule) is deferred, not
  built in this phase** — identical reasoning to ADR 0015's first bullet:
  `aws-infra/functions/layers/{boto3,powertools}/python/` are still empty
  placeholders, a repo-wide gap predating both F1 and F5. `aws-infra`
  already provisions `SessionKillQueue.fifo` + its DLQ and
  `SentinelRevocations` (`foundation_stack.py`), so the infrastructure
  side is ahead of the Lambda-packaging blocker, not behind it.

## Consequences

1. §9 "100-account org: p95 end-to-end ≤ 30s" — deferred; no deployed
   Lambdas or real org exist to benchmark against (same class of deferral
   as ADR 0015's 500-principal-scan criterion).
2. §9 "Zero occurrence of policy names not matching
   `SENTINEL_EMERGENCY_REVOKE_*`" — met by construction (`dispatch.py`
   generates the one name per invocation; nothing else names a policy).
3. §9 "Cleanup extends TTL when a newer revocation is live; never deletes
   an active one" — met; verified by
   `test_cleanup_extends_instead_of_deleting_when_a_newer_revocation_is_live`.
4. §9 "Every action produces a KMS-signed evidence blob and an ASFF
   finding" — code-complete (`worker.process_kill_message` calls both
   unconditionally on the success path); not independently re-verified
   against real KMS/Security Hub, per the same reasoning ADR 0015 applied
   to Prime's post-turn Finding flow.
5. §9 "Denylist enforced in unit tests with 5 adversarial fixtures" — met;
   `tests/unit/f5/test_denylist.py` (5 parametrized cases) plus
   `test_dispatch_excludes_denylisted_roles` proving enforcement end-to-end
   through `dispatch()`.
6. §8 "Eval: 20 golden turns" — scaled to 8 entries covering all five
   required categories (obvious-yes, obvious-no, tricky, adversarial-input,
   latency-sensitive), schema-checked only (`test_f5_golden_schema.py`) —
   `iam_sentinel_agents.evals.runner` (phase-12) doesn't exist yet and no
   deployed agent exists to run a turn against, same deferral as ADR 0015.
7. CDK deployment of `SessionTerminator` — deferred pending the same
   Lambda dependency-layer packaging decision ADR 0015 flagged; tracked in
   `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS, not silently dropped.
8. `list_terminations`' `accounts_targeted`/`accounts_completed` counters
   are actually role-level, not account-level (a permission set can have
   more than one matching `AWSReservedSSO_*` role per account in rare
   cases) — kept for continuity with the WORKFLOW step 3 field names the
   specialist prompt already references; noted here rather than silently
   treated as exact.
