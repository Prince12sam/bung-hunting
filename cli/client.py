import httpx

from api.config import settings

BASE_URL = f"http://{settings.host}:{settings.port}"

DEFAULT_TIMEOUT = 600
# `scan` runs up to 8 tool stages sequentially, each with its own timeout
# up to settings.nuclei_timeout_seconds (300s) — worst case comfortably
# exceeds the default. A real 8-minute+ run against gamed.gg hit exactly
# this: the server finished and returned 200, but the CLI had already
# given up, so the result was never shown.
SCAN_TIMEOUT = 1800


def post(path: str, json: dict, timeout: float = DEFAULT_TIMEOUT) -> dict:
    with httpx.Client(base_url=BASE_URL, timeout=timeout) as client:
        response = client.post(path, json=json)
        response.raise_for_status()
        return response.json()
