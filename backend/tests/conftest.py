import pytest


@pytest.fixture(autouse=True)
def disable_live_web_research(monkeypatch):
    monkeypatch.setattr("app.graph.collect_public_web_evidence", lambda company, profile, claims, on_progress=None: [])
