from fastapi.testclient import TestClient

from app.main import app

NO_API_KEY = "DEEPSEEK_API_KEY is not configured. Add it to backend/.env."


def test_public_web_step_is_not_reached_without_api_key(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())

    with TestClient(app) as client:
        created = client.post("/deals/demo")
        deal_id = created.json()["id"]
        streamed = client.post(f"/deals/{deal_id}/analyze-stream")

    assert streamed.status_code == 200
    body = streamed.text
    assert '"event": "run_error"' in body
    assert NO_API_KEY in body
    assert '"step": "search_public_web"' not in body
