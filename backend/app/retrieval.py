from __future__ import annotations

import re
import uuid

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
    if "public" in lower or "annual report" in lower or "10k" in lower or "10-k" in lower or "analyst" in lower:
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
    category_bonus = 0.12 if claim.category.replace("_", " ") in chunk.text.lower() else 0
    independence_bonus = {"third_party": 0.12, "internal": 0.07, "founder_supplied": 0, "derived": 0}[source_independence(chunk.citation)]
    return round(min(1, lexical + number_bonus + category_bonus + independence_bonus), 3)


def find_relevant_chunks(claim: DealClaim, chunks: list[MaterialChunk], limit: int = 4) -> list[MaterialChunk]:
    claim_terms = keywords(claim.text)
    scored = []
    for chunk in chunks:
        chunk_terms = keywords(chunk.text)
        overlap = len(claim_terms & chunk_terms)
        if overlap:
            scored.append((relevance_score(claim, chunk), overlap, chunk))
    return [chunk for _, __, chunk in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)[:limit]]


def evidence_stance_for_chunk(claim: DealClaim, chunk: MaterialChunk) -> str:
    claim_text = claim.text.lower()
    chunk_text_lower = chunk.text.lower()
    same_source = chunk.citation.lower().startswith(claim.sourceMaterial.lower())
    claim_packet_source = "claim_packet" in claim.sourceMaterial.lower() or "claim packet" in claim.sourceMaterial.lower()

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

    claim_numbers = normalized_numbers(claim.text)
    chunk_numbers = normalized_numbers(chunk.text)
    independence = source_independence(chunk.citation)
    if claim_numbers and claim_numbers.issubset(chunk_numbers):
        if not same_source and independence != "founder_supplied":
            return "supports"
        return "partially_supports"

    claim_terms = keywords(claim.text)
    chunk_terms = keywords(chunk.text)
    overlap = len(claim_terms & chunk_terms)
    if overlap >= 5 and not same_source and independence == "third_party":
        return "supports"
    if overlap >= 5 and not same_source and claim.category in {"financials", "pricing", "retention"} and independence == "internal":
        return "supports"
    return "partially_supports"


def evidence_title_for_stance(stance: str) -> str:
    if stance == "supports":
        return "Direct supporting evidence"
    if stance == "contradicts":
        return "Contradictory supplied evidence"
    return "Relevant supplied material"


def fallback_evidence_for_claim(claim: DealClaim, chunks: list[MaterialChunk]) -> list[EvidenceItem]:
    relevant = find_relevant_chunks(claim, chunks, limit=2)
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
            )
        ]
    return [
        EvidenceItem(
            id=f"ev-{uuid.uuid4().hex[:10]}",
            claimId=claim.id,
            title=evidence_title_for_stance(evidence_stance_for_chunk(claim, chunk)),
            sourceType="uploaded",
            citation=chunk.citation,
            snippet=chunk.text[:360],
            stance=evidence_stance_for_chunk(claim, chunk),  # type: ignore[arg-type]
            reliability="high" if evidence_stance_for_chunk(claim, chunk) == "supports" else "medium",
            sourceIndependence=source_independence(chunk.citation),
            relevanceScore=relevance_score(claim, chunk),
            quoteSpan=chunk.citation,
        )
        for chunk in relevant
    ]
