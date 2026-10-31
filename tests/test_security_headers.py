from fastapi.testclient import TestClient

from forca import config, web


def test_hsts_is_sent_when_using_https(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "https://financas.exemplo.com")
    headers = TestClient(web.app).get("/manifest.webmanifest").headers
    assert headers["Strict-Transport-Security"] == "max-age=31536000"


def test_no_hsts_on_local_http(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://localhost:8000")
    assert "Strict-Transport-Security" not in TestClient(web.app).get("/manifest.webmanifest").headers


def test_base_security_headers():
    headers = TestClient(web.app).get("/manifest.webmanifest").headers
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
