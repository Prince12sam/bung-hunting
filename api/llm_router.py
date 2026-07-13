from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import litellm

from api.config import settings

litellm.suppress_debug_info = True

# One worker is enough — calls are made one at a time by the fallback loop
# below, this exists purely to get a hard wall-clock timeout on top of it.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-call")


class LLMUnavailable(Exception):
    pass


def _call(model: str, messages: list[dict]) -> str:
    response = litellm.completion(
        model=model,
        messages=messages,
        timeout=settings.llm_call_timeout_seconds,
        api_base=settings.ollama_base_url if model.startswith("ollama/") else None,
    )
    return response.choices[0].message["content"]


def complete(messages: list[dict], purpose: str = "coding") -> str:
    """Try each configured model in order, return the first success.

    Empty config (the default) means no provider has been set up yet —
    callers must handle LLMUnavailable rather than treat it as a crash,
    since the rest of the pipeline (e.g. semgrep findings) is still useful
    without an LLM summary.

    litellm's own `timeout=` kwarg is NOT reliably enforced for every
    provider — confirmed the hard way with a local Ollama "thinking" model
    that ran for 30+ minutes past a 60s timeout, blocking the whole request.
    The call is run in a worker thread and bounded here with a real
    wall-clock deadline; if it's exceeded we stop waiting and move to the
    next fallback model immediately. The abandoned call may keep running in
    the background (Python can't forcibly kill a thread), but the request
    itself is never blocked on it again.
    """
    models = settings.coding_models if purpose == "coding" else settings.fast_models
    if not models:
        raise LLMUnavailable(
            "No LLM provider configured. Set ES_CODING_MODELS (and the "
            "matching provider API key) in .env — see docs/GETTING_STARTED.md"
        )

    last_err: Exception | None = None
    for model in models:
        future = _executor.submit(_call, model, messages)
        try:
            return future.result(timeout=settings.llm_call_timeout_seconds + 5)
        except FutureTimeoutError as exc:
            last_err = TimeoutError(
                f"{model} did not respond within {settings.llm_call_timeout_seconds}s"
            )
            last_err.__cause__ = exc
            continue
        except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a fallback chain
            last_err = exc
            continue

    raise LLMUnavailable(f"All configured LLM providers failed. Last error: {last_err}")
