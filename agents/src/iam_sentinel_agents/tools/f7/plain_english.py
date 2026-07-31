"""Deterministic plain-English collision explanation (phase-08 §4 Step 3).

The template is fixed string formatting, not LLM-generated -- the specialist
prompt's own Step 3 is explicit: "This template is not LLM-generated -- it
is a deterministic string format. The LLM only synthesizes the narrative
around the collection." Same output for the same inputs, every run
(phase-08 §9 acceptance: "Plain-English template output is deterministic
across runs").
"""

from __future__ import annotations

_TEMPLATE = (
    "SCP {denying_scp_name} at {denying_level} level denies {action} "
    "because of statement {denying_statement_id}. SCP {allowing_scp_name} "
    "at {allowing_level} level allows {action}. Under AWS SCP evaluation "
    "rules, an explicit Deny at ANY level overrides an Allow at any other "
    "level, so {action} is DENIED in this account."
)


def build_plain_english(
    *,
    action: str,
    denying_scp_name: str,
    denying_level: str,
    denying_statement_id: str | None,
    allowing_scp_name: str,
    allowing_level: str,
) -> str:
    return _TEMPLATE.format(
        action=action,
        denying_scp_name=denying_scp_name,
        denying_level=denying_level,
        denying_statement_id=denying_statement_id or "<unnamed statement>",
        allowing_scp_name=allowing_scp_name,
        allowing_level=allowing_level,
    )
