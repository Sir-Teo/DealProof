from __future__ import annotations

import re
import uuid

from .models import DealClaim, EvidenceItem, MaterialChunk, SourceMaterial
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
    stop = {"the", "and", "for", "with", "that", "this", "from", "into", "are", "our", "has", "have", "will", "can"}
    return {word for word in re.findall(r"[a-zA-Z0-9$%]+", text.lower()) if len(word) > 3 and word not in stop}


def find_relevant_chunks(claim: DealClaim, chunks: list[MaterialChunk], limit: int = 4) -> list[MaterialChunk]:
    claim_terms = keywords(claim.text)
    scored = []
    for chunk in chunks:
        chunk_terms = keywords(chunk.text)
        overlap = len(claim_terms & chunk_terms)
        if overlap:
            scored.append((overlap, chunk))
    return [chunk for _, chunk in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]


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
            )
        ]
    return [
        EvidenceItem(
            id=f"ev-{uuid.uuid4().hex[:10]}",
            claimId=claim.id,
            title="Relevant supplied material",
            sourceType="uploaded",
            citation=chunk.citation,
            snippet=chunk.text[:360],
            stance="partially_supports",
            reliability="medium",
        )
        for chunk in relevant
    ]
