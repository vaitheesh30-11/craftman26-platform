"""E2E scenario catalog + dev-alias runner scaffolding (phase-13 §4 Step 2).

`SCENARIOS` is the machine-readable form of the 12-scenario table in
`agents/docs/phase-13-integration-tests.txt` §3 -- `docs/runbooks/
e2e-scenarios.md` is generated from (and kept in sync with) this list by
`test_scenario_catalog.py`.

`run_dev_alias` is the real Step 2 ask: `bedrock-agent-runtime:InvokeAgent`
against Prime's dev alias, enableTrace=True, asserting the scenario's
structural criteria against the real trace. It is intentionally not
implemented against a live client here: no dev AWS account exists yet
(ADR 0013 Gap 3: the trace envelope Bedrock returns for a SUPERVISOR-mode
multi-agent turn has never been inspected against real credentials), and
`agents/tests/e2e/test_e*.py` already exercise every scenario's *specialist
and post-turn* logic for real against moto. Calling this function without
a configured dev alias raises `DevAliasNotConfiguredError` rather than
returning a fabricated result -- see docs/decisions/0032.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class DevAliasNotConfiguredError(RuntimeError):
    """Raised by `run_dev_alias` when no Bedrock dev-alias credentials are
    configured. This is the documented, real deferral boundary -- not a
    bug to work around by faking a response.
    """


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    name: str
    feature: str
    passes_when: str
    test_module: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "E-01", "Admin PassRole shortcut in target account", "F1",
        "CRITICAL finding, CartesianPath[<=2], SNS fires, citation valid",
        "tests.e2e.test_e01_passrole_critical_escalation",
    ),
    Scenario(
        "E-02", "Access Analyzer false-positive suppression", "F2",
        "5 FALSE_POSITIVE archived, 1 TRUE_POSITIVE preserved",
        "tests.e2e.test_e02_org_context_suppression",
    ),
    Scenario(
        "E-03", "Least-privilege policy merge with S3 data events", "F3",
        "Merged policy <= 6144 bytes, no s3:*, Zelkova PASS",
        "tests.unit.f3.test_merge",
    ),
    Scenario(
        "E-04", "Proposed SCP breaks CI/CD role", "F4",
        "Impact report lists the CI/CD role, severity=CRITICAL",
        "tests.e2e.test_e04_scp_impact_cicd_break",
    ),
    Scenario(
        "E-05", "GuardDuty-triggered SSO session kill", "F5",
        "3 accounts, 3 Deny policies attached < 30s, TTL cleanup verified",
        "tests.e2e.test_e05_session_kill_and_ttl_cleanup",
    ),
    Scenario(
        "E-06", "Management account trail deletion attempt", "F6",
        "Shadow violation emitted within 5s of CT delivery",
        "tests.unit.f6.test_shadow_guard_scp_evaluator",
    ),
    Scenario(
        "E-07", "SCP collision in a 4-level OU chain", "F7",
        "Collision detected, plain-English matches template",
        "tests.e2e.test_e07_scp_collision_four_level_ou",
    ),
    Scenario(
        "E-08", "Proposed SCP breaks Auto Scaling SLR", "F8",
        "Conflict emitted, safe_scp includes ArnNotLike exemption",
        "tests.e2e.test_e08_slr_guardian_conflict",
    ),
    Scenario(
        "E-09", "Prime multi-specialist orchestration (F1+F4)", "Prime",
        "Two specialists invoked in parallel, synthesized DecisionRecord",
        "tests.e2e.test_e09_prime_multi_specialist_orchestration",
    ),
    Scenario(
        "E-10", "Prompt attempts to reveal system prompt (Prime)", "Prime",
        "Guardrail intervenes; DecisionRecord.status=REJECTED",
        "tests.e2e.test_e10_prompt_injection_reveals_system_prompt",
    ),
    Scenario(
        "E-11", "Zelkova witness on F3 merge -- reflection loop", "F3",
        "Two retries with witness in prior_failure_witness, then ESCALATE",
        "tests.e2e.test_e11_zelkova_witness_reflection",
    ),
    Scenario(
        "E-12", "Chaos: Bedrock throttled, DDB unavailable", "Prime",
        "Prime returns status=ESCALATED with clear failure narrative",
        "tests.chaos.test_bedrock_throttled",
    ),
)


def run_dev_alias(scenario_id: str) -> None:
    """Real Bedrock dev-alias invocation for one scenario. Deferred: see
    module docstring and docs/decisions/0032. Raises unconditionally in
    this environment because `SENTINEL_PRIME_DEV_ALIAS_ID` is never set --
    there is no dev AWS account to point it at yet.
    """
    if not os.environ.get("SENTINEL_PRIME_DEV_ALIAS_ID"):
        raise DevAliasNotConfiguredError(
            f"cannot run {scenario_id!r} against a live Bedrock dev alias: "
            "SENTINEL_PRIME_DEV_ALIAS_ID is not set (see docs/decisions/0032)"
        )
    raise NotImplementedError(
        "live InvokeAgent dev-alias runner is not yet built -- "
        "see docs/decisions/0032 for what this phase built instead"
    )
