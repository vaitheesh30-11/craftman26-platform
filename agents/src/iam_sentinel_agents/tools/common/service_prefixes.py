"""Shared CloudTrail-event -> IAM-action canonicalization and the write-verb
allowlist used to exclude read-only events before replaying history against
the SCP engine (phase-05 SS4 Step 3).
"""

from __future__ import annotations

_EVENT_SOURCE_SUFFIX = ".amazonaws.com"

# A handful of CloudTrail `eventSource` values do not map onto their IAM
# action namespace by simply stripping ".amazonaws.com" -- deliberately
# small: every service not listed here uses the general rule, which matches
# the vast majority of AWS services (s3, ec2, iam, kms, ...).
_EVENT_SOURCE_TO_IAM_SERVICE = {
    "monitoring": "cloudwatch",
    "email": "ses",
}

_WRITE_VERB_PREFIXES = (
    "Put",
    "Create",
    "Update",
    "Delete",
    "Attach",
    "Detach",
    "Modify",
    "Start",
    "Run",
    "Stop",
    "Terminate",
    "Revoke",
    "Authorize",
    "Add",
    "Remove",
    "Enable",
    "Disable",
    "Set",
    "Register",
    "Deregister",
    "Associate",
    "Disassociate",
    "Reboot",
    "Restore",
    "Purge",
    "Reset",
)


def canonicalize_action(event_source: str, event_name: str) -> str:
    """`s3.amazonaws.com` + `PutBucketPolicy` -> `s3:PutBucketPolicy`."""
    prefix = (
        event_source[: -len(_EVENT_SOURCE_SUFFIX)]
        if event_source.endswith(_EVENT_SOURCE_SUFFIX)
        else event_source
    )
    service = _EVENT_SOURCE_TO_IAM_SERVICE.get(prefix, prefix)
    return f"{service}:{event_name}"


def is_write_action(event_name: str) -> bool:
    """phase-05 SS4 Step 3's write-verb allowlist. The Athena query already
    filters `readonly = false` server-side; this is the client-side mirror
    applied once rows are in hand -- used both defensively (a data source
    that doesn't carry `readOnly` faithfully) and by every test in this
    module that never stands up a mocked Athena backend.
    """
    return event_name.startswith(_WRITE_VERB_PREFIXES)
