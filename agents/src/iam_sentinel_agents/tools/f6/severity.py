"""Shadow-violation severity rubric -- phase-07 §4 Step 3.

The spec's prose ("CRITICAL: any Organizations write (examples: ...)")
reads as an open-ended class for Organizations but a closed, named list for
CloudTrail and KMS ("any CloudTrail write (cloudtrail:DeleteTrail,
StopLogging)" lists exactly the two log-tampering actions that matter, not
every CloudTrail write verb; likewise KMS's two key-destruction/policy
actions). This module treats Organizations as the open class (any write
verb on the `organizations:` prefix) and CloudTrail/KMS as the two named
closed sets -- a routine reading of ambiguous prose, not a contract-level
contradiction, so no ADR.
"""

from __future__ import annotations

from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.common import Severity

_ORG_WRITE_VERB_PREFIXES = (
    "delete",
    "detach",
    "disable",
    "leaveorganization",
    "closeaccount",
    "removeaccountfromorganization",
    "declinehandshake",
)
_CRITICAL_CLOUDTRAIL_ACTIONS = {"cloudtrail:deletetrail", "cloudtrail:stoplogging"}
_CRITICAL_KMS_ACTIONS = {"kms:putkeypolicy", "kms:scheduledeletion", "kms:scheduledkeydeletion"}


def _is_critical_organizations_write(action: str) -> bool:
    if not action.startswith("organizations:"):
        return False
    verb = action.split(":", 1)[1]
    return verb.startswith(_ORG_WRITE_VERB_PREFIXES)


def classify_severity(action: str, would_be_denied_at_level: Literal["root", "ou"]) -> Severity:
    """`action` must already be lowercased (per phase-07 §4 Step 2: "Compute
    action ... Lowercase for matching")."""
    if (
        _is_critical_organizations_write(action)
        or action in _CRITICAL_CLOUDTRAIL_ACTIONS
        or action in _CRITICAL_KMS_ACTIONS
    ):
        return "CRITICAL"
    if action.startswith("iam:") and would_be_denied_at_level == "ou":
        return "HIGH"
    return "MEDIUM"
