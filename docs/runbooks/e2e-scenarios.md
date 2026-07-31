# IAM Sentinel — Integration & E2E scenario catalog

Source of truth for scenario IDs/wording: `agents/docs/phase-13-integration-tests.txt`
§3. Machine-readable form: `agents/tests/e2e/runner.py::SCENARIOS`
(`tests/e2e/test_scenario_catalog.py` keeps the two in sync).

## Status legend

- **Real (moto/in-process)** — exercises real production code against a
  moto-mocked AWS surface (or a documented, precedented test double where
  moto has no coverage — see each test module's docstring). No live AWS
  account involved.
- **Deferred (needs Bedrock dev alias)** — the scenario's own criteria
  require a deployed Prime agent with all 8 specialists associated and a
  real `bedrock-agent-runtime:InvokeAgent` call. No dev AWS account exists
  yet (docs/decisions/0013, docs/decisions/0033). `runner.run_dev_alias`
  raises `DevAliasNotConfiguredError` rather than fabricating a pass.

| ID   | Name                                              | Feature | Status | Test |
|------|---------------------------------------------------|---------|--------|------|
| E-01 | Admin PassRole shortcut in target account         | F1      | Real (moto IAM + DDB/S3/SNS) | `tests/e2e/test_e01_passrole_critical_escalation.py` |
| E-02 | Access Analyzer false-positive suppression        | F2      | Real (fake Access Analyzer client, precedented) | `tests/e2e/test_e02_org_context_suppression.py` |
| E-03 | Least-privilege policy merge with S3 data events  | F3      | Real (pure computation, no AWS) | `tests/unit/f3/test_merge.py` |
| E-04 | Proposed SCP breaks CI/CD role                    | F4      | Real (pure computation, no AWS) | `tests/e2e/test_e04_scp_impact_cicd_break.py` |
| E-05 | GuardDuty-triggered SSO session kill              | F5      | Real (moto SQS/DDB, fake SSO client, precedented) | `tests/e2e/test_e05_session_kill_and_ttl_cleanup.py` |
| E-06 | Management account trail deletion attempt         | F6      | Real (unit-level; see `tests/unit/f6/`) | `tests/unit/f6/test_shadow_guard_scp_evaluator.py` |
| E-07 | SCP collision in a 4-level OU chain               | F7      | Real (moto Organizations) | `tests/e2e/test_e07_scp_collision_four_level_ou.py` |
| E-08 | Proposed SCP breaks Auto Scaling SLR              | F8      | Real (pure computation + post-turn round trip) | `tests/e2e/test_e08_slr_guardian_conflict.py` |
| E-09 | Prime multi-specialist orchestration (F1+F4)      | Prime   | Real (verdict composition + post-turn) — **not** a live Bedrock SUPERVISOR fan-out; see below | `tests/e2e/test_e09_prime_multi_specialist_orchestration.py` |
| E-10 | Prompt attempts to reveal system prompt (Prime)   | Prime   | Real (sanitizer) + structural (composer) | `tests/e2e/test_e10_prompt_injection_reveals_system_prompt.py` |
| E-11 | Zelkova witness on F3 merge — reflection loop     | F3      | Real (witness capture + composer escalation), reflection loop itself deferred | `tests/e2e/test_e11_zelkova_witness_reflection.py` |
| E-12 | Chaos: Bedrock throttled, DDB unavailable         | Prime   | Real (retry/circuit-breaker layer) | `tests/chaos/test_bedrock_throttled.py`, `tests/chaos/test_ddb_unavailable.py` |

## The one honest caveat that applies to E-09, E-10, E-11, E-12

Per docs/decisions/0013 (agents phase-01) and reaffirmed by docs/decisions/0033
(this phase): Sentinel Prime's own specialist routing/fan-out and its
mapping of a caught exception (sanitizer rejection, Guardrail intervention,
Zelkova failure) to an explicit `SpecialistVerdict` are Bedrock's
SUPERVISOR-mode model/prompt behavior, not a Python function this
repository owns or can unit-test in isolation. Every scenario above proves
the *real* code on both sides of that boundary — the tool/adapter layer
that produces the raw signal, and `decision_composer`/`PrimePostTurnProcessor`
that consumes an already-classified verdict — without fabricating the
model-layer mapping in between as if it were tested Python code.

## Running

```
cd agents
uv run pytest tests/e2e tests/chaos tests/contract tests/prompt_injection -q
```

No AWS credentials are required for any of the above — every AWS call is
either moto-mocked or a documented test double. `runner.run_dev_alias(...)`
is the only code path that would need real Bedrock dev-alias credentials,
and it refuses to run without `SENTINEL_PRIME_DEV_ALIAS_ID` set rather than
silently skipping or fabricating a pass.
