"""Watchdog Lambda -- agents phase-17 §6.

`watchdog/scanner.py::watchdog_scanner` is the target `aws-infra`'s
`EventStack.PENDING_EVENT_BINDINGS` names `WatchdogSchedule`
(`rate(1 minute)`, `owning_phase="agents phase-17 (Self-Healing)"`) --
`EventStack.register_schedule()` is called from this phase's own CDK stack
once one exists (deferred; see this phase's ADR), the same division of
ownership every other pending binding follows.
"""

from __future__ import annotations
