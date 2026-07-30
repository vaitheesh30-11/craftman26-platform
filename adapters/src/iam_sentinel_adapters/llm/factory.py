"""Provider selection via `SENTINEL_LLM_PROVIDER` (docs/EXECUTION_PLAN.txt
§2). Local dev + tests use Grok; every AWS deployment uses Bedrock. No
caller ever hard-codes either provider.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.llm.bedrock_provider import BedrockProvider
from iam_sentinel_adapters.llm.grok_provider import GrokProvider
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from iam_sentinel_adapters.llm.types import LLMProvider


def get_provider() -> LLMProvider:
    if settings.llm_provider == "grok":
        return GrokProvider()
    return BedrockProvider()
