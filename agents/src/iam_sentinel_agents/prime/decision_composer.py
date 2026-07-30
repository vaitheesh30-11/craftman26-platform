"""Verdict rollup (phase-01 §4 step 3): "status derived from verdict
rollup (any REJECT → REJECTED; any CRITICAL finding → status=ANSWERED but
critical flag; any INCONCLUSIVE → ESCALATED)".

Precedence, highest first: REJECT beats everything (a specialist actively
rejecting the request is a stronger signal than ambiguity elsewhere) ->
INCONCLUSIVE/ESCALATE -> unanimous REMEDIATED -> default ANSWERED. The
CRITICAL-finding flag is orthogonal to `status` (per the spec text: it
rides alongside ANSWERED, it doesn't replace it) and is what
`PrimePostTurnProcessor` uses to decide whether to fire SNS + Security
Hub, independent of the DecisionRecord's own `status` field.
"""

from __future__ import annotations

from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.common import Severity
    from iam_sentinel_agents.contracts.verdict import SpecialistVerdict

DecisionStatus = Literal["ANSWERED", "ESCALATED", "AUTO_REMEDIATED", "REJECTED"]

_ESCALATING_VERDICTS = frozenset({"INCONCLUSIVE", "ESCALATE"})


def compose_status(verdicts: list[SpecialistVerdict]) -> DecisionStatus:
    if not verdicts:
        raise ValueError("cannot compose a status from zero specialist verdicts")

    if any(v.verdict == "REJECT" for v in verdicts):
        return "REJECTED"
    if any(v.verdict in _ESCALATING_VERDICTS for v in verdicts):
        return "ESCALATED"
    if all(v.verdict == "REMEDIATED" for v in verdicts):
        return "AUTO_REMEDIATED"
    return "ANSWERED"


def has_critical_finding(verdicts: list[SpecialistVerdict]) -> bool:
    target: Severity = "CRITICAL"
    return any(finding.severity == target for verdict in verdicts for finding in verdict.findings)
