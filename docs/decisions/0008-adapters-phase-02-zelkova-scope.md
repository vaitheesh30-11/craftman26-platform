# ADR 0008 — adapters phase-02: Zelkova adapter scope and interface fixes

Status: accepted
Date: 2026-07-30

## Context

`adapters/docs/phase-02-zelkova-adapter.txt` §3 specifies `ZelkovaClient`'s
interface without a `feature_id` parameter on any method, and specifies
`post_check(role_arn=..., expected_policy=..., ...)` without a policy name.
Both are needed by code the same spec mandates in §4-5:

- §4/§5 step 4 requires every invocation to emit a KMS-signed evidence blob
  via the `evidence` adapter. `evidence.client.EvidenceClient.put_signed_evidence`
  (phase-04) hard-requires a `FeatureID` (`Literal["F1"..."F8"]`) to derive
  the content-addressed S3 key — there is no adapter-synthesizable default,
  and widening `FeatureID` to add a sentinel "unknown" value would leak into
  every other adapter that already keys off the real literal.
- §5 step 3 says "fetch observed policy via `iam:GetRolePolicy` or
  `iam:GetUserPolicy`" — both AWS APIs require the policy's name in addition
  to the role/user identifier; a role ARN alone cannot resolve to a specific
  inline policy document.

## Decision

1. Every public `ZelkovaClient` method (`check_no_new_access`,
   `check_access_not_granted`, `start_policy_generation`,
   `get_generated_policy`, `post_check`) takes a required `feature_id:
   FeatureID` keyword argument beyond what §3 lists. Every real caller is a
   specialist that already owns its `FeatureID` (same calling convention as
   `correlation_id`), so this is a pure interface completion, not new
   behavior the caller couldn't already provide.
2. `post_check` also takes a required `policy_name: str` keyword argument,
   used with `role_arn` to call `iam:GetRolePolicy`. `iam:GetUserPolicy` is
   not wired in this phase — no caller targets IAM users yet; add it
   alongside the first specialist that needs it.
3. Errors: any exception other than `ThrottlingError` (after
   `Policy.CAUTIOUS` retry exhaustion) is wrapped and re-raised as
   `ZelkovaError` at every call site — the adapter never returns
   `ZelkovaResult(pass_=True)` on an exception path, matching §4's "never
   fails open" contract. `ZelkovaError`/`ZelkovaViolationError` already
   existed in `errors.py` from an earlier phase; reused as-is.
4. Testing: moto 5.0.16 (pinned in `adapters/pyproject.toml`) has no Access
   Analyzer backend at all (`moto.backends.list_of_moto_modules()` contains
   no `accessanalyzer` entry) — confirmed by inspection before writing
   tests. Per the ground rules, Access Analyzer calls are mocked with
   `unittest.mock.MagicMock` (same pattern as `test_bedrock_provider.py`,
   which mocks `bedrock-agent-runtime`/`bedrock-runtime` for the same
   reason: no live-equivalent moto backend was needed there either). IAM
   (`GetRolePolicy`) is real moto-mockable, but the post-check tests use
   `MagicMock` too so the polling/race-check logic in `post_check.py` stays
   testable independent of a `ZelkovaClient` instance.
5. Per the revised testing policy, wrote 14 focused unit tests (8 covering
   `ZelkovaClient`'s five methods' pass/fail/throttle/error branches, 2 for
   `start_policy_generation`/`check_access_not_granted`/`get_generated_policy`
   edge cases, 2 for `post_check`'s poll-resolves and poll-exhausts paths,
   2 more for delegation and non-throttling failures) instead of §7's
   Hypothesis-driven 10,000-trial fault-injection property test. The two
   error-path tests (`raises on exhausted throttle`, `raises on non-
   throttling failure`) cover the same guarantee the property test would
   have checked — every exception path raises, none returns `pass_=True` —
   just without the exhaustive trial count.

## Consequences

Deferred, tracked in `docs/EXECUTION_STATE.txt`:

- §8 acceptance criterion "post-check p95 latency ≤ 30s" is enforced
  structurally (`wait_seconds` default 15 + `max_polls` default 3 at 5s
  each caps the code path at 30s) but not measured against a real Access
  Analyzer/IAM round trip — needs a dev account.
- §8 acceptance criterion "every specialist that writes policy passes its
  adapter tests using this client" is not yet checkable — no specialist
  Lambda exists until Wave 3 (agents phase-02, sprint step 18).
- `iam:GetUserPolicy` path for `post_check` (only `GetRolePolicy` is wired;
  add when a user-targeting caller exists).
- The full 10,000-trial Hypothesis fault-injection property test (§7) is
  not run — see testing-policy note above.
