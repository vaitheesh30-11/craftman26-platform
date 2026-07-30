from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from iam_sentinel_infra.config import load_stage_config

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.mark.parametrize("stage", ["dev", "staging", "prod"])
def test_load_stage_config_reads_every_stage_file(stage: str) -> None:
    config = load_stage_config(stage, config_dir=CONFIG_DIR)  # type: ignore[arg-type]
    assert config.stage == stage
    assert config.account_id
    assert config.region


def test_missing_required_field_raises(tmp_path: Path) -> None:
    (tmp_path / "dev.yaml").write_text("stage: dev\nregion: us-east-1\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_stage_config("dev", config_dir=tmp_path)  # type: ignore[arg-type]


def test_unknown_field_rejected(tmp_path: Path) -> None:
    (tmp_path / "dev.yaml").write_text(
        "\n".join(
            [
                "stage: dev",
                "account_id: '111111111111'",
                "region: us-east-1",
                "org_id: o-x",
                "org_root_id: r-x",
                "delegated_admin_analyzer_account: '111111111111'",
                "delegated_admin_idc_account: '111111111111'",
                "not_a_real_field: true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_stage_config("dev", config_dir=tmp_path)  # type: ignore[arg-type]
