import http.server
import socketserver
import threading

from fastapi.testclient import TestClient

from api.config import settings
from api.main import app
from api.tool_router import run_httpx, run_nmap


def _start_http_server(port: int) -> socketserver.TCPServer:
    httpd = socketserver.TCPServer(("0.0.0.0", port), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_scan_denies_active_action_on_unverified_third_party_target():
    """The scope gate must block active tools against a target nobody
    verified — this must hold even if a caller asks for it directly."""
    client = TestClient(app)
    response = client.post("/v1/scan", json={"target": "example.com"})
    assert response.status_code == 200

    body = response.json()
    assert body["findings"] == []
    assert any("skipped" in w for w in body["warnings"])


def test_local_target_auto_verified_and_scan_wires_through():
    """localhost is auto-verified (docs/SECURITY_AND_AUTHORIZATION.md #4) —
    both pipeline stages should actually run, not be skipped."""
    client = TestClient(app)
    response = client.post("/v1/scan", json={"target": "localhost"})
    assert response.status_code == 200

    body = response.json()
    assert not any("skipped" in w for w in body["warnings"])


def test_nmap_detects_a_specific_open_port_on_the_host():
    port = 8765
    httpd = _start_http_server(port)
    try:
        findings = run_nmap(settings.container_host_alias, ports=str(port))
    finally:
        httpd.shutdown()

    assert any(f"{port}" in f["title"] for f in findings)


def test_httpx_detects_the_same_service():
    port = 8766
    httpd = _start_http_server(port)
    try:
        findings = run_httpx(f"{settings.container_host_alias}:{port}")
    finally:
        httpd.shutdown()

    assert len(findings) >= 1
    assert findings[0]["source_tool"] == "httpx"
