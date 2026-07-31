"""tools/f2/suppress.py -- phase-03 §4 Step 4 and §9 acceptance criteria:
"Archive rule creation is idempotent on repeat runs" and "Never archives a
TRUE_POSITIVE (property test with adversarial fixtures)".
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.tools.f2.suppress import select_archivable_finding_ids, suppress_findings
from tests.contract._factories import make_org_context_classification

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.org_context import OrgContextClassification

pytestmark = pytest.mark.unit

ANALYZER_ARN = "arn:aws:access-analyzer:us-east-1:111122223333:analyzer/org-analyzer"
ORG_ID = "o-a1b2c3d4e5"


def _classification(finding_id: str, kind: str) -> OrgContextClassification:
    return make_org_context_classification(finding_id=finding_id, classification=kind)


def test_select_archivable_finding_ids_only_returns_false_positives() -> None:
    classifications = [
        _classification("f-1", "FALSE_POSITIVE_ORG_SCOPED"),
        _classification("f-2", "FALSE_POSITIVE_ACCOUNT_SCOPED"),
        _classification("f-3", "TRUE_POSITIVE"),
        _classification("f-4", "INCONCLUSIVE_UNKNOWN_CONDITION"),
    ]
    assert select_archivable_finding_ids(classifications) == ["f-1", "f-2"]


@pytest.mark.parametrize(
    "kinds",
    [
        ["TRUE_POSITIVE"],
        ["INCONCLUSIVE_UNKNOWN_CONDITION"],
        ["TRUE_POSITIVE", "INCONCLUSIVE_UNKNOWN_CONDITION"],
        ["TRUE_POSITIVE", "FALSE_POSITIVE_ORG_SCOPED", "INCONCLUSIVE_UNKNOWN_CONDITION"],
    ],
)
def test_select_archivable_finding_ids_never_includes_true_positive_or_inconclusive(
    kinds: list[str],
) -> None:
    classifications = [_classification(f"f-{i}", kind) for i, kind in enumerate(kinds)]
    selected = set(select_archivable_finding_ids(classifications))
    non_archivable = {
        c.finding_id
        for c in classifications
        if c.classification not in {"FALSE_POSITIVE_ORG_SCOPED", "FALSE_POSITIVE_ACCOUNT_SCOPED"}
    }
    assert selected.isdisjoint(non_archivable)


def test_suppress_findings_batches_updates_in_groups_of_25() -> None:
    fake_session = MagicMock()
    fake_client = MagicMock()
    fake_session.client.return_value = fake_client
    fake_client.exceptions.ResourceNotFoundException = type(
        "ResourceNotFoundException", (Exception,), {}
    )
    fake_client.get_archive_rule.side_effect = fake_client.exceptions.ResourceNotFoundException()

    finding_ids = [f"f-{i}" for i in range(30)]
    result = suppress_findings(
        finding_ids, ANALYZER_ARN, org_id=ORG_ID, session=fake_session, create_rule=False
    )

    assert result == {"archived": 30, "rule_id": None}
    assert fake_client.update_findings.call_count == 2
    first_batch = fake_client.update_findings.call_args_list[0].kwargs["ids"]
    second_batch = fake_client.update_findings.call_args_list[1].kwargs["ids"]
    assert len(first_batch) == 25
    assert len(second_batch) == 5


def test_suppress_findings_creates_rule_when_it_does_not_exist() -> None:
    fake_session = MagicMock()
    fake_client = MagicMock()
    fake_session.client.return_value = fake_client
    fake_client.exceptions.ResourceNotFoundException = type(
        "ResourceNotFoundException", (Exception,), {}
    )
    fake_client.get_archive_rule.side_effect = fake_client.exceptions.ResourceNotFoundException()

    result = suppress_findings(
        ["f-1"], ANALYZER_ARN, org_id=ORG_ID, session=fake_session, create_rule=True
    )

    fake_client.create_archive_rule.assert_called_once()
    fake_client.update_archive_rule.assert_not_called()
    assert result["rule_id"] == f"sentinel-org-scoped-suppression-{ORG_ID}"


def test_suppress_findings_is_idempotent_and_updates_an_existing_rule() -> None:
    fake_session = MagicMock()
    fake_client = MagicMock()
    fake_session.client.return_value = fake_client
    fake_client.exceptions.ResourceNotFoundException = type(
        "ResourceNotFoundException", (Exception,), {}
    )
    fake_client.get_archive_rule.return_value = {
        "ruleName": f"sentinel-org-scoped-suppression-{ORG_ID}"
    }

    result = suppress_findings(
        ["f-1"], ANALYZER_ARN, org_id=ORG_ID, session=fake_session, create_rule=True
    )

    fake_client.update_archive_rule.assert_called_once()
    fake_client.create_archive_rule.assert_not_called()
    assert result["rule_id"] == f"sentinel-org-scoped-suppression-{ORG_ID}"


def test_suppress_findings_skips_rule_when_no_findings_given() -> None:
    fake_session = MagicMock()
    fake_client = MagicMock()
    fake_session.client.return_value = fake_client

    result = suppress_findings(
        [], ANALYZER_ARN, org_id=ORG_ID, session=fake_session, create_rule=True
    )

    assert result == {"archived": 0, "rule_id": None}
    fake_client.create_archive_rule.assert_not_called()
    fake_client.update_findings.assert_not_called()
