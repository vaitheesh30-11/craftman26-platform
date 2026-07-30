"""Access Analyzer Zelkova adapter (adapters phase-02).

The platform's mathematical safety net: `CheckNoNewAccess` /
`CheckAccessNotGranted` before a policy write, `StartPolicyGeneration` /
`GetGeneratedPolicy` for auto-generated least-privilege policies, and a
post-write eventual-consistency verification. Never fails open -- see
`errors.ZelkovaError` and `client.ZelkovaClient`.
"""

from __future__ import annotations

from iam_sentinel_adapters.zelkova.client import ZelkovaClient
from iam_sentinel_adapters.zelkova.models import PolicyPair, Witness, ZelkovaResult

__all__ = [
    "PolicyPair",
    "Witness",
    "ZelkovaClient",
    "ZelkovaResult",
]
