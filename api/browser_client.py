"""Thin client for the sandboxed browser (docker/docker-compose.yml's
browser_sandbox), driven via Playwright's Chrome DevTools Protocol
connection — same "hand-rolled client to a long-lived sandboxed service"
pattern as api/msf_client.py's relationship to msfrpcd.

Every action returns the same finding-dict schema every tool_router.py
run_* function does (source_tool/severity/title/description/file_path/
line), so browser actions slot into the same findings list/report
pipeline and can sit in the adaptive planning loop's action registry
(api/agents/adaptive_agent.py) identically to any CLI tool.

Scope classification (read-only vs state-changing) is NOT decided here —
same as tool_router.py's run_* functions, this module is purely
mechanical. The caller (api/agents/adaptive_agent.py) decides which scope
tier each action needs and calls api/scope.py's require_authorized before
invoking it.
"""

import os
import tempfile

from api.config import settings


class BrowserActionError(Exception):
    pass


class BrowserSession:
    def __init__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - environment issue, not a logic path
            raise BrowserActionError(
                "the `playwright` package isn't installed — run `pip install -r requirements.txt`"
            ) from exc

        self._playwright = sync_playwright().start()
        url = f"http://{settings.browser_sandbox_host}:{settings.browser_cdp_port}"
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(
                url, timeout=settings.browser_action_timeout_seconds * 1000
            )
        except Exception as exc:
            self._playwright.stop()
            raise BrowserActionError(
                f"could not connect to the browser sandbox at {url} — is `scorpion launch` running? ({exc})"
            ) from exc

        context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        self._page = context.new_page()

    def close(self) -> None:
        try:
            self._page.close()
        finally:
            self._playwright.stop()

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _timeout_ms(self) -> int:
        return settings.browser_action_timeout_seconds * 1000

    def _locate(self, text_or_selector: str):
        # Prefer text-based location — resilient to markup changes and
        # matches how a human/LLM would describe "the Login button" —
        # falling back to treating the input as a raw CSS selector.
        try:
            locator = self._page.get_by_text(text_or_selector, exact=False)
            if locator.count() > 0:
                return locator.first
        except Exception:
            pass
        return self._page.locator(text_or_selector).first

    def navigate(self, url: str) -> list[dict]:
        try:
            response = self._page.goto(url, timeout=self._timeout_ms())
        except Exception as exc:
            raise BrowserActionError(f"navigate to {url} failed: {exc}") from exc
        status = response.status if response else None
        return [
            {
                "source_tool": "browser",
                "severity": "info",
                "title": f"navigated to {self._page.url}",
                "description": f"page title: {self._page.title()!r}, status: {status}",
                "file_path": None,
                "line": None,
            }
        ]

    def click(self, text_or_selector: str) -> list[dict]:
        try:
            self._locate(text_or_selector).click(timeout=self._timeout_ms())
            self._page.wait_for_load_state("networkidle", timeout=self._timeout_ms())
        except Exception as exc:
            raise BrowserActionError(f"click '{text_or_selector}' failed: {exc}") from exc
        return [
            {
                "source_tool": "browser",
                "severity": "info",
                "title": f"clicked '{text_or_selector}'",
                "description": f"now at {self._page.url} (page title: {self._page.title()!r})",
                "file_path": None,
                "line": None,
            }
        ]

    def fill(self, selector: str, value: str) -> list[dict]:
        try:
            self._page.fill(selector, value, timeout=self._timeout_ms())
        except Exception as exc:
            raise BrowserActionError(f"fill '{selector}' failed: {exc}") from exc
        return [
            {
                "source_tool": "browser",
                "severity": "info",
                "title": f"filled '{selector}'",
                "description": f"at {self._page.url}",
                "file_path": None,
                "line": None,
            }
        ]

    def extract_text(self) -> list[dict]:
        try:
            text = self._page.inner_text("body")
        except Exception as exc:
            raise BrowserActionError(f"extract_text failed: {exc}") from exc
        return [
            {
                "source_tool": "browser",
                "severity": "info",
                "title": f"page text extracted: {self._page.url}",
                "description": text[:2000],
                "file_path": None,
                "line": None,
            }
        ]

    def extract_forms(self) -> list[dict]:
        try:
            forms = self._page.eval_on_selector_all(
                "form",
                """forms => forms.map(f => ({
                    action: f.action,
                    method: (f.method || 'get').toUpperCase(),
                    fields: Array.from(f.elements)
                        .map(e => ({name: e.name, type: e.type}))
                        .filter(field => field.name),
                }))""",
            )
        except Exception as exc:
            raise BrowserActionError(f"extract_forms failed: {exc}") from exc

        findings = []
        for form in forms:
            fields = form.get("fields", [])
            field_names = ", ".join(f["name"] for f in fields) or "(no named fields)"
            has_password_field = any(f.get("type") == "password" for f in fields)
            findings.append(
                {
                    "source_tool": "browser",
                    "severity": "medium" if has_password_field else "info",
                    "title": f"form discovered: {form.get('method')} {form.get('action') or self._page.url}",
                    "description": f"fields: {field_names}"
                    + (" — includes a password field" if has_password_field else ""),
                    "file_path": None,
                    "line": None,
                }
            )
        return findings

    def screenshot(self, out_path: str | None = None) -> list[dict]:
        if out_path is None:
            fd, out_path = tempfile.mkstemp(prefix="scorpion-browser-", suffix=".png")
            os.close(fd)
        try:
            self._page.screenshot(path=out_path)
        except Exception as exc:
            raise BrowserActionError(f"screenshot failed: {exc}") from exc
        return [
            {
                "source_tool": "browser",
                "severity": "info",
                "title": f"screenshot captured: {self._page.url}",
                "description": f"page title: {self._page.title()!r}",
                "file_path": out_path,
                "line": None,
            }
        ]
