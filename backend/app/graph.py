from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Callable, TypedDict

from langgraph.graph import END, StateGraph

from . import db
from .config import AGENT_ROLE, APP_NAME
from .llm import DeepSeekClient
from .models import (
    ClaimExtraction,
    DealClaim,
    EvidenceItem,
    MaterialChunk,
    MemoGeneration,
    QualityReview,
    RiskMemo,
    SourceMaterial,
)
from .retrieval import chunk_text, fallback_evidence_for_claim, find_relevant_chunks
from .scoring import apply_rule_based_status, score_claims


class DiligenceState(TypedDict, total=False):
    deal_id: str
    company: str
    materials: list[SourceMaterial]
    chunks: list[MaterialChunk]
    claims: list[DealClaim]
    evidence: list[EvidenceItem]
    quality_review: QualityReview
    memo: RiskMemo
    generated_at: str


ProgressCallback = Callable[[str, str, dict[str, int | str] | None], None]

def build_graph():
    graph = StateGraph(DiligenceState)
    graph.add_node("load_materials", load_materials)
    graph.add_node("chunk_materials", chunk_materials)
    graph.add_node("extract_claims", extract_claims)
    graph.add_node("retrieve_evidence", retrieve_evidence)
    graph.add_node("score_claims", score_claim_statuses)
    graph.add_node("review_quality", review_quality)
    graph.add_node("generate_memo", generate_memo)
    graph.add_node("persist_results", persist_results)
    graph.set_entry_point("load_materials")
    graph.add_edge("load_materials", "chunk_materials")
    graph.add_edge("chunk_materials", "extract_claims")
    graph.add_edge("extract_claims", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "score_claims")
    graph.add_edge("score_claims", "review_quality")
    graph.add_edge("review_quality", "generate_memo")
    graph.add_edge("generate_memo", "persist_results")
    graph.add_edge("persist_results", END)
    return graph.compile()


def run_diligence(deal_id: str, on_progress: ProgressCallback | None = None) -> DiligenceState:
    db.update_deal_status(deal_id, "running")
    try:
        deal = db.get_deal(deal_id)
        if on_progress:
            result = run_diligence_with_progress(deal_id, deal.company, on_progress)
        else:
            result = build_graph().invoke({"deal_id": deal_id, "company": deal.company})
        return result
    except Exception as exc:
        db.update_deal_status(deal_id, "failed", error=str(exc))
        raise


def run_diligence_with_progress(deal_id: str, company: str, on_progress: ProgressCallback) -> DiligenceState:
    state: DiligenceState = {"deal_id": deal_id, "company": company}
    steps = [
        ("load_materials", "Read supplied materials", "Loading source packets from the deal workspace", load_materials),
        ("chunk_materials", "Split source text", "Creating retrievable evidence chunks", chunk_materials),
        ("extract_claims", "Extract diligence claims", "Identifying concrete founder claims to verify", extract_claims),
        ("retrieve_evidence", "Retrieve evidence", "Searching supplied materials for support and contradictions", retrieve_evidence),
        ("score_claims", "Score claim support", "Applying support and risk scoring rules", score_claim_statuses),
        ("review_quality", "Review output quality", "Checking confidence, citations, and memo readiness", review_quality),
        ("generate_memo", "Draft red-team memo", "Writing the partner-ready diligence memo", generate_memo),
        ("persist_results", "Save analysis results", "Persisting claims, evidence, memo, and run metadata", persist_results),
    ]
    for step_id, label, description, step in steps:
        before = progress_payload(state, label)
        on_progress("step_start", step_id, {**before, "label": description})
        on_progress(
            "tool_start",
            step_id,
            {
                **before,
                "label": label,
                "toolName": step_id,
                "input": tool_input_summary(state, step_id),
            },
        )
        state = step(state)
        after = progress_payload(state, label)
        on_progress(
            "tool_complete",
            step_id,
            {
                **after,
                "label": label,
                "toolName": step_id,
                "output": tool_output_summary(state, step_id),
            },
        )
        on_progress("step_complete", step_id, {**after, "label": description})
    return state


def progress_payload(state: DiligenceState, label: str) -> dict[str, int | str]:
    payload: dict[str, int | str] = {"label": label}
    if "materials" in state:
        payload["materials"] = len(state["materials"])
    if "chunks" in state:
        payload["chunks"] = len(state["chunks"])
    if "claims" in state:
        payload["claims"] = len(state["claims"])
    if "evidence" in state:
        payload["evidence"] = len(state["evidence"])
    if "generated_at" in state:
        payload["generatedAt"] = state["generated_at"]
    return payload


def tool_input_summary(state: DiligenceState, step_id: str) -> str:
    summaries = {
        "load_materials": f"deal_id={state['deal_id']}",
        "chunk_materials": f"materials={len(state.get('materials', []))}",
        "extract_claims": f"company={state['company']}; materials={len(state.get('materials', []))}",
        "retrieve_evidence": f"claims={len(state.get('claims', []))}; chunks={len(state.get('chunks', []))}",
        "score_claims": f"claims={len(state.get('claims', []))}; evidence={len(state.get('evidence', []))}",
        "generate_memo": f"company={state['company']}; claims={len(state.get('claims', []))}",
        "persist_results": f"deal_id={state['deal_id']}; claims={len(state.get('claims', []))}; evidence={len(state.get('evidence', []))}",
    }
    return summaries.get(step_id, "state")


def tool_output_summary(state: DiligenceState, step_id: str) -> str:
    summaries = {
        "load_materials": f"Loaded {len(state.get('materials', []))} materials.",
        "chunk_materials": f"Created {len(state.get('chunks', []))} chunks.",
        "extract_claims": f"Extracted {len(state.get('claims', []))} claims.",
        "retrieve_evidence": f"Retrieved {len(state.get('evidence', []))} evidence items.",
        "score_claims": f"Scored {len(state.get('claims', []))} claims.",
        "review_quality": f"Memo readiness {state.get('quality_review').memoReadinessScore if state.get('quality_review') else 0}%.",
        "generate_memo": "Generated red-team memo.",
        "persist_results": "Saved analysis results.",
    }
    return summaries.get(step_id, "Complete.")


def load_materials(state: DiligenceState) -> DiligenceState:
    materials = db.get_materials(state["deal_id"])
    if not materials:
        raise ValueError("Add at least one uploaded file or URL before analysis.")
    return {**state, "materials": materials}


def chunk_materials(state: DiligenceState) -> DiligenceState:
    chunks: list[MaterialChunk] = []
    for material in state["materials"]:
        chunks.extend(chunk_text(material))
    if not chunks:
        raise ValueError("No readable text could be extracted from the supplied materials.")
    return {**state, "chunks": chunks}


def extract_claims(state: DiligenceState) -> DiligenceState:
    llm = DeepSeekClient()
    context = format_material_context(state["materials"], max_chars=14_000)
    if llm.enabled:
        system = (
            "You extract investor diligence claims from deal materials. Return JSON only. "
            "Extract concrete, verifiable claims about market, growth, ROI, competition, pricing, retention, compliance, and financials. "
            "Every claim must include a sourceMaterial and direct sourceSnippet from the supplied context. "
            "Initial status must be missing and riskRationale can be empty."
        )
        user = (
            f"Company: {state['company']}\n\n"
            "Return shape: {\"claims\":[{\"id\":\"claim-01\",\"text\":\"...\",\"category\":\"market|growth|customer_roi|competition|pricing|retention|compliance|financials\","
            "\"sourceMaterial\":\"...\",\"sourceSnippet\":\"...\",\"importance\":\"high|medium|low\",\"status\":\"missing\",\"riskRationale\":\"\"}]}\n\n"
            f"Materials:\n{context}"
        )
        extracted = llm.complete_json(system, user, ClaimExtraction)
        claims = normalize_claim_ids(extracted.claims)
    else:
        claims = fallback_claims(state["materials"])
    if not claims:
        raise ValueError("No diligence claims were extracted from the supplied materials.")
    return {**state, "claims": claims[:18]}


def retrieve_evidence(state: DiligenceState) -> DiligenceState:
    all_evidence: list[EvidenceItem] = []
    updated_claims: list[DealClaim] = []
    for claim in state["claims"]:
        evidence = fallback_evidence_for_claim(claim, state["chunks"])
        updated = apply_rule_based_status(claim, evidence)
        all_evidence.extend(evidence)
        updated_claims.append(updated)
    return {**state, "claims": updated_claims, "evidence": all_evidence}


def score_claim_statuses(state: DiligenceState) -> DiligenceState:
    evidence_by_claim = {claim.id: [item for item in state["evidence"] if item.claimId == claim.id] for claim in state["claims"]}
    claims = [apply_rule_based_status(claim, evidence_by_claim.get(claim.id, [])) for claim in state["claims"]]
    return {**state, "claims": claims}


def review_quality(state: DiligenceState) -> DiligenceState:
    claims = state["claims"]
    evidence = state["evidence"]
    duplicated = duplicated_claims(claims)
    low_value = [claim.id for claim in claims if claim.qualityScore < 35 or "Claim is too terse to verify precisely." in claim.qualityIssues]
    warnings: list[str] = []
    if any(claim.status == "contradicted" for claim in claims):
        warnings.append("At least one important claim is contradicted by supplied evidence.")
    if any(claim.status == "supported" and claim.confidence != "high" for claim in claims):
        warnings.append("Some supported claims have less than high reviewer confidence.")
    if not any(item.sourceIndependence == "third_party" for item in evidence):
        warnings.append("No third-party validation was attached to the analysis.")
    if any(claim.status in {"missing", "weak"} and claim.importance == "high" for claim in claims):
        warnings.append("High-importance claims remain weak or missing.")
    overconfidence = [
        f"{claim.id}: {claim.text}"
        for claim in claims
        if claim.status == "supported" and ("No third-party validation is attached." in claim.qualityIssues or claim.confidence != "high")
    ]
    follow_up = [claim.verificationNeed for claim in claims if claim.status != "supported"]
    unique_follow_up = list(dict.fromkeys(follow_up))[:6]
    avg_quality = round(sum(claim.qualityScore for claim in claims) / len(claims)) if claims else 0
    penalty = min(30, len(warnings) * 5 + len(duplicated) * 3)
    review = QualityReview(
        memoReadinessScore=max(0, min(100, avg_quality - penalty)),
        globalWarnings=warnings,
        duplicatedClaims=duplicated,
        lowValueClaims=low_value,
        recommendedFollowUpEvidence=unique_follow_up,
        overconfidenceWarnings=overconfidence,
    )
    return {**state, "quality_review": review}


def duplicated_claims(claims: list[DealClaim]) -> list[str]:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for claim in claims:
        signature = " ".join(sorted(re.findall(r"[a-zA-Z0-9]+", claim.text.lower()))[:8])
        if signature in seen:
            duplicates.append(f"{seen[signature]} / {claim.id}")
        else:
            seen[signature] = claim.id
    return duplicates


def generate_memo(state: DiligenceState) -> DiligenceState:
    llm = DeepSeekClient()
    _, grade, _ = score_claims(state["claims"])
    claim_context = "\n".join(
        f"- [{claim.status}/{claim.importance}/{claim.category}/confidence={claim.confidence}/quality={claim.qualityScore}] "
        f"{claim.text} Rationale: {claim.riskRationale} Verification need: {claim.verificationNeed}"
        for claim in state["claims"]
    )
    quality_context = state.get("quality_review", QualityReview()).model_dump_json()
    if llm.enabled:
        system = (
            "You write concise partner-ready VC red-team memos. Return JSON only. "
            "Use decision-oriented sections: what can be trusted, what remains unproven, what would change the decision, and a recommendation. "
            "Do not present weak, missing, contradicted, or low-confidence claims as strengths. Do not invent facts."
        )
        user = (
            f"Company: {state['company']}\nOverall grade from scoring rules: {grade}\nQuality review: {quality_context}\n\nClaims:\n{claim_context}\n\n"
            "Return shape: {\"memo\":{\"company\":\"...\",\"overallGrade\":\"green|yellow|red\",\"investmentQuestion\":\"...\","
            "\"keyStrengths\":[...],\"materialRisks\":[...],\"followUpQuestions\":[...],\"icRecommendation\":\"...\"}}"
        )
        try:
            memo = llm.complete_json(system, user, MemoGeneration).memo
            memo = memo.model_copy(update={"overallGrade": grade})
        except Exception:
            memo = fallback_memo(state["company"], grade, state["claims"])
    else:
        memo = fallback_memo(state["company"], grade, state["claims"])
    return {**state, "memo": memo}


def persist_results(state: DiligenceState) -> DiligenceState:
    generated_at = datetime.now(timezone.utc).isoformat()
    db.save_analysis(state["deal_id"], state["claims"], state["evidence"], state["memo"], state.get("quality_review", QualityReview()), generated_at)
    return {**state, "generated_at": generated_at}


def refresh_review_artifacts(deal_id: str) -> None:
    deal = db.get_deal(deal_id)
    if not deal.claims:
        return
    state: DiligenceState = {
        "deal_id": deal_id,
        "company": deal.company,
        "claims": deal.claims,
        "evidence": deal.evidence,
    }
    reviewed = review_quality(state)
    _, grade, _ = score_claims(deal.claims)
    memo = fallback_memo(deal.company, grade, deal.claims)
    db.save_review_artifacts(deal_id, memo, reviewed["quality_review"])


def answer_question(deal_id: str, question: str):
    from .models import ChatAnswer

    deal = db.get_deal(deal_id)
    if not deal.claims:
        return ChatAnswer(answer="Run analysis before asking diligence questions.", citations=[], confidence="low")
    terms = set(re.findall(r"[a-zA-Z0-9$%]+", question.lower()))
    relevant = []
    for claim in deal.claims:
        claim_terms = set(re.findall(r"[a-zA-Z0-9$%]+", claim.text.lower()))
        overlap = len(terms & claim_terms)
        if overlap:
            relevant.append((overlap, claim))
    claims = [claim for _, claim in sorted(relevant, key=lambda item: item[0], reverse=True)[:4]] or deal.claims[:4]
    evidence = [item for item in deal.evidence if item.claimId in {claim.id for claim in claims}]
    citations = list(dict.fromkeys(item.citation for item in evidence))[:5]
    llm = DeepSeekClient()
    if llm.enabled:
        system = (
            f"You are {APP_NAME}, a {AGENT_ROLE}. Answer only from stored claims and evidence. "
            "If evidence is insufficient, say so directly. Return JSON only with answer, citations, confidence."
        )
        user = (
            f"Question: {question}\n\nClaims:\n"
            + "\n".join(claim.model_dump_json() for claim in claims)
            + "\n\nEvidence:\n"
            + "\n".join(item.model_dump_json() for item in evidence)
        )
        try:
            answer = llm.complete_json(system, user, ChatAnswer)
            known_citations = [item.citation for item in evidence]
            if not answer.citations or any(citation not in known_citations for citation in answer.citations):
                answer = answer.model_copy(update={"citations": list(dict.fromkeys(known_citations))[:5]})
            return answer
        except Exception:
            pass
    weak = [claim for claim in claims if claim.status != "supported"]
    if weak:
        answer = "The evidence is not strong enough to fully trust this yet. " + " ".join(
            f"{claim.text} is {claim.status}: {claim.riskRationale}" for claim in weak
        )
    else:
        answer = "The stored evidence supports this directionally. " + " ".join(
            f"{claim.text}: {claim.riskRationale}" for claim in claims
        )
    return ChatAnswer(answer=answer, citations=citations, confidence="medium" if weak else "high")


def format_material_context(materials: list[SourceMaterial], max_chars: int) -> str:
    sections = []
    remaining = max_chars
    for material in materials:
        text = material.text[: max(0, remaining)]
        sections.append(f"### {material.name}\nKind: {material.kind}\n{text}")
        remaining -= len(text)
        if remaining <= 0:
            break
    return "\n\n".join(sections)


def normalize_claim_ids(claims: list[DealClaim]) -> list[DealClaim]:
    return [claim.model_copy(update={"id": f"claim-{index:02d}"}) for index, claim in enumerate(claims, start=1)]


def normalize_evidence_ids(claim_id: str, evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    return [
        item.model_copy(update={"id": f"ev-{uuid.uuid4().hex[:10]}", "claimId": claim_id})
        for item in evidence
    ]


def fallback_claims(materials: list[SourceMaterial]) -> list[DealClaim]:
    claims: list[DealClaim] = []
    seen: set[str] = set()
    for material in materials:
        for line in material.text.splitlines():
            match = re.match(r"\s*Claim:\s*(.+)", line, flags=re.IGNORECASE)
            if not match:
                continue
            text = re.sub(r"\s+", " ", match.group(1)).strip()
            if len(text) < 20 or text.lower() in seen:
                continue
            seen.add(text.lower())
            category = infer_claim_category(text)
            claims.append(
                DealClaim(
                    id=f"claim-{len(claims)+1:02d}",
                    text=text,
                    category=category,  # type: ignore[arg-type]
                    sourceMaterial=material.name,
                    sourceSnippet=text[:280],
                    importance="high" if category in {"growth", "market", "customer_roi", "compliance", "financials"} else "medium",
                )
            )

    patterns = [
        ("growth", r"([^.!?]*(?:grow|growth|ARR|revenue|signed|customers|clinics)[^.!?]*[.!?])"),
        ("customer_roi", r"([^.!?]*(?:save|recover|ROI|hours|collections|improve)[^.!?]*[.!?])"),
        ("competition", r"([^.!?]*(?:competitor|competition|only|no direct)[^.!?]*[.!?])"),
        ("market", r"([^.!?]*(?:market|TAM|opportunity|\$[0-9]+[BMK])[^\n.!?]*[.!?])"),
        ("compliance", r"([^.!?]*(?:compliance|human review|diagnosis|submission|regulatory)[^.!?]*[.!?])"),
        ("pricing", r"([^.!?]*(?:price|pricing|contract|ACV|ARR)[^.!?]*[.!?])"),
    ]
    for material in materials:
        for category, pattern in patterns:
            for match in re.findall(pattern, material.text, flags=re.IGNORECASE)[:2]:
                text = re.sub(r"\s+", " ", match).strip()
                if len(text) < 20 or text.lower() in seen:
                    continue
                seen.add(text.lower())
                claims.append(
                    DealClaim(
                        id=f"claim-{len(claims)+1:02d}",
                        text=text,
                        category=category,  # type: ignore[arg-type]
                        sourceMaterial=material.name,
                        sourceSnippet=text[:280],
                        importance="high" if category in {"growth", "market", "customer_roi", "compliance"} else "medium",
                    )
                )
    return claims[:18]


def infer_claim_category(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ["competitor", "competition"]):
        return "competition"
    if any(term in lower for term in ["roi", "ltv", "save", "savings", "manual effort"]):
        return "customer_roi"
    if any(term in lower for term in ["arr", "revenue", "mrr", "gross margin", "cash-flow", "cash flow", "r&d", "expense"]):
        return "financials"
    if any(term in lower for term in ["valuation", "pre-money", "post-money", "equity", "pricing"]):
        return "pricing"
    if any(term in lower for term in ["tam", "market", "vertical"]):
        return "market"
    if any(term in lower for term in ["retention", "churn"]):
        return "retention"
    if any(term in lower for term in ["regulatory", "compliance", "audited", "third-party"]):
        return "compliance"
    return "growth"


def fallback_memo(company: str, grade: str, claims: list[DealClaim]) -> RiskMemo:
    strengths = [
        f"{claim.text} (confidence: {claim.confidence}, quality: {claim.qualityScore}/100)"
        for claim in claims
        if claim.status == "supported" and claim.confidence == "high"
    ][:3] or ["No claim is ready to treat as fully trusted without additional review."]
    risks = [
        f"{claim.text} ({claim.status}, confidence: {claim.confidence}). {claim.riskRationale}"
        for claim in claims
        if claim.status != "supported" or claim.confidence != "high"
    ][:4] or [
        "No material red flags were identified from supplied materials, but external validation remains limited."
    ]
    questions = list(dict.fromkeys(claim.verificationNeed for claim in claims if claim.status in {"weak", "missing", "contradicted"}))[:4] or [
        "Which customer references can validate the strongest claims?"
    ]
    return RiskMemo(
        company=company,
        overallGrade=grade,  # type: ignore[arg-type]
        investmentQuestion=f"Do the supplied materials support {company}'s core traction, market, and risk claims strongly enough for IC?",
        keyStrengths=strengths,
        materialRisks=risks,
        followUpQuestions=questions,
        icRecommendation=(
            f"Current grade: {grade}. Proceed only after the team resolves weak, contradicted, and missing-evidence claims with cited support."
        ),
    )
