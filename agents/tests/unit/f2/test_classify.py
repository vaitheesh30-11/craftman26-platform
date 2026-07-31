"""tools/f2/classify.py -- phase-03 §4 Steps 2, 3, 5, 6 and §8 Test Plan
("Rate limiting: property test with 100 findings; verify no more than 4
concurrent GetFinding calls").
"""

from __future__ import annotations

import threading
import time
from typing import cast, TYPE_CHECKING
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.f2 import classify
from iam_sentinel_agents.tools.f2.org_tree import OrgContext

if TYPE_CHECKING:
    from mypy_boto3_accessanalyzer.client import AccessAnalyzerClient

pytestmark = pytest.mark.unit

ANALYZER_ARN = "arn:aws:access-analyzer:us-east-1:111122223333:analyzer/org-analyzer"
ORG = OrgContext(
    org_id="o-a1b2c3d4e5",
    master_account_id="111122223333",
    feature_set="ALL",
    account_ids=["111122223333", "444455556666"],
    ou_paths=["o-a1b2c3d4e5/r-ab12/"],
)


def test_classify_finding_org_id_condition_is_false_positive_org_scoped() -> None:
    finding = {"id": "f-1", "condition": {"aws:PrincipalOrgId": "o-a1b2c3d4e5"}}
    result = classify.classify_finding(
        finding, analyzer_arn=ANALYZER_ARN, org=ORG, access_still_granted=lambda _f: True
    )
    assert result.classification == "FALSE_POSITIVE_ORG_SCOPED"
    assert result.matched_condition_key == "aws:PrincipalOrgId"


def test_classify_finding_account_condition_is_false_positive_account_scoped() -> None:
    finding = {"id": "f-2", "condition": {"aws:PrincipalAccount": "444455556666"}}
    result = classify.classify_finding(
        finding, analyzer_arn=ANALYZER_ARN, org=ORG, access_still_granted=lambda _f: True
    )
    assert result.classification == "FALSE_POSITIVE_ACCOUNT_SCOPED"
    assert result.matched_condition_key == "aws:PrincipalAccount"


def test_classify_finding_org_paths_condition_is_false_positive_org_scoped() -> None:
    finding = {
        "id": "f-3",
        "condition": {"aws:PrincipalOrgPaths": "o-a1b2c3d4e5/r-ab12/*"},
    }
    result = classify.classify_finding(
        finding, analyzer_arn=ANALYZER_ARN, org=ORG, access_still_granted=lambda _f: True
    )
    assert result.classification == "FALSE_POSITIVE_ORG_SCOPED"
    assert result.matched_condition_key == "aws:PrincipalOrgPaths"


def test_classify_finding_no_condition_and_access_still_granted_is_true_positive() -> None:
    finding = {"id": "f-4", "condition": {}}
    result = classify.classify_finding(
        finding, analyzer_arn=ANALYZER_ARN, org=ORG, access_still_granted=lambda _f: True
    )
    assert result.classification == "TRUE_POSITIVE"
    assert result.matched_condition_key is None


def test_classify_finding_no_condition_and_access_not_granted_is_inconclusive() -> None:
    finding = {"id": "f-5", "condition": {}}
    result = classify.classify_finding(
        finding, analyzer_arn=ANALYZER_ARN, org=ORG, access_still_granted=lambda _f: False
    )
    assert result.classification == "INCONCLUSIVE_UNKNOWN_CONDITION"


def test_get_findings_bounded_never_exceeds_four_concurrent_calls() -> None:
    lock = threading.Lock()
    state = {"current": 0, "peak": 0}

    class _FakeAccessAnalyzerClient:
        def get_finding(self, *, analyzerArn: str, id: str) -> dict[str, object]:  # noqa: N803
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            time.sleep(0.005)
            with lock:
                state["current"] -= 1
            return {"finding": {"id": id, "condition": {}}}

    finding_ids = [f"f-{i}" for i in range(100)]
    fake_client = cast("AccessAnalyzerClient", _FakeAccessAnalyzerClient())
    results = classify._get_findings_bounded(fake_client, ANALYZER_ARN, finding_ids)

    assert len(results) == 100
    assert state["peak"] <= 4


@mock_aws
def test_scan_and_classify_end_to_end_classifies_and_reports_total() -> None:
    org_client = boto3.client("organizations", region_name="us-east-1")
    org = org_client.create_organization(FeatureSet="ALL")["Organization"]
    org_id = org["Id"]

    fake_aa = MagicMock()
    fake_aa.get_paginator.return_value.paginate.return_value = [
        {"findings": [{"id": "f-1"}, {"id": "f-2"}]}
    ]

    def _get_finding(*, analyzerArn: str, id: str) -> dict[str, object]:  # noqa: N803
        condition = {"aws:PrincipalOrgId": org_id} if id == "f-1" else {}
        return {"finding": {"id": id, "condition": condition}}

    fake_aa.get_finding.side_effect = _get_finding

    session = boto3.Session(region_name="us-east-1")
    with patch.object(classify, "_access_analyzer_client", return_value=fake_aa):
        payload = classify.scan_and_classify(
            ANALYZER_ARN, session=session, access_still_granted=lambda _f: True
        )

    assert payload.total_findings == 2
    by_id = {c.finding_id: c.classification for c in payload.classifications}
    assert by_id["f-1"] == "FALSE_POSITIVE_ORG_SCOPED"
    assert by_id["f-2"] == "TRUE_POSITIVE"


@mock_aws
def test_scan_and_classify_caps_classifications_but_reports_true_total() -> None:
    org_client = boto3.client("organizations", region_name="us-east-1")
    org_client.create_organization(FeatureSet="ALL")

    fake_aa = MagicMock()
    all_findings = [{"id": f"f-{i}"} for i in range(10)]
    fake_aa.get_paginator.return_value.paginate.return_value = [{"findings": all_findings}]
    fake_aa.get_finding.side_effect = lambda *, analyzerArn, id: {  # noqa: N803
        "finding": {"id": id, "condition": {}}
    }

    session = boto3.Session(region_name="us-east-1")
    with patch.object(classify, "_access_analyzer_client", return_value=fake_aa):
        payload = classify.scan_and_classify(
            ANALYZER_ARN, max_findings=3, session=session, access_still_granted=lambda _f: True
        )

    assert payload.total_findings == 10
    assert len(payload.classifications) == 3
