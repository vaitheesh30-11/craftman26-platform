from __future__ import annotations

from iam_sentinel_adapters.llm.bedrock_provider import BedrockProvider
from iam_sentinel_adapters.llm.factory import get_provider
from iam_sentinel_adapters.llm.grok_provider import GrokProvider
from iam_sentinel_adapters.settings import settings


def test_grok_provider_selected_when_configured() -> None:
    original = settings.llm_provider
    settings.llm_provider = "grok"
    try:
        assert isinstance(get_provider(), GrokProvider)
    finally:
        settings.llm_provider = original


def test_bedrock_provider_selected_by_default() -> None:
    original = settings.llm_provider
    settings.llm_provider = "bedrock"
    try:
        assert isinstance(get_provider(), BedrockProvider)
    finally:
        settings.llm_provider = original
