from fastapi.testclient import TestClient

from app.graph import stream_llm_chunk
from app.main import app

NO_API_KEY = "DEEPSEEK_API_KEY is not configured. Add it to backend/.env."


def disable_llm(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())


def test_analysis_requires_deepseek_api_key(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200

        analyzed = client.post(f"/deals/{created.json()['id']}/analyze")

    assert analyzed.status_code == 500
    assert analyzed.json()["detail"] == NO_API_KEY


def test_vague_packet_reports_missing_api_key_before_llm_analysis(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        created = client.post("/deals", json={"company": "VagueCo", "tagline": "Future of everything", "stage": "Seed"})
        deal = created.json()
        uploaded = client.post(
            f"/deals/{deal['id']}/materials",
            files=[
                (
                    "files",
                    (
                        "overview.txt",
                        b"VagueCo is building the future with a world-class team and delightful product experience.",
                        "text/plain",
                    ),
                )
            ],
        )
        assert uploaded.status_code == 200

        analyzed = client.post(f"/deals/{deal['id']}/analyze")

    assert analyzed.status_code == 500
    assert analyzed.json()["detail"] == NO_API_KEY


def test_empty_deal_returns_clear_failure_before_llm(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        created = client.post("/deals", json={"company": "EmptyCo", "tagline": "No packet", "stage": "Screening"})
        analyzed = client.post(f"/deals/{created.json()['id']}/analyze")

    assert analyzed.status_code == 500
    assert analyzed.json()["detail"] == "Add at least one uploaded file or URL before analysis."


def test_stream_llm_chunk_coalesces_small_deltas(monkeypatch):
    monkeypatch.setattr("app.graph.LLM_STREAM_MIN_CHARS", 5)
    events = []
    emit = stream_llm_chunk(
        {"on_progress": lambda event, step, payload: events.append((event, step, payload))},
        "extract_claims",
    )

    assert emit is not None
    emit("a")
    emit("bc")
    assert events == []

    emit("de")
    assert len(events) == 1
    assert events[0][0] == "tool_delta"
    assert events[0][1] == "extract_claims"
    assert events[0][2]["rawOutput"] == "abcde"

    emit("f")
    assert len(events) == 1
