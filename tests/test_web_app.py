"""Tests for the web UI dashboard."""
from __future__ import annotations

import os
import json
import pytest

# Flask may not be installed
flask_available = True
try:
    import flask
except ImportError:
    flask_available = False

pytestmark = pytest.mark.skipif(not flask_available, reason="Flask not installed")


@pytest.fixture
def app():
    from mcp_pcb_emcopilot.web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestIndexPage:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_index_contains_upload_form(self, client):
        resp = client.get("/")
        assert b"Upload PCB Design" in resp.data
        assert b"upload-form" in resp.data

    def test_index_contains_title(self, client):
        resp = client.get("/")
        assert b"MCP PCB EMCopilot" in resp.data


class TestUpload:
    def test_upload_no_file(self, client):
        resp = client.post("/api/upload")
        assert resp.status_code == 400

    def test_upload_valid_kicad(self, client):
        fixture = os.path.join(os.path.dirname(__file__), "fixtures", "simple_2layer.kicad_pcb")
        if not os.path.exists(fixture):
            pytest.skip("Test fixture not found")

        with open(fixture, "rb") as f:
            resp = client.post("/api/upload", data={"file": (f, "test.kicad_pcb")}, follow_redirects=False)

        assert resp.status_code == 302  # redirect to session
        assert "/session/" in resp.headers["Location"]


class TestSessionView:
    def test_missing_session_404(self, client):
        resp = client.get("/session/nonexistent")
        assert resp.status_code == 404

    def test_session_after_upload(self, client):
        fixture = os.path.join(os.path.dirname(__file__), "fixtures", "simple_2layer.kicad_pcb")
        if not os.path.exists(fixture):
            pytest.skip("Test fixture not found")

        with open(fixture, "rb") as f:
            resp = client.post("/api/upload", data={"file": (f, "test.kicad_pcb")}, follow_redirects=True)

        assert resp.status_code == 200
        assert b"Design Review" in resp.data
        assert b"test.kicad_pcb" in resp.data


class TestSessionAPI:
    def test_missing_session_api(self, client):
        resp = client.get("/api/session/nonexistent")
        assert resp.status_code == 404
        data = json.loads(resp.data)
        assert "error" in data

    def test_session_api_after_upload(self, client):
        fixture = os.path.join(os.path.dirname(__file__), "fixtures", "simple_2layer.kicad_pcb")
        if not os.path.exists(fixture):
            pytest.skip("Test fixture not found")

        with open(fixture, "rb") as f:
            resp = client.post("/api/upload", data={"file": (f, "test.kicad_pcb")}, follow_redirects=False)

        session_id = resp.headers["Location"].split("/")[-1]
        resp = client.get(f"/api/session/{session_id}")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "session_id" in data
        assert "component_count" in data
        assert data["component_count"] > 0


class TestSelfContained:
    def test_no_external_css_js(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        assert 'href="http' not in html
        assert 'src="http' not in html
