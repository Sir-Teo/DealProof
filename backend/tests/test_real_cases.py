import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import DealClaim
from app.scoring import score_claims

FIXTURES = Path(__file__).parent / "fixtures" / "real_cases"


def disable_llm(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())


def fixture_uploads(names: list[str]):
    return [
        ("files", (name, (FIXTURES / name).read_bytes(), "text/plain"))
        for name in names
    ]


def load_manifest() -> dict:
    return json.loads((FIXTURES / "manifest.json").read_text())


def create_manifest_case_deal(client: TestClient, case: dict) -> dict:
    created = client.post(
        "/deals",
        json={
            "company": case["company"],
            "tagline": "Real-world public-source diligence",
            "stage": "Real-world fixture diligence",
        },
    )
    assert created.status_code == 200
    deal = created.json()
    uploaded = client.post(f"/deals/{deal['id']}/materials", files=fixture_uploads(case["fixtures"]))
    assert uploaded.status_code == 200
    return deal


def create_real_case_deal(client: TestClient) -> dict:
    manifest = load_manifest()
    dm_case = next(case for case in manifest["cases"] if case["id"] == "dm_revenue_flow")
    apple_case = next(case for case in manifest["cases"] if case["id"] == "apple_2025_10k")
    created = client.post(
        "/deals",
        json={
            "company": dm_case["company"],
            "tagline": "Public investor materials and SEC evidence",
            "stage": "Real-world fixture diligence",
        },
    )
    assert created.status_code == 200
    deal = created.json()
    uploaded = client.post(
        f"/deals/{deal['id']}/materials",
        files=fixture_uploads(dm_case["fixtures"] + apple_case["fixtures"]),
    )
    assert uploaded.status_code == 200
    return deal


def create_large_real_case_deal(client: TestClient) -> dict:
    manifest = load_manifest()
    large_case = next(case for case in manifest["cases"] if case["id"] == "large_public_data_room")
    created = client.post(
        "/deals",
        json={
            "company": large_case["company"],
            "tagline": "Large public-material data room",
            "stage": "Expanded real-world fixture diligence",
        },
    )
    assert created.status_code == 200
    deal = created.json()
    uploaded = client.post(
        f"/deals/{deal['id']}/materials",
        files=fixture_uploads(large_case["fixtures"]),
    )
    assert uploaded.status_code == 200
    assert len(uploaded.json()["materials"]) >= large_case["expected"]["minMaterials"]
    return deal


def test_real_case_fixture_manifest_is_complete():
    manifest = load_manifest()

    assert manifest["snapshotDate"]
    assert len(manifest["cases"]) == 5
    for case in manifest["cases"]:
        assert case["sourceUrl"].startswith("https://")
        for name in case["fixtures"]:
            path = FIXTURES / name
            assert path.exists()
            assert path.read_text().strip()


@pytest.mark.parametrize("case_id", [
    "dm_revenue_flow",
    "apple_2025_10k",
    "large_public_data_room",
    "microsoft_2025_annual_report",
    "perplexity_public_web",
])
def test_five_real_case_quality_gate(monkeypatch, case_id):
    disable_llm(monkeypatch)
    manifest = load_manifest()
    case = next(item for item in manifest["cases"] if item["id"] == case_id)
    expected = case.get("expected", {})

    with TestClient(app) as client:
        deal = create_manifest_case_deal(client, case)
        analyzed = client.post(f"/deals/{deal['id']}/analyze")
        assert analyzed.status_code == 200
        payload = analyzed.json()
        question = expected.get("chatQuestion") or (expected.get("chatQuestions") or ["What are the strongest and weakest claims?"])[0]
        answer = client.post(f"/deals/{deal['id']}/chat", json={"question": question})

    claims = payload["claims"]
    statuses = {claim["status"] for claim in claims}
    evidence = payload["evidence"]
    memo = payload["memo"]
    strengths = "\n".join(memo["keyStrengths"])

    assert len(claims) >= expected.get("minClaims", 1)
    assert len({claim["text"] for claim in claims}) == len(claims)
    assert len(evidence) >= len(claims)
    assert all(item["citation"] for item in evidence)
    assert any(item["quoteSpan"] for item in evidence if item["stance"] != "not_found")
    assert set(expected.get("requiresStatuses", [])).issubset(statuses)
    assert memo["executiveSummary"]
    assert memo["thesisAssessment"]
    assert memo["evidenceMap"]
    assert memo["materialRisks"]
    assert memo["followUpQuestions"]
    assert answer.status_code == 200
    assert answer.json()["citations"]

    _, expected_grade, _ = score_claims([DealClaim.model_validate(claim) for claim in claims])
    assert memo["overallGrade"] == expected_grade
    for claim in claims:
        if claim["status"] in {"weak", "missing", "contradicted"}:
            assert claim["text"][:56] not in strengths


def test_real_case_agent_output_has_supported_weak_and_contradicted_claims(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        deal = create_real_case_deal(client)
        analyzed = client.post(f"/deals/{deal['id']}/analyze")
        assert analyzed.status_code == 200
        payload = analyzed.json()

    claim_texts = [claim["text"] for claim in payload["claims"]]
    statuses = {claim["status"] for claim in payload["claims"]}
    evidence_stances = {item["stance"] for item in payload["evidence"]}

    assert len(claim_texts) >= 6
    assert len(claim_texts) == len(set(claim_texts))
    assert {"supported", "weak", "contradicted"}.issubset(statuses)
    assert {"supports", "partially_supports", "contradicts"}.issubset(evidence_stances)
    assert any("2.56M ARR" in claim["text"] and claim["status"] in {"weak", "supported"} for claim in payload["claims"])
    assert any("no direct" in claim["text"].lower() and claim["status"] == "contradicted" for claim in payload["claims"])
    assert any("75.4%" in claim["text"] and claim["status"] == "supported" for claim in payload["claims"])

    _, expected_grade, counts = score_claims([DealClaim.model_validate(claim) for claim in payload["claims"]])
    assert payload["memo"]["overallGrade"] == expected_grade
    assert sum(counts.values()) == len(payload["claims"])


def test_real_case_chat_returns_citations(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        deal = create_real_case_deal(client)
        analyzed = client.post(f"/deals/{deal['id']}/analyze")
        assert analyzed.status_code == 200

        answer = client.post(
            f"/deals/{deal['id']}/chat",
            json={"question": "Can we trust the ROI and no-competitor claims?"},
        )

    assert answer.status_code == 200
    payload = answer.json()
    assert payload["answer"]
    assert payload["citations"]
    assert payload["confidence"] in {"low", "medium", "high"}


def test_large_real_case_data_room_output_quality(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        deal = create_large_real_case_deal(client)
        analyzed = client.post(f"/deals/{deal['id']}/analyze")
        assert analyzed.status_code == 200
        payload = analyzed.json()

    claims = payload["claims"]
    statuses = {claim["status"] for claim in claims}
    claim_text = "\n".join(claim["text"] for claim in claims)
    citations = {item["citation"].split(", chunk")[0] for item in payload["evidence"]}

    assert len(payload["materials"]) >= 14
    assert len(claims) >= 14
    assert len({claim["text"] for claim in claims}) == len(claims)
    assert {"supported", "weak", "contradicted"}.issubset(statuses)
    assert "DMs Revenue Flow can reach $2.56M ARR by month 24." in claim_text
    assert "DMs Revenue Flow has no direct or adjacent competitors" in claim_text
    assert any(claim["status"] == "contradicted" and "no direct or adjacent competitors" in claim["text"] for claim in claims)
    assert any(claim["status"] in {"weak", "contradicted"} and "100-500x ROI" in claim["text"] for claim in claims)
    assert any(claim["status"] == "contradicted" and "$500B+ global digital marketing TAM" in claim["text"] for claim in claims)
    assert any(claim["status"] == "contradicted" and "independently verified" in claim["text"] for claim in claims)
    assert any(claim["status"] == "supported" and "75.4%" in claim["text"] for claim in claims)
    assert any(claim["status"] == "contradicted" and "no manufacturing purchase obligations" in claim["text"] for claim in claims)
    assert len(citations) >= 8

    _, expected_grade, _ = score_claims([DealClaim.model_validate(claim) for claim in claims])
    assert payload["memo"]["overallGrade"] == expected_grade
    assert payload["memo"]["materialRisks"]
    assert payload["memo"]["followUpQuestions"]


def test_large_real_case_chat_answers_multiple_questions(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        deal = create_large_real_case_deal(client)
        analyzed = client.post(f"/deals/{deal['id']}/analyze")
        assert analyzed.status_code == 200

        roi_answer = client.post(
            f"/deals/{deal['id']}/chat",
            json={"question": "Which public materials support the ARR and ROI claims?"},
        )
        risk_answer = client.post(
            f"/deals/{deal['id']}/chat",
            json={"question": "What are the biggest unsupported or contradicted claims?"},
        )

    assert roi_answer.status_code == 200
    assert risk_answer.status_code == 200
    assert roi_answer.json()["citations"]
    assert risk_answer.json()["citations"]


@pytest.mark.real_live
def test_real_live_refresh_script_is_opt_in():
    if os.getenv("REAL_CASE_LIVE") != "1":
        pytest.skip("Set REAL_CASE_LIVE=1 and run scripts/fetch_real_cases.py to refresh public snapshots.")
