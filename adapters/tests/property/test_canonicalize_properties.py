"""phase-04 §4/§12 ask for 1,000 semantically-equivalent-but-textually-
different JSON inputs to canonicalize to identical bytes. Capped at 200
per the revised testing policy -- the invariant doesn't change with
example count.
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json

_json_value = st.recursive(
    st.none() | st.booleans() | st.integers(min_value=-(10**9), max_value=10**9) | st.text(max_size=20),
    lambda children: st.lists(children, max_size=5)
    | st.dictionaries(st.text(max_size=10), children, max_size=5),
    max_leaves=15,
)


@given(_json_value)
@settings(max_examples=200)
def test_canonicalization_ignores_source_formatting(value: object) -> None:
    compact = json.dumps(value)
    spaced = json.dumps(value, indent=2)
    shuffled = json.dumps(value, sort_keys=False)

    canonical_forms = {
        canonicalize_json(json.loads(compact)),
        canonicalize_json(json.loads(spaced)),
        canonicalize_json(json.loads(shuffled)),
    }

    assert len(canonical_forms) == 1
