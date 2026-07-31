"""`refresh_scp_cache` (phase-07 §4 Step 2's 15-min cache refresh) against
a stubbed `OrganizationsClient` -- moto's Organizations support doesn't
model SCP attachment/`DescribePolicy` content (docs/decisions/0023), so
this exercises the walk/cache-write logic with `unittest.mock` doubles
matching the boto3 paginator protocol.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.tools.f6.scp_refresh import refresh_scp_cache

pytestmark = pytest.mark.unit


def _org_client(
    *, ou_ids: list[str], policies_by_target: dict[str, list[dict[str, object]]]
) -> MagicMock:
    org = MagicMock()
    org.list_roots.return_value = {"Roots": [{"Id": "r-root1"}]}

    def get_paginator(name: str) -> MagicMock:
        if name == "list_organizational_units_for_parent":
            # Scoped by `ParentId`, not a fixed page for every call: an
            # unscoped mock would tell the walk that every OU is also a
            # child of itself (and of every other OU), duplicating levels.
            # Only the root has children in this fixture; every OU is a leaf.
            return MagicMock(
                paginate=lambda **kwargs: [
                    {
                        "OrganizationalUnits": (
                            [{"Id": ou_id} for ou_id in ou_ids]
                            if kwargs.get("ParentId") == "r-root1"
                            else []
                        )
                    }
                ]
            )
        if name == "list_policies_for_target":
            return MagicMock(
                paginate=lambda **kwargs: [
                    {"Policies": policies_by_target.get(kwargs["TargetId"], [])}
                ]
            )
        raise AssertionError(f"unexpected paginator: {name}")

    org.get_paginator.side_effect = get_paginator
    org.describe_policy.side_effect = lambda **kwargs: {
        "Policy": {
            "Content": '{"Statement": [{"Effect": "Deny", "Action": "iam:*", "Resource": "*"}]}'
        }
    }
    return org


def test_refresh_scp_cache_caches_root_and_every_ou() -> None:
    org = _org_client(
        ou_ids=["ou-1"],
        policies_by_target={
            "r-root1": [{"Id": "p-root", "Arn": "arn:.../p-root", "Name": "RootDeny"}],
            "ou-1": [{"Id": "p-ou", "Arn": "arn:.../p-ou", "Name": "OuDeny"}],
        },
    )
    policies_client = MagicMock()

    result = refresh_scp_cache(
        org_id="o-abc123", organizations_client=org, policies=policies_client
    )

    assert result == {"levels_cached": 2, "policies_cached": 2}
    assert policies_client.put_policy.call_count == 2
    root_call = policies_client.put_policy.call_args_list[0]
    assert root_call.kwargs["level"] == "root"


def test_refresh_scp_cache_handles_a_target_with_no_scps() -> None:
    org = _org_client(ou_ids=[], policies_by_target={})
    policies_client = MagicMock()

    result = refresh_scp_cache(
        org_id="o-abc123", organizations_client=org, policies=policies_client
    )

    assert result == {"levels_cached": 1, "policies_cached": 0}
    policies_client.put_policy.assert_not_called()
