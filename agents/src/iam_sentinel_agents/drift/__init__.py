"""Drift detection + auto-remediation for Sentinel's own CDK stacks --
agents phase-17 §8. Runs daily; no `EventStack.PENDING_EVENT_BINDINGS` entry
names a `drift_detector` schedule for THIS phase because one already exists
for a different producer -- `aws-infra`'s `CrossAccountStack.
_build_drift_schedule_and_alarm` (phase-08) owns member-account StackSet
drift, a different resource population than "Sentinel's own platform
stacks" this module covers. This phase's own daily schedule is deferred
alongside the rest of its CDK wiring; see this phase's ADR.
"""

from __future__ import annotations
