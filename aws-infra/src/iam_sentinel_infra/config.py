"""Per-stage configuration, loaded from `config/{stage}.yaml` (phase-00 §3).

Every stack constructor receives one `StageConfig`; no stack reads YAML or
environment variables directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

Stage = Literal["dev", "staging", "prod"]

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class StageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Stage
    account_id: str
    region: str
    org_id: str
    org_root_id: str
    delegated_admin_analyzer_account: str
    delegated_admin_idc_account: str
    org_trail_bucket_name: str = "org-cloudtrail-bucket-placeholder"
    haiku_model_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"
    sonnet_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    kb_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    episodic_retention_years: int = 2
    correlation_dollar_cap: float = 1.00
    principal_daily_dollar_cap: float = 50.00


def load_stage_config(stage: Stage, *, config_dir: Path = CONFIG_DIR) -> StageConfig:
    path = config_dir / f"{stage}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return StageConfig.model_validate(raw)
