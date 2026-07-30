"""ARN wildcard resolution for `iam:PassRole` Resource patterns (phase-02 §4
Step 1). IAM Resource patterns use the glob-like `*`/`?` wildcard grammar
(not regex) anywhere in the ARN, including the account-id segment
(`arn:aws:iam::*:role/*`) -- `fnmatch.fnmatchcase` implements exactly that
grammar without any extra "convenience" behavior (e.g. case-folding) IAM
itself doesn't have.
"""

from __future__ import annotations

from fnmatch import fnmatchcase


def resolve_role_pattern(pattern: str, candidate_role_arns: list[str]) -> list[str]:
    """Return every candidate ARN that `pattern` matches, order preserved.

    `pattern` may be a concrete ARN (matches at most itself) or contain
    `*`/`?` anywhere IAM allows a Resource wildcard.
    """
    return [arn for arn in candidate_role_arns if fnmatchcase(arn, pattern)]
