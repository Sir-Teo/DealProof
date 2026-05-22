from fastapi.testclient import TestClient

from app.main import app
from app.models import EvidenceItem


def disable_llm(monkeypatch):
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())


def public_web_evidence(claim_id: str, stance: str = "supports") -> EvidenceItem:
    return EvidenceItem(
        id="ev-public-01",
        claimId=claim_id,
        title="Public web supporting evidence",
        sourceType="public_web",
        citation="Public source (https://example.com/source)",
        snippet="Public source says revenue grew from 1000000 to 2000000 in 2025.",
        stance=stance,  # type: ignore[arg-type]
        reliability="high",
        sourceIndependence="third_party",
        relevanceScore=0.86,
        quoteSpan="Public source says revenue grew from 1000000 to 2000000 in 2025.",
        sourceName="Public source",
        sourceUrl="https://example.com/source",
        chunkIndex=1,
        retrievedAt="2026-05-22T12:00:00+00:00",
    )


def test_public_web_evidence_is_attached_and_scored(monkeypatch):
    disable_llm(monkeypatch)

    def fake_web(company, profile, claims, on_progress=None):
        target = next(claim for claim in claims if "Revenue grew from 1000000 to 2000000" in claim.text)
        if on_progress:
            on_progress("web_query", {"label": '"Northstar Ops" revenue', "query": '"Northstar Ops" revenue', "claimId": target.id})
            on_progress("web_evidence", {"label": "supports: Public source", "claimId": target.id, "sourceName": "Public source", "sourceUrl": "https://example.com/source", "stance": "supports", "relevanceScore": "0.86", "webEvidence": 1})
        return [public_web_evidence(target.id)]

    monkeypatch.setattr("app.graph.collect_public_web_evidence", fake_web)

    with TestClient(app) as client:
        created = client.post("/deals", json={"company": "Northstar Ops", "tagline": "Ops", "stage": "Series A"})
        deal_id = created.json()["id"]
        uploaded = client.post(
            f"/deals/{deal_id}/materials",
            files=[("files", ("deck.txt", b"Claim: Revenue grew from 1000000 to 2000000 in 2025.", "text/plain"))],
        )
        assert uploaded.status_code == 200
        analyzed = client.post(f"/deals/{deal_id}/analyze")

    assert analyzed.status_code == 200
    payload = analyzed.json()
    web_items = [item for item in payload["evidence"] if item["sourceType"] == "public_web"]
    assert web_items
    assert web_items[0]["sourceUrl"] == "https://example.com/source"
    assert web_items[0]["quoteSpan"]
    assert web_items[0]["sourceIndependence"] == "third_party"
    assert any(claim["status"] == "supported" for claim in payload["claims"])


def test_public_web_failure_does_not_fail_analysis(monkeypatch):
    disable_llm(monkeypatch)

    def failing_web(company, profile, claims, on_progress=None):
        raise TimeoutError("search timed out")

    monkeypatch.setattr("app.graph.collect_public_web_evidence", failing_web)

    with TestClient(app) as client:
        created = client.post("/deals/demo")
        deal_id = created.json()["id"]
        analyzed = client.post(f"/deals/{deal_id}/analyze")

    assert analyzed.status_code == 200
    assert analyzed.json()["claims"]


def test_analysis_stream_includes_public_web_step(monkeypatch):
    disable_llm(monkeypatch)

    with TestClient(app) as client:
        created = client.post("/deals/demo")
        deal_id = created.json()["id"]
        streamed = client.post(f"/deals/{deal_id}/analyze-stream")

    assert streamed.status_code == 200
    body = streamed.text
    assert '"step": "search_public_web"' in body
    assert '"toolName": "search_public_web"' in body


def test_analysis_stream_includes_public_web_research_details(monkeypatch):
    disable_llm(monkeypatch)

    def fake_web(company, profile, claims, on_progress=None):
        if on_progress:
            query = '"CaviClear" competitors'
            on_progress("web_query", {"label": query, "query": query, "claimId": claims[0].id})
            on_progress("web_results", {"label": "2 search results", "query": query, "results": 2, "claimId": claims[0].id})
        return []

    monkeypatch.setattr("app.graph.collect_public_web_evidence", fake_web)

    with TestClient(app) as client:
        created = client.post("/deals/demo")
        deal_id = created.json()["id"]
        streamed = client.post(f"/deals/{deal_id}/analyze-stream")

    body = streamed.text
    assert '"event": "tool_delta"' in body
    assert '"webEvent": "web_query"' in body
    assert '"query": "\\"CaviClear\\" competitors"' in body
    assert '"webEvent": "web_results"' in body
