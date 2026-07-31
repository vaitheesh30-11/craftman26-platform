"""Guards the scenario catalog (`runner.SCENARIOS`) against silent drift
from the phase-13 spec's 12-scenario table, and proves `run_dev_alias`
fails loudly (never fabricates a result) when no dev alias is configured.
"""

from __future__ import annotations

import pytest

from tests.e2e.runner import DevAliasNotConfiguredError, run_dev_alias, SCENARIOS


def test_catalog_has_all_twelve_scenarios_in_spec_order() -> None:
    assert [s.scenario_id for s in SCENARIOS] == [f"E-{i:02d}" for i in range(1, 13)]


def test_every_scenario_has_a_test_module_and_passes_when_clause() -> None:
    for scenario in SCENARIOS:
        assert scenario.test_module
        assert scenario.passes_when
        assert scenario.feature


def test_run_dev_alias_raises_rather_than_fabricating_a_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SENTINEL_PRIME_DEV_ALIAS_ID", raising=False)
    with pytest.raises(DevAliasNotConfiguredError):
        run_dev_alias("E-01")
