"""`functions/router.handler` -- the Lambda `backend.RouterBridgeService`
invokes (agents phase-15 §6 Step 1). Exercises the envelope contract only
(dispatch mapping, read-mode branch, `AmbiguityError` -> `ESCALATE`
shaping); each fast-path mirror's own logic is `test_fast_path.py`'s job.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from iam_sentinel_agents.functions import router as router_fn
from iam_sentinel_agents.tools.common.fast_path import AmbiguityError

pytestmark = pytest.mark.unit


class _FakeContext:
    aws_request_id = "req-router"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


def _context() -> Any:
    return _FakeContext()


def test_post_dispatch_routes_f1_to_passrole_fast() -> None:
    with patch.object(router_fn, "passrole_fast", return_value={"verdict": "CONFIRM"}) as mocked:
        result = router_fn.handler(
            {
                "mode": "fast",
                "target": "F1",
                "payload": {"account_id": "123456789012"},
                "principal": "arn:aws:iam::111122223333:user/Alice",
                "correlation_id": "01ROUTER0000000000000001",
            },
            _context(),
        )
    mocked.assert_called_once()
    assert result == {"verdict": "CONFIRM"}


def test_post_dispatch_routes_f5_and_builds_an_sso_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sso = MagicMock()
    monkeypatch.setattr(router_fn.boto3, "client", MagicMock(return_value=fake_sso))
    with patch.object(router_fn, "emergency_kill_fast", return_value={"verdict": "CONFIRM"}) as mocked:
        result = router_fn.handler(
            {"mode": "fast", "target": "F5", "payload": {"permission_set_arn": "arn:x"}},
            _context(),
        )
    assert result == {"verdict": "CONFIRM"}
    _args, kwargs = mocked.call_args
    assert kwargs["sso_client"] is fake_sso


def test_read_dispatch_routes_f6_to_shadow_guard_fast() -> None:
    with patch.object(router_fn, "shadow_guard_fast", return_value={"items": [], "next_token": None}) as mocked:
        result = router_fn.handler(
            {"mode": "fast", "target": "F6", "query": {"days_back": 7}}, _context()
        )
    mocked.assert_called_once_with({"days_back": 7})
    assert result == {"items": [], "next_token": None}


def test_unknown_target_raises() -> None:
    with pytest.raises(router_fn.UnknownFastPathTargetError):
        router_fn.handler({"mode": "fast", "target": "F9", "payload": {}}, _context())


def test_ambiguity_error_shapes_an_escalate_verdict() -> None:
    with patch.object(router_fn, "passrole_fast", side_effect=AmbiguityError("too many principals")):
        result = router_fn.handler(
            {"mode": "fast", "target": "F1", "payload": {"account_id": "123456789012"}}, _context()
        )
    assert result["verdict"] == "ESCALATE"
    assert "too many principals" in result["reason"]
    assert result["findings"] == []
    assert result["remediation"] is None


def test_correlation_id_defaults_to_a_new_ulid_when_absent() -> None:
    with patch.object(router_fn, "passrole_fast", return_value={"verdict": "REJECT"}) as mocked:
        router_fn.handler({"mode": "fast", "target": "F1", "payload": {}}, _context())
    _args, kwargs = mocked.call_args
    assert kwargs["correlation_id"]
