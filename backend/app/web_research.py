from __future__ import annotations

import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Callable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from .models import DealClaim, DealProfile, EvidenceItem, MaterialChunk
from .parsers import UrlFetchError, validate_fetch_url
from .retrieval import evidence_stance_for_chunk, keywords, quote_span_for_claim, relevance_score

WEB_SEARCH_ENABLED = os.getenv("DEALPROOF_WEB_SEARCH_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
WEB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("DEALPROOF_WEB_SEARCH_TIMEOUT_SECONDS", "8"))
WEB_SEARCH_MAX_CLAIMS = int(os.getenv("DEALPROOF_WEB_SEARCH_MAX_CLAIMS", "6"))
WEB_SEARCH_RESULTS_PER_CLAIM = int(os.getenv("DEALPROOF_WEB_SEARCH_RESULTS_PER_CLAIM", "3"))
WEB_SEARCH_MAX_PAGE_CHARS = int(os.getenv("DEALPROOF_WEB_SEARCH_MAX_PAGE_CHARS", "12000"))
WebProgress = Callable[[str, dict[str, str | int]], None]


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


def collect_public_web_evidence(
    company: str,
    profile: DealProfile,
    claims: list[DealClaim],
    on_progress: WebProgress | None = None,
) -> list[EvidenceItem]:
    if not WEB_SEARCH_ENABLED:
        emit_web_progress(on_progress, "web_disabled", {"label": "Public web search is disabled"})
        return []

    selected_claims = sorted(claims, key=claim_priority_key)[:WEB_SEARCH_MAX_CLAIMS]
    emit_web_progress(
        on_progress,
        "web_start",
        {"label": f"Researching {len(selected_claims)} priority claims in parallel", "claims": len(selected_claims)},
    )
    evidence: list[EvidenceItem] = []
    seen_urls: set[str] = set()
    seen_lock = Lock()

    def research_claim(claim: DealClaim) -> list[EvidenceItem]:
        claim_evidence: list[EvidenceItem] = []
        with httpx.Client(
            timeout=httpx.Timeout(WEB_SEARCH_TIMEOUT_SECONDS, connect=4),
            follow_redirects=True,
            headers={"User-Agent": "DealProof/0.1 public diligence research"},
        ) as client:
            emit_web_progress(
                on_progress,
                "web_claim",
                {"label": claim.text[:140], "claimId": claim.id, "category": claim.category, "importance": claim.importance},
            )
            for result in search_claim_sources(client, company, profile, claim, on_progress=on_progress):
                normalized = normalize_url(result.url)
                if not normalized:
                    continue
                with seen_lock:
                    if normalized in seen_urls:
                        continue
                    seen_urls.add(normalized)
                emit_web_progress(
                    on_progress,
                    "web_fetch",
                    {"label": result.title[:140] or result.url, "sourceUrl": result.url, "sourceName": result.title[:120]},
                )
                item = evidence_from_result(client, company, claim, result)
                if item:
                    claim_evidence.append(item)
                    emit_web_progress(
                        on_progress,
                        "web_evidence",
                        {
                            "label": f"{item.stance.replace('_', ' ')}: {item.sourceName or item.citation}",
                            "claimId": claim.id,
                            "sourceUrl": item.sourceUrl or "",
                            "sourceName": item.sourceName or "",
                            "stance": item.stance,
                            "relevanceScore": f"{item.relevanceScore:.2f}",
                            "webEvidence": 0,
                        },
                    )
        return claim_evidence

    max_workers = min(len(selected_claims), WEB_SEARCH_MAX_CLAIMS)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(research_claim, claim): claim for claim in selected_claims}
        for future in as_completed(futures):
            try:
                evidence.extend(future.result())
            except Exception:
                pass

    emit_web_progress(on_progress, "web_complete", {"label": f"Attached {len(evidence)} public web evidence items", "webEvidence": len(evidence)})
    return evidence


def claim_priority_key(claim: DealClaim) -> tuple[int, int, int]:
    importance_rank = {"high": 0, "medium": 1, "low": 2}
    status_rank = {"missing": 0, "weak": 1, "contradicted": 2, "supported": 3}
    category_rank = {
        "customer_roi": 0,
        "financials": 1,
        "growth": 2,
        "competition": 3,
        "market": 4,
        "compliance": 5,
        "legal": 6,
    }
    return (
        importance_rank.get(claim.importance, 3),
        status_rank.get(claim.status, 4),
        category_rank.get(claim.category, 9),
    )


def search_claim_sources(
    client: httpx.Client,
    company: str,
    profile: DealProfile,
    claim: DealClaim,
    on_progress: WebProgress | None = None,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    for query in web_queries(company, profile, claim):
        emit_web_progress(on_progress, "web_query", {"label": query, "query": query, "claimId": claim.id})
        query_results = duckduckgo_search(client, query, limit=WEB_SEARCH_RESULTS_PER_CLAIM)
        emit_web_progress(
            on_progress,
            "web_results",
            {"label": f"{len(query_results)} search results", "query": query, "results": len(query_results), "claimId": claim.id},
        )
        for result in query_results:
            normalized = normalize_url(result.url)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            results.append(result)
            if len(results) >= WEB_SEARCH_RESULTS_PER_CLAIM:
                return results
    return results


def emit_web_progress(on_progress: WebProgress | None, event: str, payload: dict[str, str | int]) -> None:
    if on_progress:
        on_progress(event, payload)


def web_queries(company: str, profile: DealProfile, claim: DealClaim) -> list[str]:
    claim_terms = " ".join(list(keywords(claim.text))[:8])
    sector = profile.sector.lower()
    customer = profile.customer.lower()

    if claim.category == "competition":
        # Surface actual competitors rather than asking about the company itself
        sector_context = f"{sector} {customer}" if customer != "unknown" else sector
        return list(dict.fromkeys([
            f"{sector_context} software competitors alternatives 2024",
            f'"{company}" competitors "alternative to" OR "versus" OR "vs"',
            f"{sector_context} vendors list comparison",
        ]))

    if claim.category == "market":
        return list(dict.fromkeys([
            f"{sector} market size TAM {customer} 2024 report",
            f'"{company}" {sector} market opportunity billion',
            f"{sector} {customer} industry analysts forecast",
        ]))

    if claim.category == "customer_roi":
        return list(dict.fromkeys([
            f'"{company}" customer case study ROI results',
            f'"{company}" customer testimonial savings hours',
            f"{sector} {customer} ROI benchmark study",
        ]))

    category_context = {
        "financials": "annual report filing revenue gross margin",
        "growth": "customers revenue growth traction",
        "compliance": "security compliance regulatory audit",
        "legal": "lawsuit patent legal risk",
        "fundraising": "funding round valuation investors",
        "product": "product review customers integration",
        "team": "founder background LinkedIn experience",
        "go_to_market": "go to market sales channel partners",
        "retention": "churn NRR net revenue retention",
        "pricing": "pricing model contract value",
        "operations": "operations infrastructure scalability",
    }.get(claim.category, profile.sector)

    return list(dict.fromkeys([
        f'"{company}" {category_context} {claim_terms}',
        f'"{company}" {claim.category.replace("_", " ")} evidence',
        f'"{company}" {profile.sector} {category_context}',
    ]))


def duckduckgo_search(client: httpx.Client, query: str, limit: int = 3) -> list[SearchResult]:
    try:
        response = client.get(f"https://duckduckgo.com/html/?q={quote_plus(query)}")
        response.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[SearchResult] = []
    for result in soup.select(".result"):
        link = result.select_one("a.result__a")
        if not link:
            continue
        url = extract_result_url(link.get("href", ""))
        if not url or should_skip_url(url):
            continue
        title = link.get_text(" ", strip=True)
        snippet_node = result.select_one(".result__snippet")
        snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
        results.append(SearchResult(title=title or url, url=url, snippet=snippet))
        if len(results) >= limit:
            break
    return results


def extract_result_url(href: str) -> str:
    if not href:
        return ""
    parsed = urlparse(href)
    if parsed.query:
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return unquote(uddg[0])
    return href if href.startswith(("http://", "https://")) else ""


def evidence_from_result(
    client: httpx.Client,
    company: str,
    claim: DealClaim,
    result: SearchResult,
) -> EvidenceItem | None:
    text = fetch_public_text(client, result.url)
    if not text and not result.snippet:
        return None
    title = result.title[:160] or source_name_for_url(result.url)
    page_text = "\n".join(part for part in [title, result.snippet, text] if part).strip()
    chunk = MaterialChunk(
        id=f"web-{uuid.uuid4().hex[:10]}",
        material_id=f"web-{source_name_for_url(result.url)}",
        deal_id="public-web",
        citation=f"{title} ({result.url})",
        text=page_text[:WEB_SEARCH_MAX_PAGE_CHARS],
        sourceName=title,
        sourceUrl=result.url,
        sourceType="url",
        chunkIndex=1,
    )
    score = relevance_score(claim, chunk)
    if score < minimum_relevance_for_claim(claim):
        return None
    stance = web_stance_for_claim(company, claim, chunk)
    quote = quote_span_for_claim(claim, chunk, stance=stance)
    if stance in {"supports", "contradicts"} and not quote:
        return None
    return EvidenceItem(
        id=f"ev-{uuid.uuid4().hex[:10]}",
        claimId=claim.id,
        title=web_title_for_stance(stance),
        sourceType="public_web",
        citation=chunk.citation,
        snippet=chunk.text[:420],
        stance=stance,  # type: ignore[arg-type]
        reliability="high" if stance in {"supports", "contradicts"} else "medium",
        sourceIndependence="third_party",
        relevanceScore=score,
        quoteSpan=quote,
        sourceName=title,
        sourceUrl=result.url,
        chunkIndex=1,
        retrievedAt=datetime.now(timezone.utc).isoformat(),
    )


def fetch_public_text(client: httpx.Client, url: str) -> str:
    if should_skip_url(url):
        return ""
    try:
        validate_fetch_url(url)
    except UrlFetchError:
        return ""
    try:
        response = client.get(url)
        response.raise_for_status()
    except Exception:
        return ""
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "text/plain" not in content_type and content_type:
        return ""
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "form", "nav", "footer"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    return f"{title}\n{body}"[:WEB_SEARCH_MAX_PAGE_CHARS]


def web_stance_for_claim(company: str, claim: DealClaim, chunk: MaterialChunk) -> str:
    local_stance = evidence_stance_for_chunk(claim, chunk)
    if local_stance == "contradicts":
        return local_stance
    # When the claim denies competition and the web page names actual competitors,
    # that's a contradiction even if the company name isn't mentioned.
    if claim.category == "competition" and denies_competition(claim.text):
        if names_competitor(company, chunk.text) or competitor_list_page(chunk.text):
            return "contradicts"
    if local_stance == "supports" and company_or_metric_matches(company, claim, chunk.text):
        return "supports"
    return "partially_supports"


def company_or_metric_matches(company: str, claim: DealClaim, text: str) -> bool:
    lower = text.lower()
    company_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", company.lower()) if len(token) > 2}
    number_match = bool(re.findall(r"\d", claim.text)) and bool(set(re.findall(r"\d[\d,.]*%?", claim.text)) & set(re.findall(r"\d[\d,.]*%?", text)))
    return bool(company_tokens & set(re.findall(r"[a-zA-Z0-9]+", lower))) or number_match


def denies_competition(text: str) -> bool:
    lower = text.lower()
    return any(
        phrase in lower
        for phrase in [
            "no direct competitor",
            "no direct competitors",
            "no adjacent competitors",
            "no competitors",
            "no direct competition",
        ]
    )


def names_competitor(company: str, text: str) -> bool:
    lower = text.lower()
    if not any(term in lower for term in ["competitor", "competitors", "alternatives", "versus", "competes with"]):
        return False
    company_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", company.lower()) if len(token) > 2}
    capitalized_names = {token.lower() for token in re.findall(r"\b[A-Z][A-Za-z0-9&.-]{2,}\b", text)}
    return bool(capitalized_names - company_tokens)


def competitor_list_page(text: str) -> bool:
    lower = text.lower()
    list_signals = ["top 10", "top 5", "best alternatives", "alternatives to", "compare", "vs.", "compared to", "similar tools", "similar software", "other options", "also consider"]
    return any(signal in lower for signal in list_signals) and len(re.findall(r"\b[A-Z][A-Za-z0-9]{2,}\b", text)) >= 4


def minimum_relevance_for_claim(claim: DealClaim) -> float:
    # Competition and market queries target the sector, not just the company —
    # allow lower bar so we capture contradictory industry evidence.
    if claim.category in {"competition", "market"}:
        return 0.12
    if claim.category in {"financials", "customer_roi"}:
        return 0.18
    return 0.22


def web_title_for_stance(stance: str) -> str:
    if stance == "supports":
        return "Public web supporting evidence"
    if stance == "contradicts":
        return "Public web contradictory evidence"
    return "Relevant public web evidence"


def normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return ""
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def should_skip_url(url: str) -> bool:
    lower = url.lower()
    return any(
        lower.endswith(suffix)
        for suffix in [".pdf", ".zip", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov"]
    )


def source_name_for_url(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    return host or "Public web"
