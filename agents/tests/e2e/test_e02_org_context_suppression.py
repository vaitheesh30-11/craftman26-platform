"""E-02 — Access Analyzer false-positive suppression (phase-13 scenario
table). Real `tools/f2/suppress.suppress_findings` batching/archive-rule
logic against a fake Access Analyzer client (the same test double
`tests/unit/f2/test_handlers.py` already establishes as this module's own
precedent -- moto has no Access Analyzer archive-rule support to fall back
to). Passes when: 5 FALSE_POSITIVE archived, 1 TRUE_POSITIVE preserved.
"""

from __future__ import annotations

from unittest import mock
from unittest.mock import MagicMock

import boto3

from iam_sentinel_agents.tools.f2.org_tree import OrgContext
from iam_sentinel_agents.tools.f2.suppress import select_archivable_finding_ids, suppress_findings
from tests.contract._factories import make_org_context_classification

_ANALYZER_ARN = "arn:aws:access-analyzer:us-east-1:111122223333:analyzer/org-analyzer"
_ORG = OrgContext(
    org_id="o-a1b2c3d4e5",
    master_account_id="111122223333",
    feature_set="ALL",
    account_ids=["111122223333"],
    ou_paths=["o-a1b2c3d4e5/r-ab12/"],
)


def _fake_analyzer_client() -> MagicMock:
    client = MagicMock()
    client.exceptions.ResourceNotFoundException = type(
        "ResourceNotFoundException", (Exception,), {}
    )
    client.get_archive_rule.side_effect = client.exceptions.ResourceNotFoundException()
    return client


def test_e02_five_false_positives_archived_one_true_positive_preserved() -> None:
    classifications = [
        make_org_context_classification(finding_id=f"f-{i}", classification="FALSE_POSITIVE_ORG_SCOPED")
        for i in range(5)
    ] + [make_org_context_classification(finding_id="f-true-positive", classification="TRUE_POSITIVE")]

    archivable = select_archivable_finding_ids(classifications)
    assert len(archivable) == 5
    assert "f-true-positive" not in archivable

    fake_client = _fake_analyzer_client()
    session = boto3.Session(region_name="us-east-1")

    with mock.patch.object(session, "client", return_value=fake_client):
        result = suppress_findings(
            archivable, _ANALYZER_ARN, org_id=_ORG.org_id, session=session
        )

    assert result["archived"] == 5
    assert result["rule_id"] == f"sentinel-org-scoped-suppression-{_ORG.org_id}"

    # Never archives a TRUE_POSITIVE: the one `update_findings` call's `ids`
    # batch is exactly the 5 false positives, the true positive never appears.
    fake_client.update_findings.assert_called_once()
    called_ids = fake_client.update_findings.call_args.kwargs["ids"]
    assert "f-true-positive" not in called_ids
    assert len(called_ids) == 5
