"""Phase-12 eval harness: golden-set runner + LLM-as-judge (agents
docs/phase-12-observability-evals.txt §6). Every prior specialist phase
(F1-F8) and the Prime supervisor deferred running its golden.jsonl end to
end because this module didn't exist -- see docs/decisions/0032."""

from __future__ import annotations
