from fastapi.testclient import TestClient

from app.main import app
from app.models import DealClaim
from app.scoring import score_claims


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


def test_analysis_returns_quality_review_and_claim_review_patch(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())

    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200
        deal_id = created.json()["id"]

        analyzed = client.post(f"/deals/{deal_id}/analyze")
        assert analyzed.status_code == 200
        deal = analyzed.json()
        assert deal["qualityReview"]["memoReadinessScore"] >= 0
        claim_id = deal["claims"][0]["id"]

        patched = client.patch(
            f"/deals/{deal_id}/claims/{claim_id}/review",
            json={"reviewerStatus": "needs_evidence", "reviewerNotes": "Ask for customer-level backup."},
        )

        assert patched.status_code == 200
        claim = next(item for item in patched.json()["claims"] if item["id"] == claim_id)
        assert claim["reviewerStatus"] == "needs_evidence"
        assert claim["reviewerNotes"] == "Ask for customer-level backup."


def test_claim_status_review_refreshes_memo_and_quality_review(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())

    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200
        deal_id = created.json()["id"]

        analyzed = client.post(f"/deals/{deal_id}/analyze")
        assert analyzed.status_code == 200
        deal = analyzed.json()

        updated = deal
        for claim in deal["claims"]:
            patched = client.patch(f"/deals/{deal_id}/claims/{claim['id']}/review", json={"status": "supported"})
            assert patched.status_code == 200
            updated = patched.json()

    _, expected_grade, _ = score_claims([DealClaim.model_validate(claim) for claim in updated["claims"]])
    assert expected_grade == "green"
    assert updated["memo"]["overallGrade"] == expected_grade
    assert "High-importance claims remain weak or missing." not in updated["qualityReview"]["globalWarnings"]
