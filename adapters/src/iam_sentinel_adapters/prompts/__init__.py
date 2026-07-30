"""XML prompt fencing and untrusted-input sanitization (phase-03)."""

from __future__ import annotations

from iam_sentinel_adapters.prompts.sanitizer import sanitize_untrusted
from iam_sentinel_adapters.prompts.xml_fencer import UntrustedBlock, build_prompt

__all__ = ["UntrustedBlock", "build_prompt", "sanitize_untrusted"]
