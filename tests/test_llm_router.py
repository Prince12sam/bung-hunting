"""Confirms the LLM call timeout is actually enforced, not just requested.

This is a direct regression test for a real incident: a local Ollama
"thinking" model ran 30+ minutes past litellm's own timeout=60, blocking
a whole scan. litellm's timeout isn't reliably honored for every provider,
so api/llm_router.py wraps every call in its own hard deadline — this test
simulates exactly that failure mode (a call that never returns) and checks
we don't wait for it.
"""

import time

import pytest

from api import llm_router
from api.config import settings


def test_complete_does_not_hang_past_its_timeout(monkeypatch):
    monkeypatch.setattr(settings, "coding_models", ["ollama/some-slow-model"])
    monkeypatch.setattr(settings, "llm_call_timeout_seconds", 1)

    def _never_returns(model, messages):
        time.sleep(30)  # simulates the real incident: a call that just hangs
        return "should never get here"

    monkeypatch.setattr(llm_router, "_call", _never_returns)

    start = time.monotonic()
    with pytest.raises(llm_router.LLMUnavailable):
        llm_router.complete([{"role": "user", "content": "hi"}])
    elapsed = time.monotonic() - start

    # Bounded by llm_call_timeout_seconds (1s) + the 5s grace period in
    # complete(), not by the simulated 30s hang.
    assert elapsed < 10, f"complete() blocked for {elapsed:.1f}s instead of respecting the timeout"
