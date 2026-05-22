from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from .models import DealClaim, EvidenceItem, MaterialChunk, SourceIndependence, SourceMaterial
from .config import LOCAL_RETRIEVAL_CITATION


def chunk_text(material: SourceMaterial, max_chars: int = 950) -> list[MaterialChunk]:
    text = re.sub(r"\s+", " ", material.text).strip()
    if not text:
        return []
    chunks: list[MaterialChunk] = []
    start = 0
    index = 1
    while start < len(text):
        window = text[start : start + max_chars]
        if start + max_chars < len(text):
            cut = max(window.rfind(". "), window.rfind("\n"), window.rfind(" "))
            if cut > 350:
                window = window[: cut + 1]
        chunks.append(
            MaterialChunk(
                id=f"chunk-{uuid.uuid4().hex[:10]}",
                deal_id=material.deal_id,
                material_id=material.id,
                citation=f"{material.name}, chunk {index}",
                text=window.strip(),
                sourceName=material.name,
                sourceUrl=material.url,
                sourceType=material.source_type,
                chunkIndex=index,
            )
        )
        start += max(len(window), max_chars)
        index += 1
    return chunks


def keywords(text: str) -> set[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "are",
        "our",
        "has",
        "have",
        "will",
        "can",
        "claim",
        "claims",
    }
    return {word for word in re.findall(r"[a-zA-Z0-9$%]+", text.lower()) if len(word) > 3 and word not in stop}


def normalized_numbers(text: str) -> set[str]:
    numbers = set()
    for value in re.findall(r"\$?\d[\d,]*(?:\.\d+)?%?", text):
        clean = value.replace("$", "").replace(",", "").replace("%", "")
        if clean:
            numbers.add(clean)
    return numbers


def source_independence(citation: str) -> SourceIndependence:
    lower = citation.lower()
    if "claim_packet" in lower or "claim packet" in lower or "deck" in lower or "pitch" in lower or "founder" in lower:
        return "founder_supplied"
    if (
        "public" in lower
        or "annual report" in lower
        or "10k" in lower
        or "10-k" in lower
        or "analyst" in lower
        or "sec" in lower
        or "crunchbase" in lower
        or "linkedin" in lower
        or "gartner" in lower
    ):
        return "third_party"
    if "customer" in lower or "reference" in lower or "financial" in lower or "model" in lower or "data_room" in lower:
        return "internal"
    if citation == LOCAL_RETRIEVAL_CITATION:
        return "derived"
    return "internal"


def relevance_score(claim: DealClaim, chunk: MaterialChunk) -> float:
    claim_terms = keywords(claim.text)
    chunk_terms = keywords(chunk.text)
    if not claim_terms:
        return 0
    lexical = len(claim_terms & chunk_terms) / len(claim_terms)
    number_bonus = 0.3 if normalized_numbers(claim.text) and normalized_numbers(claim.text).issubset(normalized_numbers(chunk.text)) else 0
    category_bonus = 0.12 if category_matches_chunk(claim, chunk.text) else 0
    independence_bonus = {"third_party": 0.12, "internal": 0.07, "founder_supplied": 0, "derived": 0}[source_independence(chunk.citation)]
    freshness_bonus = 0.06 if source_freshness_score(chunk.text) else 0
    contradiction_bonus = 0.14 if contradiction_cue_matches(claim.text, chunk.text) else 0
    return round(min(1, lexical + number_bonus + category_bonus + independence_bonus + freshness_bonus + contradiction_bonus), 3)


def category_matches_chunk(claim: DealClaim, text: str) -> bool:
    lower = text.lower()
    category_terms = {
        "market": ["market", "tam", "sam", "vertical"],
        "growth": ["growth", "grew", "signed", "customer", "traction"],
        "customer_roi": ["roi", "save", "savings", "hours", "efficiency"],
        "competition": ["competitor", "competition", "vendor", "alternative"],
        "pricing": ["price", "pricing", "acv", "contract"],
        "retention": ["retention", "churn", "nrr", "renewal"],
        "compliance": ["compliance", "regulatory", "audit", "hipaa", "soc 2"],
        "financials": ["arr", "mrr", "revenue", "gross margin", "cash", "expense"],
        "product": ["product", "platform", "automates", "integrates", "workflow"],
        "team": ["founder", "team", "hired", "previously", "led"],
        "go_to_market": ["pipeline", "sales", "channel", "partner", "lead"],
        "fundraising": ["raise", "round", "valuation", "pre-money", "post-money"],
        "legal": ["legal", "lawsuit", "patent", "ip", "contractual"],
        "operations": ["operations", "manufacturing", "inventory", "supply", "implementation"],
    }
    return any(term in lower for term in category_terms.get(claim.category, []))


def source_freshness_score(text: str) -> int:
    return len(re.findall(r"\b20(?:2[3-9]|3[0-9])\b|Q[1-4]\s+20\d{2}|FY\s*20\d{2}", text, flags=re.IGNORECASE))


def contradiction_cue_matches(claim_text: str, chunk_text: str) -> bool:
    lower_claim = claim_text.lower()
    lower_chunk = chunk_text.lower()
    negated_claim = any(phrase in lower_claim for phrase in ["no ", "none", "without", "not "])
    contradiction_terms = [
        "not",
        "does not",
        "did not",
        "lacks",
        "missing",
        "instead",
        "however",
        "but",
        "contradict",
        "competitors include",
        "not independently verified",
    ]
    return negated_claim or any(term in lower_chunk for term in contradiction_terms)


def find_relevant_chunks(claim: DealClaim, chunks: list[MaterialChunk], limit: int = 4) -> list[MaterialChunk]:
    claim_terms = keywords(claim.text)
    scored = []
    for chunk in chunks:
        chunk_terms = keywords(chunk.text)
        overlap = len(claim_terms & chunk_terms)
        number_match = bool(normalized_numbers(claim.text) & normalized_numbers(chunk.text))
        contradiction_match = contradiction_cue_matches(claim.text, chunk.text) and bool(claim_terms & chunk_terms)
        if overlap or number_match or contradiction_match:
            scored.append((relevance_score(claim, chunk), overlap, chunk))
    return [chunk for _, __, chunk in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)[:limit]]


def evidence_stance_for_chunk(claim: DealClaim, chunk: MaterialChunk) -> str:
    claim_text = claim.text.lower()
    chunk_text_lower = chunk.text.lower()
    same_source = chunk.citation.lower().startswith(claim.sourceMaterial.lower())
    denies_competition = any(
        phrase in claim_text
        for phrase in [
            "no direct competitor",
            "no direct competitors",
            "no direct or adjacent competitors",
            "no adjacent competitors",
            "no competitors",
            "no direct competition",
        ]
    )
    names_competitors = any(
        phrase in chunk_text_lower
        for phrase in [
            "direct competitors",
            "adjacent competitors",
            "competitors include",
            "as direct competitors",
            "adjacent ai",
            "adjacent automation",
            "list ",
            "lists ",
        ]
    )
    if denies_competition and names_competitors and not same_source:
        return "contradicts"

    if "no manufacturing purchase obligations" in claim_text and "manufacturing purchase obligations" in chunk_text_lower and not same_source:
        return "contradicts"

    if "no third-party validation risk" in claim_text and any(
        phrase in chunk_text_lower for phrase in ["does not provide", "lacks third-party validation", "not include"]
    ):
        return "contradicts"

    if "proven by bottom-up" in claim_text and any(
        phrase in chunk_text_lower for phrase in ["does not include a bottom-up", "not supported by bottom-up", "not supported by bottom"]
    ):
        return "contradicts"

    if "independently verified" in claim_text and any(
        phrase in chunk_text_lower for phrase in ["not independently verified", "details are available under nda", "not independently"]
    ):
        return "contradicts"

    if any(phrase in claim_text for phrase in ["no legal risk", "no compliance risk", "no regulatory risk"]) and any(
        phrase in chunk_text_lower for phrase in ["lawsuit", "regulatory risk", "requires compliance", "not compliant", "pending review"]
    ):
        return "contradicts"

    if any(phrase in claim_text for phrase in ["fully automated", "no human review", "no manual review"]) and any(
        phrase in chunk_text_lower for phrase in ["human review", "manual review", "human-in-the-loop", "human in the loop"]
    ):
        return "contradicts"

    claim_numbers = normalized_numbers(claim.text)
    chunk_numbers = normalized_numbers(chunk.text)
    independence = source_independence(chunk.citation)
    if claim_numbers and claim_numbers.issubset(chunk_numbers):
        if independence == "third_party":
            return "supports"
        if not same_source and independence != "founder_supplied":
            return "supports"
        return "partially_supports"

    claim_terms = keywords(claim.text)
    chunk_terms = keywords(chunk.text)
    overlap = len(claim_terms & chunk_terms)
    if overlap >= 5 and not same_source and independence == "third_party":
        return "supports"
    if (
        overlap >= 5
        and not same_source
        and claim.category in {"financials", "pricing", "retention", "operations", "legal", "compliance", "fundraising"}
        and independence == "internal"
    ):
        return "supports"
    return "partially_supports"


def evidence_title_for_stance(stance: str) -> str:
    if stance == "supports":
        return "Direct supporting evidence"
    if stance == "contradicts":
        return "Contradictory supplied evidence"
    return "Relevant supplied material"


def quote_span_for_claim(claim: DealClaim, chunk: MaterialChunk) -> str:
    candidates = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", chunk.text) if part.strip()]
    if not candidates:
        return chunk.text[:420].strip()
    claim_terms = keywords(claim.text)
    claim_numbers = normalized_numbers(claim.text)

    def candidate_score(candidate: str) -> tuple[int, int, int]:
        candidate_terms = keywords(candidate)
        number_matches = len(claim_numbers & normalized_numbers(candidate))
        return (number_matches, len(claim_terms & candidate_terms), len(candidate))

    quote = max(candidates, key=candidate_score)
    if len(quote) < 80 and len(chunk.text) <= 420:
        return chunk.text.strip()
    return quote[:420].strip()


def source_type_for_chunk(chunk: MaterialChunk) -> str:
    return "supplied_url" if chunk.sourceType == "url" else "uploaded"


def fallback_evidence_for_claim(claim: DealClaim, chunks: list[MaterialChunk]) -> list[EvidenceItem]:
    relevant = find_relevant_chunks(claim, chunks, limit=3)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    if not relevant:
        return [
            EvidenceItem(
                id=f"ev-{uuid.uuid4().hex[:10]}",
                claimId=claim.id,
                title="No matching supplied evidence found",
                sourceType="derived",
                citation=LOCAL_RETRIEVAL_CITATION,
                snippet="No uploaded material or supplied URL chunk matched this claim closely enough to support it.",
                stance="not_found",
                reliability="medium",
                sourceIndependence="derived",
                relevanceScore=0,
                retrievedAt=retrieved_at,
            )
        ]
    evidence: list[EvidenceItem] = []
    for chunk in relevant:
        stance = evidence_stance_for_chunk(claim, chunk)
        evidence.append(
            EvidenceItem(
                id=f"ev-{uuid.uuid4().hex[:10]}",
                claimId=claim.id,
                title=evidence_title_for_stance(stance),
                sourceType=source_type_for_chunk(chunk),  # type: ignore[arg-type]
                citation=chunk.citation,
                snippet=chunk.text[:420],
                stance=stance,  # type: ignore[arg-type]
                reliability="high" if stance == "supports" else "medium",
                sourceIndependence=source_independence(chunk.citation),
                relevanceScore=relevance_score(claim, chunk),
                quoteSpan=quote_span_for_claim(claim, chunk),
                sourceMaterialId=chunk.material_id,
                sourceName=chunk.sourceName or chunk.citation.split(", chunk")[0],
                sourceUrl=chunk.sourceUrl,
                chunkIndex=chunk.chunkIndex,
                retrievedAt=retrieved_at,
            )
        )
    return evidence


def source_type_for_citation(citation: str) -> str:
    return "supplied_url" if citation.startswith(("http://", "https://")) else "uploaded"
