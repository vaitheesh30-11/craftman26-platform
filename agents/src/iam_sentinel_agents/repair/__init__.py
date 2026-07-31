"""Repair Lambdas -- agents phase-17 §7.

Each module here is invoked by an alarm on a specific metric spike
(`SentinelMemoryReadFailure`, `SentinelKbStaleRetrieval`,
`SentinelPoliciesStale`), not on a schedule -- no `EventStack` binding
covers these (§7's triggers are alarm actions, a different EventBridge/
CloudWatch wiring shape than the schedules `PENDING_EVENT_BINDINGS` already
tracks). CDK for the alarm-to-Lambda wiring is deferred with the rest of
this phase's infrastructure; see this phase's ADR.
"""

from __future__ import annotations
