from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.models import DealClaim, QualityReview, RiskMemo
from app.parsers import UrlFetchError


def test_demo_deal_can_be_created_and_loaded():
    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200
        deal = created.json()
        assert deal["claims"] == []
        assert deal["evidence"] == []
        assert deal["memo"] is None
        assert deal["chatHistory"] == []

        loaded = client.get(f"/deals/{deal['id']}")
        assert loaded.status_code == 200
        assert len(loaded.json()["materials"]) >= 3


def test_settings_can_be_saved_and_loaded():
    with TestClient(app) as client:
        updated = client.patch(
            "/settings",
            json={
                "maxClaims": 9,
                "maxClaimsPerMaterial": 4,
                "deepseekModel": "deepseek-v4-pro",
                "webResearchEnabled": False,
            },
        )
        loaded = client.get("/settings")

    assert updated.status_code == 200
    assert loaded.status_code == 200
    assert loaded.json() == {
        "maxClaims": 9,
        "maxClaimsPerMaterial": 4,
        "deepseekModel": "deepseek-v4-pro",
        "webResearchEnabled": False,
    }


def test_settings_reject_legacy_deepseek_models():
    with TestClient(app) as client:
        response = client.patch(
            "/settings",
            json={
                "maxClaims": 6,
                "maxClaimsPerMaterial": 6,
                "deepseekModel": "deepseek-chat",
                "webResearchEnabled": True,
            },
        )

    assert response.status_code == 422


def test_add_url_returns_readable_fetch_failure(monkeypatch):
    async def fail_fetch(_url: str) -> str:
        raise UrlFetchError("Failed to fetch URL: upstream returned HTTP 403.")

    monkeypatch.setattr("app.main.fetch_url_text", fail_fetch)

    with TestClient(app) as client:
        created = client.post("/deals", json={})
        assert created.status_code == 200
        deal_id = created.json()["id"]

        response = client.post(
            f"/deals/{deal_id}/urls",
            json={"url": "https://www.sec.gov/Archives/edgar/data/1387222/000095010326007678/xslF345X06/ownership.xml"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Failed to fetch URL: upstream returned HTTP 403."


def test_risk_memo_accepts_structured_evidence_map_items():
    memo = RiskMemo.model_validate(
        {
            "company": "CaviClear AI",
            "overallGrade": "yellow",
            "investmentQuestion": "Should we invest?",
            "keyStrengths": ["Initial traction"],
            "materialRisks": ["Founder-supplied metrics"],
            "followUpQuestions": ["Can ARR be verified?"],
            "icRecommendation": "Continue only with validation.",
            "evidenceMap": [
                {
                    "claim": "ARR reached $235k in April.",
                    "strength": "weak",
                    "confidence": "low",
                    "status": "Needs independent verification",
                }
            ],
        }
    )

    assert memo.evidenceMap == [
        "claim: ARR reached $235k in April.; strength: weak; confidence: low; status: Needs independent verification"
    ]


NO_API_KEY = "DEEPSEEK_API_KEY is not configured. Add it to backend/.env."


def test_analysis_stream_reports_missing_api_key(monkeypatch):
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
        assert '"event": "run_error"' in body
        assert NO_API_KEY in body


def test_analysis_endpoint_reports_missing_api_key(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())

    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200
        deal_id = created.json()["id"]

        analyzed = client.post(f"/deals/{deal_id}/analyze")

    assert analyzed.status_code == 500
    assert analyzed.json()["detail"] == NO_API_KEY


def test_chat_before_analysis_does_not_require_api_key():
    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200
        deal_id = created.json()["id"]

        response = client.post(f"/deals/{deal_id}/chat", json={"question": "Can we trust this deal?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Run analysis before asking diligence questions."


def test_claim_review_disposition_and_diligence_request_export(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())
    deal_id = "deal-review-workflow-test"
    claim = DealClaim(
        id="claim-01",
        text="The product is fully HIPAA compliant.",
        category="compliance",
        sourceMaterial="deck.txt",
        sourceSnippet="HIPAA compliant",
        importance="high",
        status="missing",
        riskRationale="No compliance evidence was found.",
        confidence="low",
        qualityScore=20,
        verificationNeed="Request compliance evidence.",
        decisionImpact="high",
        statusReason="No quote-backed evidence supports this claim.",
        resolutionRequest="Provide HIPAA audit or compliance documentation.",
    )
    memo = RiskMemo(
        company="ReviewCo",
        overallGrade="red",
        investmentQuestion="Can ReviewCo pass compliance diligence?",
        keyStrengths=[],
        materialRisks=["Compliance evidence is missing."],
        followUpQuestions=[claim.resolutionRequest],
        icRecommendation="Needs diligence.",
    )
    review = QualityReview(
        memoReadinessScore=40,
        readinessStatus="needs_diligence",
        topGatingIssue="claim-01: compliance evidence is missing.",
        approvedDiligenceRequests=[claim.resolutionRequest],
    )

    db.init_db()
    try:
        db.create_deal(deal_id, "ReviewCo", stage="Seed")
    except Exception:
        pass
    db.save_analysis(deal_id, [claim], [], memo, review, "2026-05-25T00:00:00+00:00")

    with TestClient(app) as client:
        patched = client.patch(
            f"/deals/{deal_id}/claims/{claim.id}/review",
            json={
                "reviewerDisposition": "ic_blocker",
                "reviewerNotes": "Must resolve before IC.",
                "resolutionRequest": "Send HIPAA audit report and policy evidence.",
            },
        )
        exported = client.get(f"/deals/{deal_id}/export-diligence-requests")

    assert patched.status_code == 200
    updated_claim = patched.json()["claims"][0]
    assert updated_claim["reviewerDisposition"] == "ic_blocker"
    assert updated_claim["resolutionRequest"] == "Send HIPAA audit report and policy evidence."
    assert patched.json()["qualityReview"]["readinessStatus"] == "blocked"
    assert exported.status_code == 200
    assert "Send HIPAA audit report and policy evidence." in exported.text
