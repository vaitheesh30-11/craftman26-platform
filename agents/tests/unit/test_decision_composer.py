from __future__ import annotations

import pytest

from iam_sentinel_agents.prime.decision_composer import compose_status, has_critical_finding
from tests.contract._factories import make_finding, make_verdict


def test_all_confirm_yields_answered() -> None:
    verdicts = [make_verdict(verdict="CONFIRM")]
    assert compose_status(verdicts) == "ANSWERED"


def test_any_reject_yields_rejected_even_alongside_inconclusive() -> None:
    verdicts = [
        make_verdict(verdict="REJECT", findings=[]),
        make_verdict(verdict="INCONCLUSIVE", findings=[], correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A4"),
    ]
    assert compose_status(verdicts) == "REJECTED"


@pytest.mark.parametrize("verdict", ["INCONCLUSIVE", "ESCALATE"])
def test_inconclusive_or_escalate_yields_escalated(verdict: str) -> None:
    verdicts = [make_verdict(verdict=verdict, findings=[])]
    assert compose_status(verdicts) == "ESCALATED"


def test_unanimous_remediated_yields_auto_remediated() -> None:
    verdicts = [make_verdict(verdict="REMEDIATED", findings=[])]
    assert compose_status(verdicts) == "AUTO_REMEDIATED"


def test_compose_status_rejects_empty_verdict_list() -> None:
    with pytest.raises(ValueError, match="zero specialist verdicts"):
        compose_status([])


def test_has_critical_finding_true_when_any_verdict_carries_one() -> None:
    verdicts = [make_verdict(findings=[make_finding(severity="CRITICAL")])]
    assert has_critical_finding(verdicts) is True


def test_has_critical_finding_false_when_all_low() -> None:
    low_finding = make_finding(severity="LOW", principal_arn=None)
    verdicts = [make_verdict(findings=[low_finding])]
    assert has_critical_finding(verdicts) is False
