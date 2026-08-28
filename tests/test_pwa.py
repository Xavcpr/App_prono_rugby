from django.urls import reverse
from django.test import Client


def test_manifest_route():
    resp = Client().get(reverse("pwa_manifest"), secure=True)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/manifest+json")
    data = resp.json()
    assert data["short_name"] == "Pronos"
    assert data["start_url"] == "/"
    assert data["display"] == "standalone"
    assert any(icon["sizes"] == "512x512" for icon in data["icons"])


def test_service_worker_route():
    resp = Client().get(reverse("service_worker"), secure=True)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/javascript"
    assert resp.headers["Service-Worker-Allowed"] == "/"
    body = resp.content.decode()
    assert "self.addEventListener('fetch'" in body


def test_base_html_links_manifest(client, db):
    resp = client.get("/accounts/login/", secure=True)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'rel="manifest"' in html
    assert "manifest.webmanifest" in html
    assert "apple-touch-icon" in html
    assert "serviceWorker" in html