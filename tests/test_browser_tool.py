"""Real-container checks for api/browser_client.py — a real Chromium
running in the browser_sandbox container (docker compose up -d
browser_sandbox, see docker/tools/browser/), driven against a local,
hermetic HTTP server. Same "no mocking" pattern as test_scan_tools.py.
"""

import functools
import http.server
import os
import tempfile
import threading
from pathlib import Path

from api.browser_client import BrowserSession
from api.config import settings

TARGET_HOST = settings.container_host_alias


def _start_form_server(port: int) -> tuple[http.server.ThreadingHTTPServer, tempfile.TemporaryDirectory]:
    tmpdir = tempfile.TemporaryDirectory()
    (Path(tmpdir.name) / "index.html").write_text(
        """<html><body>
<h1>Test Page</h1>
<a href="/next.html">Next Page</a>
<form action="/login" method="POST">
  <input type="text" name="username" id="user">
  <input type="password" name="password">
  <button type="submit">Login</button>
</form>
</body></html>"""
    )
    (Path(tmpdir.name) / "next.html").write_text("<html><body><h1>Next Page Reached</h1></body></html>")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmpdir.name)
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, tmpdir


def test_browser_session_navigates_and_extracts_text():
    port = 8862
    httpd, tmpdir = _start_form_server(port)
    try:
        with BrowserSession() as browser:
            nav = browser.navigate(f"http://{TARGET_HOST}:{port}/")
            assert nav[0]["source_tool"] == "browser"
            assert f"{TARGET_HOST}:{port}" in nav[0]["title"]

            text = browser.extract_text()
            assert "Test Page" in text[0]["description"]
    finally:
        httpd.shutdown()
        tmpdir.cleanup()


def test_browser_session_extracts_a_real_form_with_a_password_field():
    port = 8863
    httpd, tmpdir = _start_form_server(port)
    try:
        with BrowserSession() as browser:
            browser.navigate(f"http://{TARGET_HOST}:{port}/")
            forms = browser.extract_forms()
    finally:
        httpd.shutdown()
        tmpdir.cleanup()

    assert len(forms) == 1
    assert forms[0]["severity"] == "medium"  # a password field bumps it above plain "info"
    assert "username" in forms[0]["description"]
    assert "password" in forms[0]["description"]
    assert "POST" in forms[0]["title"]


def test_browser_session_clicks_a_link_by_text():
    port = 8864
    httpd, tmpdir = _start_form_server(port)
    try:
        with BrowserSession() as browser:
            browser.navigate(f"http://{TARGET_HOST}:{port}/")
            result = browser.click("Next Page")
    finally:
        httpd.shutdown()
        tmpdir.cleanup()

    assert "next.html" in result[0]["description"]


def test_browser_session_fills_a_field_for_real():
    port = 8865
    httpd, tmpdir = _start_form_server(port)
    try:
        with BrowserSession() as browser:
            browser.navigate(f"http://{TARGET_HOST}:{port}/")
            browser.fill("#user", "testvalue123")
            actual_value = browser._page.input_value("#user")
    finally:
        httpd.shutdown()
        tmpdir.cleanup()

    assert actual_value == "testvalue123"


def test_browser_session_writes_a_real_screenshot_file():
    port = 8866
    httpd, tmpdir = _start_form_server(port)
    try:
        with BrowserSession() as browser:
            browser.navigate(f"http://{TARGET_HOST}:{port}/")
            result = browser.screenshot()
    finally:
        httpd.shutdown()
        tmpdir.cleanup()

    path = result[0]["file_path"]
    try:
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
    finally:
        os.remove(path)
