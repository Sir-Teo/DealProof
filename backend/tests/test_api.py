from fastapi.testclient import TestClient

from app.main import app


def test_demo_deal_can_be_created_and_loaded():
    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200
        deal = created.json()

        loaded = client.get(f"/deals/{deal['id']}")
        assert loaded.status_code == 200
        assert len(loaded.json()["materials"]) >= 3


def test_analysis_stream_emits_progress_events(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())

    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200
        deal = created.json()

        streamed = client.post(f"/deals/{deal['id']}/analyze-stream")
        assert streamed.status_code == 200
        body = streamed.text
        assert '"event": "run_start"' in body
        assert '"event": "tool_start"' in body
        assert '"event": "tool_complete"' in body
        assert '"event": "step_complete"' in body
        assert '"event": "run_complete"' in body
