from fastapi.testclient import TestClient

from app.main import app
from app.models import DealClaim
from app.scoring import score_claims


def disable_llm(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())


def analyze_packet(client: TestClient, materials: list[tuple[str, bytes]]) -> dict:
    created = client.post(
        "/deals",
        json={"company": "Northstar Ops", "tagline": "AI workflow automation", "stage": "Series A diligence"},
    )
    assert created.status_code == 200
    deal = created.json()
    files = [("files", (name, body, "text/plain")) for name, body in materials]
    uploaded = client.post(f"/deals/{deal['id']}/materials", files=files)
    assert uploaded.status_code == 200

    analyzed = client.post(f"/deals/{deal['id']}/analyze")
    assert analyzed.status_code == 200
    return analyzed.json()


def test_seeded_agent_output_is_concrete_and_memo_grade_matches(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200

        analyzed = client.post(f"/deals/{created.json()['id']}/analyze")
        assert analyzed.status_code == 200
        deal = analyzed.json()

    claim_texts = [claim["text"] for claim in deal["claims"]]
    assert len(claim_texts) >= 6
    assert len(claim_texts) == len(set(claim_texts))
    assert all(len(text) >= 20 for text in claim_texts)
    assert all(item["citation"] for item in deal["evidence"])

    _, expected_grade, counts = score_claims([DealClaim.model_validate(claim) for claim in deal["claims"]])
    assert deal["memo"]["overallGrade"] == expected_grade
    assert counts["weak"] + counts["missing"] + counts["supported"] + counts["contradicted"] == len(deal["claims"])


def test_direct_numeric_support_can_be_supported(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        deal = analyze_packet(
            client,
            [
                (
                    "deck.txt",
                    b"Revenue grew from 1000000 to 2000000 in 2025. Customers save 12 hours per week using automation.",
                ),
                (
                    "financials_summary.txt",
                    b"Revenue grew from 1000000 to 2000000 in 2025. Gross margin increased from 62% to 68%.",
                ),
            ],
        )

    assert any(claim["status"] == "supported" for claim in deal["claims"])
    supported = [item for item in deal["evidence"] if item["stance"] == "supports"]
    assert supported
    assert any("financials_summary.txt" in item["citation"] for item in supported)


def test_competitor_contradiction_is_detected(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        deal = analyze_packet(
            client,
            [
                (
                    "deck.txt",
                    b"The company claims no direct competitors exist. Customers save 12 hours per week using automation.",
                ),
                (
                    "customer_reference.txt",
                    b"Procurement notes list ZapFlow and OpsPilot as direct competitors in workflow automation.",
                ),
            ],
        )

    contradicted = [claim for claim in deal["claims"] if claim["status"] == "contradicted"]
    assert contradicted
    assert any("no direct competitors" in claim["text"].lower() for claim in contradicted)
    assert any(item["stance"] == "contradicts" for item in deal["evidence"])


def test_vague_packet_returns_clear_failure(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        created = client.post("/deals", json={"company": "VagueCo", "tagline": "Future of everything", "stage": "Seed"})
        deal = created.json()
        files = [
            (
                "files",
                (
                    "overview.txt",
                    b"VagueCo is building the future with a world-class team and delightful product experience.",
                    "text/plain",
                ),
            )
        ]
        client.post(f"/deals/{deal['id']}/materials", files=files)

        analyzed = client.post(f"/deals/{deal['id']}/analyze")

    assert analyzed.status_code == 500
    assert analyzed.json()["detail"] == "No diligence claims were extracted from the supplied materials."


def test_empty_deal_returns_clear_failure(monkeypatch):
    disable_llm(monkeypatch)
    with TestClient(app) as client:
        created = client.post("/deals", json={"company": "EmptyCo", "tagline": "No packet", "stage": "Screening"})
        analyzed = client.post(f"/deals/{created.json()['id']}/analyze")

    assert analyzed.status_code == 500
    assert analyzed.json()["detail"] == "Add at least one uploaded file or URL before analysis."
