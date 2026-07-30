"""CDK CLI entry point. See `iam_sentinel_infra.app_factory` for the graph
itself and `iam_sentinel_infra.config` for how the stage is resolved.
"""

from __future__ import annotations

import os

import aws_cdk as cdk
from aws_cdk import Aspects
from cdk_nag import AwsSolutionsChecks, HIPAASecurityChecks

from iam_sentinel_infra.app_factory import build_app

cdk_app = cdk.App()
stage = cdk_app.node.try_get_context("sentinel:stage") or os.environ.get("SENTINEL_STAGE", "dev")
feature_flags: dict[str, bool] = cdk_app.node.try_get_context("sentinel:feature-flags") or {}

build_app(stage, app=cdk_app)

Aspects.of(cdk_app).add(AwsSolutionsChecks(verbose=True))
if feature_flags.get("enable-hipaa-nag", True):
    Aspects.of(cdk_app).add(HIPAASecurityChecks(verbose=True))

cdk_app.synth()
