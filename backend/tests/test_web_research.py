from fastapi.testclient import TestClient

from app.main import app
from app.models import DealClaim, DealProfile, EvidenceItem, MaterialChunk
from app.web_research import SearchResult, collect_public_web_evidence, web_stance_for_claim

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


def test_public_web_support_requires_exact_numbers_for_numeric_claim():
    claim = claim_for_web(
        "Harvey reached $1,120,000 ARR by February 2023 after enterprise legal customer growth.",
        category="financials",
    )
    chunk = public_web_chunk(
        "Public news: Harvey reported $100M ARR in 2023 after enterprise legal customer growth accelerated."
    )

    assert web_stance_for_claim("Harvey", claim, chunk) == "partially_supports"


def test_public_web_support_accepts_exact_numeric_match():
    claim = claim_for_web(
        "Harvey reached $1,120,000 ARR by February 2023 after enterprise legal customer growth.",
        category="financials",
    )
    chunk = public_web_chunk(
        "Public news: Harvey reached $1,120,000 ARR by February 2023 after enterprise legal customer growth."
    )

    assert web_stance_for_claim("Harvey", claim, chunk) == "supports"


def test_collect_public_web_evidence_dedupes_urls_per_claim(monkeypatch):
    claims = [
        claim_for_web("Acme reached $1,000,000 ARR in 2024.", claim_id="claim-1", category="financials"),
        claim_for_web("Acme signed 12 enterprise customers in 2024.", claim_id="claim-2", category="growth"),
    ]
    result = SearchResult(title="Acme update", url="https://example.com/acme-update", snippet="Acme update")

    monkeypatch.setattr("app.web_research.search_claim_sources", lambda *args, **kwargs: [result])
    monkeypatch.setattr(
        "app.web_research.evidence_from_result",
        lambda _client, _company, claim, _result: web_evidence_for_claim(claim),
    )

    evidence = collect_public_web_evidence(
        "Acme",
        DealProfile(sector="Legal tech", customer="enterprise"),
        claims,
        enabled=True,
        max_claims=2,
    )

    assert sorted(item.claimId for item in evidence) == ["claim-1", "claim-2"]


def claim_for_web(text: str, claim_id: str = "claim-1", category: str = "financials") -> DealClaim:
    return DealClaim(
        id=claim_id,
        text=text,
        category=category,
        sourceMaterial="deck",
        sourceSnippet=text,
        importance="high",
    )


def public_web_chunk(text: str) -> MaterialChunk:
    return MaterialChunk(
        id="chunk-web",
        material_id="web-news",
        deal_id="deal",
        citation="Public news source, chunk 1",
        text=text,
        sourceName="Public news",
        sourceUrl="https://example.com/news",
        sourceType="url",
        chunkIndex=1,
    )


def web_evidence_for_claim(claim: DealClaim) -> EvidenceItem:
    return EvidenceItem(
        id=f"ev-{claim.id}",
        claimId=claim.id,
        title="Relevant public web evidence",
        sourceType="public_web",
        citation="Acme update (https://example.com/acme-update)",
        snippet=claim.text,
        stance="partially_supports",
        reliability="medium",
        sourceIndependence="third_party",
    )
