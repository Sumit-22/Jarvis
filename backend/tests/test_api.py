from __future__ import annotations

from fastapi.testclient import TestClient

from jarvis.main import create_app
from jarvis.registry.seed_workflows import SEEDS


def _client(make_jarvis, settings):
    j = make_jarvis()
    return TestClient(create_app(settings, jarvis=j)), j


def test_health(make_jarvis, settings):
    c, _ = _client(make_jarvis, settings)
    with c:
        r = c.get("/api/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"
        assert "api_key" not in r.text.lower()


def test_non_local_origin_rejected(make_jarvis, settings):
    c, _ = _client(make_jarvis, settings)
    with c:
        assert c.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.get("/api/health", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200


def test_command_wait_and_usage(make_jarvis, settings):
    c, _ = _client(make_jarvis, settings)
    with c:
        r = c.post("/api/command?wait=true", json={"text": "play a video about cats"})
        assert r.json()["status"] == "succeeded" and r.json()["route"] == "local"
        u = c.get("/api/usage").json()
        assert u["cache_hits"] == 1 and u["planner_calls"] == 0
        assert len(c.get("/api/workflows").json()) == len(SEEDS)


def test_websocket_streams_events(make_jarvis, settings):
    c, _ = _client(make_jarvis, settings)
    with c, c.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        c.post("/api/command?wait=true", json={"text": "play a video about cats"})
        types = set()
        for _ in range(30):
            ev = ws.receive_json()
            types.add(ev["type"])
            if ev["type"] == "run_finished":
                break
        assert {"step_started", "step_finished", "run_finished"} <= types


def test_secrets_never_logged(make_jarvis, settings):
    from jarvis import logging as jlog
    assert jlog.redact({"NOTION_TOKEN": "abc", "nested": {"llm_api_key": "x"}, "ok": 1}) == {
        "NOTION_TOKEN": "***", "nested": {"llm_api_key": "***"}, "ok": 1}


def test_dashboard_cache_headers(make_jarvis, settings):
    """index.html is revalidated every time (a stale one points at deleted asset files); hashed assets are immutable."""
    import pytest
    assets = sorted((settings.frontend_dist / "assets").glob("*.js")) if settings.frontend_dist.is_dir() else []
    if not assets:
        pytest.skip("dashboard not built")
    c, _ = _client(make_jarvis, settings)
    assert c.get("/").headers["cache-control"] == "no-cache"
    assert "immutable" in c.get(f"/assets/{assets[0].name}").headers["cache-control"]
