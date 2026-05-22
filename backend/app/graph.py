from __future__ import annotations

import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, TypedDict

from langgraph.graph import END, StateGraph

from . import db
from .config import AGENT_ROLE, APP_NAME
from .llm import DeepSeekClient
from .models import (
    ClaimExtraction,
    DealClaim,
    DealProfile,
    DealProfileGeneration,
    EvidenceItem,
    MaterialChunk,
    MemoGeneration,
    QualityReview,
    RiskMemo,
    SourceMaterial,
)
from .retrieval import chunk_text, fallback_evidence_for_claim
from .scoring import apply_rule_based_status, has_audit_citation, score_claims
from .web_research import collect_public_web_evidence


class DiligenceState(TypedDict, total=False):
    deal_id: str
    company: str
    stage: str
    materials: list[SourceMaterial]
    chunks: list[MaterialChunk]
    profile: DealProfile
    claims: list[DealClaim]
    evidence: list[EvidenceItem]
    quality_review: QualityReview
    memo: RiskMemo
    llm_outputs: dict[str, str]
    on_progress: ProgressCallback
    generated_at: str


ProgressCallback = Callable[[str, str, dict[str, int | str] | None], None]
GraphStep = tuple[str, str, str]

GRAPH_STEPS: list[GraphStep] = [
    ("load_materials", "Read supplied materials", "Loading source packets from the deal workspace"),
    ("chunk_materials", "Split source text", "Creating retrievable evidence chunks"),
    ("profile_deal", "Profile deal context", "Inferring sector, buyer, model, stage, and material mix"),
    ("extract_claims", "Extract diligence claims", "Identifying concrete founder claims to verify"),
    ("retrieve_evidence", "Retrieve evidence", "Searching supplied materials for support and contradictions"),
    ("search_public_web", "Search public web", "Gathering quote-backed third-party sources from the public internet"),
    ("score_claims", "Score claim support", "Applying support and risk scoring rules"),
    ("review_quality", "Review output quality", "Checking confidence, citations, and memo readiness"),
    ("generate_memo", "Draft red-team memo", "Writing the partner-ready diligence memo"),
    ("persist_results", "Save analysis results", "Persisting claims, evidence, memo, and run metadata"),
]


def build_graph():
    graph = StateGraph(DiligenceState)
    graph.add_node("load_materials", load_materials)
    graph.add_node("chunk_materials", chunk_materials)
    graph.add_node("profile_deal", profile_deal)
    graph.add_node("extract_claims", extract_claims)
    graph.add_node("retrieve_evidence", retrieve_evidence)
    graph.add_node("search_public_web", search_public_web)
    graph.add_node("score_claims", score_claim_statuses)
    graph.add_node("review_quality", review_quality)
    graph.add_node("generate_memo", generate_memo)
    graph.add_node("persist_results", persist_results)
    graph.set_entry_point("load_materials")
    graph.add_edge("load_materials", "chunk_materials")
    graph.add_edge("chunk_materials", "profile_deal")
    graph.add_edge("profile_deal", "extract_claims")
    graph.add_edge("extract_claims", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "search_public_web")
    graph.add_edge("search_public_web", "score_claims")
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
            result = run_diligence_with_progress(deal_id, deal.company, deal.stage, on_progress)
        else:
            result = build_graph().invoke({"deal_id": deal_id, "company": deal.company, "stage": deal.stage})
        return result
    except Exception as exc:
        db.update_deal_status(deal_id, "failed", error=str(exc))
        raise


def run_diligence_with_progress(deal_id: str, company: str, stage: str, on_progress: ProgressCallback) -> DiligenceState:
    state: DiligenceState = {"deal_id": deal_id, "company": company, "stage": stage, "on_progress": on_progress}
    graph_updates = iter(build_graph().stream(state, stream_mode="updates"))
    for step_id, label, description in GRAPH_STEPS:
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
        update = next(graph_updates)
        if step_id not in update:
            emitted = ", ".join(update.keys())
            raise RuntimeError(f"LangGraph emitted {emitted or 'no step'} while waiting for {step_id}.")
        next_state = update[step_id]
        if not isinstance(next_state, dict):
            raise RuntimeError(f"LangGraph step {step_id} did not return state.")
        state = next_state
        after = progress_payload(state, label)
        on_progress(
            "tool_complete",
            step_id,
            {
                **after,
                "label": label,
                "toolName": step_id,
                "output": tool_output_summary(state, step_id),
                **tool_raw_output(state, step_id),
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
    if "profile" in state:
        payload["profile"] = state["profile"].sector
    if "generated_at" in state:
        payload["generatedAt"] = state["generated_at"]
    return payload


def tool_input_summary(state: DiligenceState, step_id: str) -> str:
    summaries = {
        "load_materials": f"deal_id={state['deal_id']}",
        "chunk_materials": f"materials={len(state.get('materials', []))}",
        "profile_deal": f"company={state['company']}; stage={state.get('stage', '')}; materials={len(state.get('materials', []))}",
        "extract_claims": f"company={state['company']}; sector={state.get('profile', DealProfile()).sector}; materials={len(state.get('materials', []))}",
        "retrieve_evidence": f"claims={len(state.get('claims', []))}; chunks={len(state.get('chunks', []))}",
        "search_public_web": f"company={state['company']}; claims={len(state.get('claims', []))}; local_evidence={len(state.get('evidence', []))}",
        "score_claims": f"claims={len(state.get('claims', []))}; evidence={len(state.get('evidence', []))}",
        "generate_memo": f"company={state['company']}; claims={len(state.get('claims', []))}",
        "persist_results": f"deal_id={state['deal_id']}; claims={len(state.get('claims', []))}; evidence={len(state.get('evidence', []))}",
    }
    return summaries.get(step_id, "state")


def tool_output_summary(state: DiligenceState, step_id: str) -> str:
    summaries = {
        "load_materials": f"Loaded {len(state.get('materials', []))} materials.",
        "chunk_materials": f"Created {len(state.get('chunks', []))} chunks.",
        "profile_deal": f"Profiled {state.get('profile', DealProfile()).sector} / {state.get('profile', DealProfile()).businessModel}.",
        "extract_claims": f"Extracted {len(state.get('claims', []))} claims.",
        "retrieve_evidence": f"Retrieved {len(state.get('evidence', []))} evidence items.",
        "search_public_web": f"Attached {len([item for item in state.get('evidence', []) if item.sourceType == 'public_web'])} public web evidence items.",
        "score_claims": f"Scored {len(state.get('claims', []))} claims.",
        "review_quality": f"Memo readiness {state.get('quality_review').memoReadinessScore if state.get('quality_review') else 0}%.",
        "generate_memo": "Generated red-team memo.",
        "persist_results": "Saved analysis results.",
    }
    return summaries.get(step_id, "Complete.")


def tool_raw_output(state: DiligenceState, step_id: str) -> dict[str, str]:
    raw_output = state.get("llm_outputs", {}).get(step_id)
    return {"rawOutput": raw_output} if raw_output else {}


def with_llm_output(state: DiligenceState, step_id: str, raw_output: str) -> dict[str, dict[str, str]]:
    outputs = {**state.get("llm_outputs", {}), step_id: raw_output}
    return {"llm_outputs": outputs}


def stream_llm_chunk(state: DiligenceState, step_id: str):
    on_progress = state.get("on_progress")
    if not on_progress:
        return None

    def emit(chunk: str) -> None:
        on_progress(
            "tool_delta",
            step_id,
            {"label": "Streaming DeepSeek response", "toolName": step_id, "rawOutput": chunk},
        )

    return emit


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


def profile_deal(state: DiligenceState) -> DiligenceState:
    llm = DeepSeekClient()
    context = format_material_context(state["materials"], max_chars=9_000)
    if llm.enabled:
        system = (
            "You profile private-market diligence packets. Return JSON only. "
            "Infer sector, businessModel, customer, stage, and materialMix from the supplied materials. "
            "Use concise phrases and do not invent facts that are not implied by the packet."
        )
        user = (
            f"Company: {state['company']}\nStage from deal record: {state.get('stage', '')}\n\n"
            "Return shape: {\"profile\":{\"sector\":\"...\",\"businessModel\":\"...\",\"customer\":\"...\","
            "\"stage\":\"...\",\"materialMix\":[\"deck\",\"financials\",\"customer references\"]}}\n\n"
            f"Materials:\n{context}"
        )
        try:
            generated, raw_output = llm.complete_json_with_raw(system, user, DealProfileGeneration, on_chunk=stream_llm_chunk(state, "profile_deal"))
            return {**state, "profile": normalize_profile(generated.profile, state), **with_llm_output(state, "profile_deal", raw_output)}
        except Exception as exc:
            raise RuntimeError("DeepSeek profile step failed.") from exc
    return {**state, "profile": fallback_deal_profile(state)}


def extract_claims(state: DiligenceState) -> DiligenceState:
    llm = DeepSeekClient()
    context = format_material_context(state["materials"], max_chars=18_000)
    profile = state.get("profile", DealProfile())
    if llm.enabled:
        system = (
            "You extract investor diligence claims from deal materials. Return JSON only. "
            "Extract concrete, verifiable VC/PE diligence claims about market, growth, ROI, competition, pricing, retention, "
            "compliance, financials, product, team, go-to-market, fundraising, legal, and operations. "
            "Every claim must include a sourceMaterial and direct sourceSnippet from the supplied context. "
            "Prefer specific claims with metrics, named customers, dates, cohorts, fundraising terms, product capabilities, legal status, "
            "or explicit assertions that would affect an IC decision. Initial status must be missing and riskRationale can be empty."
        )
        user = (
            f"Company: {state['company']}\nProfile: {profile.model_dump_json()}\n\n"
            "Return shape: {\"claims\":[{\"id\":\"claim-01\",\"text\":\"...\",\"category\":\"market|growth|customer_roi|competition|pricing|retention|compliance|financials|product|team|go_to_market|fundraising|legal|operations\","
            "\"sourceMaterial\":\"...\",\"sourceSnippet\":\"...\",\"importance\":\"high|medium|low\",\"status\":\"missing\",\"riskRationale\":\"\"}]}\n\n"
            f"Materials:\n{context}"
        )
        extracted, raw_output = llm.complete_json_with_raw(system, user, ClaimExtraction, on_chunk=stream_llm_chunk(state, "extract_claims"))
        claims = normalize_claim_ids(extracted.claims)
        state = {**state, **with_llm_output(state, "extract_claims", raw_output)}
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


def search_public_web(state: DiligenceState) -> DiligenceState:
    try:
        web_evidence = collect_public_web_evidence(
            state["company"],
            state.get("profile", DealProfile()),
            state["claims"],
            on_progress=web_progress_emitter(state),
        )
    except Exception:
        emit = web_progress_emitter(state)
        if emit:
            emit("web_error", {"label": "Public web search failed; continuing with supplied materials"})
        web_evidence = []
    if not web_evidence:
        return state

    combined_evidence = replace_not_found_with_real_evidence([*state.get("evidence", []), *web_evidence])
    evidence_by_claim = {claim.id: [item for item in combined_evidence if item.claimId == claim.id] for claim in state["claims"]}
    updated_claims = [apply_rule_based_status(claim, evidence_by_claim.get(claim.id, [])) for claim in state["claims"]]
    return {**state, "claims": updated_claims, "evidence": combined_evidence}


def web_progress_emitter(state: DiligenceState):
    on_progress = state.get("on_progress")
    if not on_progress:
        return None

    def emit(event: str, payload: dict[str, int | str]) -> None:
        label = str(payload.get("label", "Public web research"))
        raw = web_progress_raw_line(event, payload)
        on_progress(
            "tool_delta",
            "search_public_web",
            {
                "label": label,
                "toolName": "search_public_web",
                "webEvent": event,
                "rawOutput": raw,
                **payload,
            },
        )

    return emit


def web_progress_raw_line(event: str, payload: dict[str, int | str]) -> str:
    if event == "web_query":
        return f"Search: {payload.get('query', payload.get('label', ''))}\n"
    if event == "web_results":
        return f"Results: {payload.get('results', 0)} for {payload.get('query', '')}\n"
    if event == "web_fetch":
        return f"Fetch: {payload.get('sourceName') or payload.get('sourceUrl')}\n"
    if event == "web_evidence":
        return f"Evidence: {payload.get('stance')} from {payload.get('sourceName') or payload.get('sourceUrl')} (relevance {payload.get('relevanceScore')})\n"
    return f"{payload.get('label', event)}\n"


def replace_not_found_with_real_evidence(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    claims_with_real_evidence = {
        item.claimId
        for item in evidence
        if item.sourceType != "derived" and item.stance != "not_found"
    }
    return [
        item
        for item in evidence
        if not (item.claimId in claims_with_real_evidence and item.sourceType == "derived" and item.stance == "not_found")
    ]


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
    profile = state.get("profile", DealProfile())
    claim_context = "\n".join(
        f"- [{claim.status}/{claim.importance}/{claim.category}/confidence={claim.confidence}/quality={claim.qualityScore}] "
        f"{claim.text} Rationale: {claim.riskRationale} Verification need: {claim.verificationNeed}"
        for claim in state["claims"]
    )
    evidence_context = "\n".join(evidence_summary_for_claim(claim, state.get("evidence", [])) for claim in state["claims"])
    quality_context = state.get("quality_review", QualityReview()).model_dump_json()
    if llm.enabled:
        system = (
            "You write concise partner-ready VC/PE IC diligence memos. Return JSON only. "
            "Use decision-oriented sections: executive summary, thesis assessment, evidence map, what can be trusted, "
            "material risks, decision drivers, next diligence requests, open questions, and recommendation. "
            "Do not present weak, missing, contradicted, or low-confidence claims as strengths. Do not invent facts. "
            "The overallGrade must match the scoring rules supplied by the caller."
        )
        user = (
            f"Company: {state['company']}\nProfile: {profile.model_dump_json()}\nOverall grade from scoring rules: {grade}\n"
            f"Quality review: {quality_context}\n\nClaims:\n{claim_context}\n\nEvidence summaries:\n{evidence_context}\n\n"
            "Return shape: {\"memo\":{\"company\":\"...\",\"overallGrade\":\"green|yellow|red\",\"investmentQuestion\":\"...\","
            "\"keyStrengths\":[...],\"materialRisks\":[...],\"followUpQuestions\":[...],\"icRecommendation\":\"...\","
            "\"executiveSummary\":\"...\",\"thesisAssessment\":\"...\",\"evidenceMap\":[...],\"keyRisks\":[...],"
            "\"nextDiligenceRequests\":[...],\"decisionDrivers\":[...]}}"
        )
        try:
            generated, raw_output = llm.complete_json_with_raw(system, user, MemoGeneration, on_chunk=stream_llm_chunk(state, "generate_memo"))
            fallback = fallback_memo(state["company"], grade, state["claims"], state.get("evidence", []), profile, state.get("quality_review"))
            memo = fill_missing_memo_sections(generated.memo.model_copy(update={"overallGrade": grade}), fallback)
            return {**state, "memo": memo, **with_llm_output(state, "generate_memo", raw_output)}
        except Exception as exc:
            raise RuntimeError("DeepSeek memo step failed.") from exc
    else:
        memo = fallback_memo(state["company"], grade, state["claims"], state.get("evidence", []), profile, state.get("quality_review"))
    return {**state, "memo": memo}


def fill_missing_memo_sections(memo: RiskMemo, fallback: RiskMemo) -> RiskMemo:
    updates = {}
    for field in [
        "investmentQuestion",
        "icRecommendation",
        "executiveSummary",
        "thesisAssessment",
    ]:
        if not getattr(memo, field).strip():
            updates[field] = getattr(fallback, field)
    for field in [
        "keyStrengths",
        "materialRisks",
        "followUpQuestions",
        "evidenceMap",
        "keyRisks",
        "nextDiligenceRequests",
        "decisionDrivers",
    ]:
        if not getattr(memo, field):
            updates[field] = getattr(fallback, field)
    return memo.model_copy(update=updates) if updates else memo


def persist_results(state: DiligenceState) -> DiligenceState:
    generated_at = datetime.now(timezone.utc).isoformat()
    db.save_analysis(
        state["deal_id"],
        state["claims"],
        state["evidence"],
        state["memo"],
        state.get("quality_review", QualityReview()),
        generated_at,
        state.get("profile"),
    )
    return {**state, "generated_at": generated_at}


def refresh_review_artifacts(deal_id: str) -> None:
    deal = db.get_deal(deal_id)
    if not deal.claims:
        return
    state: DiligenceState = {
        "deal_id": deal_id,
        "company": deal.company,
        "stage": deal.stage,
        "profile": deal.profile or DealProfile(stage=deal.stage),
        "claims": deal.claims,
        "evidence": deal.evidence,
    }
    reviewed = review_quality(state)
    _, grade, _ = score_claims(deal.claims)
    memo = fallback_memo(deal.company, grade, deal.claims, deal.evidence, deal.profile, reviewed["quality_review"])
    db.save_review_artifacts(deal_id, memo, reviewed["quality_review"])


def answer_question(deal_id: str, question: str, chat_history=None):
    from .models import ChatAnswer

    deal = db.get_deal(deal_id)
    if not deal.claims:
        return ChatAnswer(answer="Run analysis before asking diligence questions.", citations=[], confidence="low")
    chat_history = chat_history or []
    recent_questions = " ".join(turn.question for turn in chat_history[-3:])
    question_terms = set(re.findall(r"[a-zA-Z0-9$%]+", question.lower()))
    context_query = f"{recent_questions} {question}" if len(question_terms) <= 4 and recent_questions else question
    current_terms = expand_question_terms(question_terms)
    terms = expand_question_terms(set(re.findall(r"[a-zA-Z0-9$%]+", context_query.lower())))
    relevant = []
    for claim in deal.claims:
        claim_terms = set(re.findall(r"[a-zA-Z0-9$%]+", claim.text.lower()))
        current_overlap = len(current_terms & claim_terms)
        overlap = len(terms & claim_terms)
        if overlap:
            relevant.append((current_overlap, overlap, claim))
    claims = [claim for _, __, claim in sorted(relevant, key=lambda item: (item[0], item[1]), reverse=True)[:4]] or deal.claims[:4]
    evidence = [item for item in deal.evidence if item.claimId in {claim.id for claim in claims}]
    citations = list(dict.fromkeys(item.citation for item in evidence))[:5]
    llm = DeepSeekClient()
    if llm.enabled:
        system = (
            f"You are {APP_NAME}, a {AGENT_ROLE}. Answer only from stored claims and evidence. "
            "Use recent chat turns only to resolve follow-up references, not as evidence. "
            "If evidence is insufficient, say so directly. Return JSON only with answer, citations, confidence."
        )
        history_context = "\n".join(
            f"Q: {turn.question}\nA: {turn.answer}\nCitations: {', '.join(turn.citations)}" for turn in chat_history[-6:]
        )
        user = (
            f"Question: {question}\n\nClaims:\n"
            + "\n".join(claim.model_dump_json() for claim in claims)
            + "\n\nEvidence:\n"
            + "\n".join(item.model_dump_json() for item in evidence)
            + (f"\n\nRecent chat turns:\n{history_context}" if history_context else "")
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
        lines = ["The evidence is not strong enough to fully trust this yet.\n"]
        for claim in weak:
            lines.append(f"• {claim.text} — {claim.status}: {claim.riskRationale}")
        answer = "\n".join(lines)
    else:
        lines = ["The stored evidence supports this directionally.\n"]
        for claim in claims:
            lines.append(f"• {claim.text}: {claim.riskRationale}")
        answer = "\n".join(lines)
    return ChatAnswer(answer=answer, citations=citations, confidence="medium" if weak else "high")


def expand_question_terms(terms: set[str]) -> set[str]:
    expanded = set(terms)
    expansions = {
        "competition": {"competitor", "competitors", "competitive", "landscape", "vendor", "alternative"},
        "competitor": {"competition", "competitors", "competitive", "landscape", "vendor", "alternative"},
        "competitors": {"competition", "competitor", "competitive", "landscape", "vendor", "alternative"},
        "retention": {"nrr", "churn", "renewal", "renewals", "retained"},
        "roi": {"return", "recover", "collections", "savings", "hours", "efficiency"},
        "compliance": {"hipaa", "diagnosis", "billing", "claims", "regulatory"},
        "growth": {"growing", "signed", "active", "onboarding", "arr"},
    }
    for term in terms:
        expanded.update(expansions.get(term, set()))
    return expanded


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


def normalize_profile(profile: DealProfile, state: DiligenceState) -> DealProfile:
    fallback = fallback_deal_profile(state)
    return DealProfile(
        sector=profile.sector.strip() or fallback.sector,
        businessModel=profile.businessModel.strip() or fallback.businessModel,
        customer=profile.customer.strip() or fallback.customer,
        stage=profile.stage.strip() or state.get("stage", fallback.stage),
        materialMix=profile.materialMix or fallback.materialMix,
    )


def fallback_deal_profile(state: DiligenceState) -> DealProfile:
    materials = state.get("materials", [])
    combined = " ".join(material.text.lower() for material in materials)
    material_mix = material_mix_for(materials)
    return DealProfile(
        sector=infer_sector(combined),
        businessModel=infer_business_model(combined),
        customer=infer_customer(combined),
        stage=state.get("stage", ""),
        materialMix=material_mix,
    )


def material_mix_for(materials: list[SourceMaterial]) -> list[str]:
    counts = Counter(material.kind for material in materials)
    source_counts = Counter(material.source_type for material in materials)
    mix = [f"{kind}: {count}" for kind, count in sorted(counts.items())]
    mix.extend(f"{source}: {count}" for source, count in sorted(source_counts.items()))
    return mix


def infer_sector(text: str) -> str:
    rules = [
        ("Healthcare", ["clinic", "patient", "payer", "dental", "medical", "hipaa", "diagnosis"]),
        ("Marketing technology", ["marketing", "creator", "dm", "campaign", "lead", "conversion", "social"]),
        ("Fintech", ["payment", "bank", "fintech", "lending", "underwriting", "card", "wallet"]),
        ("Retail", ["retail", "merchant", "store", "inventory", "merchandise", "ecommerce"]),
        ("Developer tools", ["developer", "api", "sdk", "repository", "workflow automation"]),
        ("Enterprise software", ["enterprise", "workflow", "automation", "saas", "seat", "contract"]),
        ("Consumer", ["consumer", "mobile app", "users", "subscriber"]),
    ]
    for sector, terms in rules:
        if any(term in text for term in terms):
            return sector
    return "General software"


def infer_business_model(text: str) -> str:
    if any(term in text for term in ["arr", "mrr", "subscription", "saas", "annual contract", "acv"]):
        return "B2B SaaS"
    if any(term in text for term in ["take rate", "marketplace", "gmv"]):
        return "Marketplace"
    if any(term in text for term in ["usage-based", "usage based", "per transaction", "transaction fee"]):
        return "Usage-based"
    if any(term in text for term in ["services", "implementation fee", "managed service"]):
        return "Services-enabled software"
    return "Unclear"


def infer_customer(text: str) -> str:
    rules = [
        ("dental clinics", ["dental clinic", "clinics", "practice"]),
        ("creators and brands", ["creator", "influencer", "brand", "dm inbox"]),
        ("enterprise buyers", ["enterprise", "fortune", "procurement", "department"]),
        ("SMBs", ["smb", "small business", "merchant", "local business"]),
        ("retailers", ["retailer", "store", "merchandise"]),
        ("developers", ["developer", "engineer", "api user"]),
        ("consumers", ["consumer", "users", "mobile app"]),
    ]
    for customer, terms in rules:
        if any(term in text for term in terms):
            return customer
    return "Unclear"


def normalize_evidence_ids(claim_id: str, evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    return [
        item.model_copy(update={"id": f"ev-{uuid.uuid4().hex[:10]}", "claimId": claim_id})
        for item in evidence
    ]


def fallback_claims(materials: list[SourceMaterial]) -> list[DealClaim]:
    claims: list[DealClaim] = []
    seen: set[str] = set()
    for material in materials:
        for text in explicit_claims(material.text):
            add_fallback_claim(claims, seen, material, text, explicit=True)

    for material in materials:
        added_for_material = 0
        for text in candidate_sentences(material.text):
            if add_fallback_claim(claims, seen, material, text, explicit=False):
                added_for_material += 1
            if added_for_material >= 5:
                break
    return claims[:18]


def explicit_claims(text: str) -> list[str]:
    claims = []
    for line in text.splitlines():
        match = re.match(r"\s*(?:claim|assertion|founder claim)\s*:\s*(.+)", line, flags=re.IGNORECASE)
        if match:
            claims.append(clean_claim_text(match.group(1)))
    return claims


def candidate_sentences(text: str) -> list[str]:
    candidates: list[str] = []
    for line in text.splitlines():
        clean = re.sub(r"^\s*[-*]\s*", "", line).strip()
        if not clean or re.match(r"\s*(?:claim|assertion|founder claim)\s*:", clean, flags=re.IGNORECASE):
            continue
        parts = re.split(r"(?<=[.!?])\s+", clean)
        for part in parts:
            text_part = clean_claim_text(part)
            if text_part:
                candidates.append(text_part)
    return candidates


def clean_claim_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" -:\t")
    return text[:420]


def normalize_structured_claim_text(text: str) -> str:
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) < 3:
        return text
    label = parts[0].lower()
    values = parts[1:]
    if not any(re.search(r"\d", value) for value in values):
        return text
    if label == "arr":
        return f"ARR grew from {format_money(values[0])} to {format_money(values[-1])} over the reported period."
    if label == "gross margin":
        margin_values = sorted(values, key=numeric_value_for_sort)
        if margin_values[0] == margin_values[-1]:
            return f"Gross margin was {margin_values[-1]} over the reported period."
        return f"Gross margin ranged from {margin_values[0]} to {margin_values[-1]} over the reported period."
    if label == "logo churn":
        return f"Logo churn was reported as {', '.join(values)} over the reported period."
    if label == "average contract value":
        return f"Average contract value was {format_money(values[-1])} in the latest reported period."
    if label in {"revenue", "mrr", "burn", "cash"}:
        return f"{parts[0]} changed from {values[0]} to {values[-1]} over the reported period."
    return text


def format_money(value: str) -> str:
    clean = value.replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", clean):
        return value
    amount = float(clean)
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:g}M"
    if amount >= 1_000:
        return f"${amount / 1_000:g}k"
    return f"${amount:g}"


def numeric_value_for_sort(value: str) -> float:
    clean = value.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(clean)
    except ValueError:
        return 0


def is_low_value_table_header(text: str) -> bool:
    lower = text.lower()
    return bool(re.fullmatch(r"(metric|date|month|quarter|year)(?:[,| ].*)?", lower))


def add_fallback_claim(
    claims: list[DealClaim],
    seen: set[str],
    material: SourceMaterial,
    text: str,
    explicit: bool,
) -> bool:
    text = clean_claim_text(text)
    text = normalize_structured_claim_text(text)
    if len(text) < 20:
        return False
    if is_low_value_table_header(text):
        return False
    signature = claim_signature(text)
    if signature in seen:
        return False
    if not explicit and not is_verifiable_claim(text):
        return False
    seen.add(signature)
    category = infer_claim_category(text)
    claims.append(
        DealClaim(
            id=f"claim-{len(claims)+1:02d}",
            text=text,
            category=category,  # type: ignore[arg-type]
            sourceMaterial=material.name,
            sourceSnippet=text[:280],
            importance=importance_for_category(category, text),  # type: ignore[arg-type]
        )
    )
    return True


def claim_signature(text: str) -> str:
    return " ".join(re.findall(r"[a-zA-Z0-9$%]+", text.lower())[:16])


def is_verifiable_claim(text: str) -> bool:
    lower = text.lower()
    metadata_prefixes = [
        "period of report",
        "source snapshot",
        "source:",
        "snapshot date",
        "page structure",
        "filing date",
    ]
    if any(lower.startswith(prefix) for prefix in metadata_prefixes):
        return False
    if re.fullmatch(r"(?:20\d{2}\s+)?form\s+10-k.*https?://\S+", lower):
        return False
    if lower.count("http://") + lower.count("https://") >= 1 and len(re.findall(r"[a-zA-Z]+", lower)) <= 8:
        return False
    generic_terms = ["world-class", "future of", "delightful", "game-changing", "best-in-class"]
    concrete_terms = [
        "arr",
        "mrr",
        "revenue",
        "gross margin",
        "cash",
        "burn",
        "customer",
        "customers",
        "clinic",
        "signed",
        "contract",
        "pilot",
        "retention",
        "churn",
        "roi",
        "save",
        "hours",
        "market",
        "tam",
        "competitor",
        "competition",
        "price",
        "pricing",
        "valuation",
        "pre-money",
        "post-money",
        "raise",
        "round",
        "automates",
        "integrates",
        "launched",
        "deploy",
        "platform",
        "workflow",
        "founder",
        "previously",
        "led",
        "hired",
        "sales",
        "pipeline",
        "channel",
        "partner",
        "soc 2",
        "hipaa",
        "patent",
        "lawsuit",
        "compliance",
        "regulatory",
        "manufacturing",
        "obligations",
        "inventory",
    ]
    if any(char.isdigit() for char in lower):
        return True
    if any(term in lower for term in generic_terms) and not any(term in lower for term in concrete_terms):
        return False
    return any(term in lower for term in concrete_terms)


def infer_claim_category(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ["competitor", "competition"]):
        return "competition"
    if any(term in lower for term in ["roi", "ltv", "save", "savings", "manual effort", "recover", "improve collections"]):
        return "customer_roi"
    if any(term in lower for term in ["raise", "round", "valuation", "pre-money", "post-money", "safe", "equity", "dilution"]):
        return "fundraising"
    if any(term in lower for term in ["lawsuit", "patent", "ip ", "intellectual property", "contractual", "legal"]):
        return "legal"
    if any(term in lower for term in ["arr", "revenue", "mrr", "gross margin", "cash-flow", "cash flow", "r&d", "expense"]):
        return "financials"
    if any(term in lower for term in ["price", "pricing", "contract", "acv"]):
        return "pricing"
    if any(term in lower for term in ["retention", "churn"]):
        return "retention"
    if any(term in lower for term in ["regulatory", "compliance", "audited", "third-party"]):
        return "compliance"
    if any(term in lower for term in ["grow", "growth", "fastest-growing", "signed", "nrr", "net revenue retention"]):
        return "growth"
    if any(term in lower for term in ["automates", "integrates", "platform", "launched", "deploy", "workflow", "ai agent", "product"]):
        return "product"
    if any(term in lower for term in ["founder", "team", "hired", "previously", "led ", "ex-"]):
        return "team"
    if any(term in lower for term in ["pipeline", "sales", "channel", "partner", "waitlist", "lead", "conversion"]):
        return "go_to_market"
    if any(term in lower for term in ["tam", "market", "vertical", "opportunity"]):
        return "market"
    if any(term in lower for term in ["manufacturing", "inventory", "supply", "operations", "onboarding", "implementation"]):
        return "operations"
    return "growth"


def importance_for_category(category: str, text: str) -> str:
    high_categories = {"growth", "customer_roi", "compliance", "financials", "fundraising", "legal", "market"}
    if category in high_categories:
        return "high"
    if category == "team" and not any(char.isdigit() for char in text):
        return "low"
    return "medium"


def fallback_memo(
    company: str,
    grade: str,
    claims: list[DealClaim],
    evidence: list[EvidenceItem] | None = None,
    profile: DealProfile | None = None,
    quality_review: QualityReview | None = None,
) -> RiskMemo:
    evidence = evidence or []
    profile = profile or DealProfile()
    score, _, counts = score_claims(claims)
    report_claims = [claim for claim in claims if not is_off_target_public_claim(company, claim)] or claims
    report_score, _, report_counts = score_claims(report_claims)
    strength_claims = sorted(
        [claim for claim in report_claims if claim.status == "supported"],
        key=strength_sort_key,
    )
    strengths = [format_strength_claim(claim, evidence) for claim in strength_claims[:3]] or [
        "No claim is ready to treat as fully trusted without additional review."
    ]
    risk_claims = sorted(
        [claim for claim in report_claims if claim.status != "supported" or claim.confidence != "high"],
        key=risk_sort_key,
    )
    risks = [format_risk_claim(claim, evidence) for claim in risk_claims[:5]] or [
        "No material red flags were identified from supplied materials, but external validation remains limited."
    ]
    questions = list(dict.fromkeys(claim.verificationNeed for claim in report_claims if claim.status in {"weak", "missing", "contradicted"}))[:6] or [
        "Which customer references can validate the strongest claims?"
    ]
    evidence_map = [evidence_summary_for_claim(claim, evidence) for claim in report_claims[:8]]
    decision_drivers = decision_drivers_for_claims(report_claims, quality_review)
    thesis = thesis_assessment_for_report(grade, report_counts, strength_claims, risk_claims)
    summary = executive_summary_for_report(company, profile, grade, score, report_score, report_counts, risk_claims)
    recommendation = recommendation_for_report(grade, report_counts, risk_claims)
    return RiskMemo(
        company=company,
        overallGrade=grade,  # type: ignore[arg-type]
        investmentQuestion=investment_question_for_report(company, profile, risk_claims),
        keyStrengths=strengths,
        materialRisks=risks,
        followUpQuestions=questions,
        icRecommendation=recommendation,
        executiveSummary=summary,
        thesisAssessment=thesis,
        evidenceMap=evidence_map,
        keyRisks=risks,
        nextDiligenceRequests=questions,
        decisionDrivers=decision_drivers,
    )


def primary_citation_for_claim(claim: DealClaim, evidence: list[EvidenceItem]) -> str:
    for item in evidence:
        if item.claimId == claim.id and item.stance == "supports":
            return f"Primary citation: {item.citation}."
    return "Primary citation: not attached."


def primary_evidence_for_claim(claim: DealClaim, evidence: list[EvidenceItem]) -> EvidenceItem | None:
    claim_evidence = [item for item in evidence if item.claimId == claim.id]
    for stance in ["supports", "contradicts", "partially_supports", "not_found"]:
        for item in claim_evidence:
            if item.stance == stance and (has_audit_citation(item) or stance in {"partially_supports", "not_found"}):
                return item
    return claim_evidence[0] if claim_evidence else None


def format_strength_claim(claim: DealClaim, evidence: list[EvidenceItem]) -> str:
    primary = primary_evidence_for_claim(claim, evidence)
    citation = f"Primary citation: {primary.citation}." if primary and primary.stance == "supports" else primary_citation_for_claim(claim, evidence)
    qualifier = ""
    if primary and primary.sourceIndependence != "third_party":
        qualifier = f" The source is {primary.sourceIndependence.replace('_', ' ')}, so this should stay tied to the packet rather than treated as market proof."
    quote = f" Quote: \"{primary.quoteSpan}\"" if primary and primary.quoteSpan else ""
    if claim.confidence == "high":
        return f"{claim.text} The cited evidence supports the claim with high reviewer confidence.{qualifier} {citation}{quote}"
    return f"{claim.text} Directionally supported, but confidence is {claim.confidence}; keep diligence follow-up attached.{qualifier} {citation}{quote}"


def format_risk_claim(claim: DealClaim, evidence: list[EvidenceItem]) -> str:
    primary = primary_evidence_for_claim(claim, evidence)
    citation = f" Citation: {primary.citation}." if primary else ""
    quote = f" Quote: \"{primary.quoteSpan}\"" if primary and primary.quoteSpan else ""
    if claim.status == "contradicted":
        lead = "This is the cleanest red flag in the packet"
    elif claim.status == "missing":
        lead = "This remains an assertion rather than diligence evidence"
    elif claim.status == "weak":
        lead = "This is plausible but not yet underwritten"
    else:
        lead = "This should not be over-weighted"
    return (
        f"{claim.text} {lead}: status is {claim.status} with {claim.confidence} confidence. "
        f"{claim.riskRationale}{citation}{quote}"
    )


def strength_sort_key(claim: DealClaim) -> tuple[int, int, int]:
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    impact_rank = {"high": 0, "medium": 1, "low": 2}
    return (
        confidence_rank.get(claim.confidence, 3),
        impact_rank.get(claim.decisionImpact, 3),
        -claim.qualityScore,
    )


def risk_sort_key(claim: DealClaim) -> tuple[int, int, int, int]:
    status_rank = {"contradicted": 0, "missing": 1, "weak": 2, "supported": 3}
    impact_rank = {"high": 0, "medium": 1, "low": 2}
    category_rank = {
        "customer_roi": 0,
        "market": 1,
        "competition": 2,
        "compliance": 3,
        "legal": 4,
        "growth": 5,
        "fundraising": 6,
        "financials": 7,
    }
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    return (
        status_rank.get(claim.status, 4),
        impact_rank.get(claim.decisionImpact, 3),
        category_rank.get(claim.category, 8),
        confidence_rank.get(claim.confidence, 3),
    )


def executive_summary_for_report(
    company: str,
    profile: DealProfile,
    grade: str,
    score: int,
    report_score: int,
    report_counts: dict[str, int],
    risk_claims: list[DealClaim],
) -> str:
    risk_clause = "No material unresolved target-company claim leads the memo."
    if risk_claims:
        lead = risk_claims[0]
        risk_clause = f"The main diligence issue is that {lead.text} is {lead.status}."
    posture = {
        "green": "The packet is close to IC-ready on the evidence supplied, but it still deserves normal confirmatory checks.",
        "yellow": "The packet has enough substance to continue diligence, but not enough to let the founder narrative carry the recommendation.",
        "red": "The packet is not ready for IC because the unsupported or contradicted claims sit too close to the investment case.",
    }.get(grade, "The packet needs further diligence before IC.")
    return (
        f"{company} screens as a {profile.sector} company with a {profile.businessModel} model serving {profile.customer}. "
        f"{posture} The full ledger scores {score}/100 and the target-company memo focus scores {report_score}/100, "
        f"with {report_counts['supported']} supported, {report_counts['weak']} weak, "
        f"{report_counts['missing']} missing, and {report_counts['contradicted']} contradicted claims. {risk_clause}"
    )


def is_off_target_public_claim(company: str, claim: DealClaim) -> bool:
    company_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", company.lower()) if len(token) > 2}
    text = claim.text.lower()
    known_public_issuers = {"apple", "target", "microsoft", "amazon", "google", "alphabet", "meta", "tesla", "nvidia"}
    mentioned_public_issuers = {issuer for issuer in known_public_issuers if re.search(rf"\b{re.escape(issuer)}\b", text)}
    if not mentioned_public_issuers:
        return False
    return not bool(company_tokens & set(re.findall(r"[a-zA-Z0-9]+", text)))


def evidence_summary_for_claim(claim: DealClaim, evidence: list[EvidenceItem]) -> str:
    claim_evidence = [item for item in evidence if item.claimId == claim.id]
    if not claim_evidence:
        return f"{claim.id} ({claim.status}): {claim.text} - no evidence item attached."
    independence = Counter(item.sourceIndependence for item in claim_evidence)
    stances = Counter(item.stance for item in claim_evidence)
    citations = list(dict.fromkeys(item.citation for item in claim_evidence))[:3]
    primary = primary_evidence_for_claim(claim, evidence)
    primary_source = primary.sourceName or primary.citation if primary else "not attached"
    primary_quote = f" Primary quote: \"{primary.quoteSpan}\"." if primary and primary.quoteSpan else ""
    independence_summary = ", ".join(f"{key}: {value}" for key, value in sorted(independence.items()))
    stance_summary = ", ".join(f"{key}: {value}" for key, value in sorted(stances.items()))
    return (
        f"{claim.id} ({claim.status}): {claim.text} - primary source: {primary_source}; "
        f"sources [{independence_summary}], stances [{stance_summary}], citations: {', '.join(citations)}.{primary_quote}"
    )


def decision_drivers_for_claims(claims: list[DealClaim], quality_review: QualityReview | None = None) -> list[str]:
    drivers: list[str] = []
    contradicted = [claim for claim in claims if claim.status == "contradicted" and claim.decisionImpact == "high"]
    weak_high = [claim for claim in claims if claim.status in {"weak", "missing"} and claim.importance == "high"]
    if contradicted:
        drivers.append(f"Resolve the contradicted high-impact claim before IC: {contradicted[0].text}")
    if weak_high:
        drivers.append(f"Replace weak or missing high-importance support with source-level backup, starting with: {weak_high[0].text}")
    if quality_review and quality_review.globalWarnings:
        drivers.extend(quality_review.globalWarnings[:2])
    if not drivers:
        drivers.append("Confirm no newer supplied evidence changes the current support status.")
    return list(dict.fromkeys(drivers))[:5]


def thesis_assessment_for_report(
    grade: str,
    counts: dict[str, int] | None = None,
    strength_claims: list[DealClaim] | None = None,
    risk_claims: list[DealClaim] | None = None,
) -> str:
    counts = counts or {"supported": 0, "weak": 0, "missing": 0, "contradicted": 0}
    strength_claims = strength_claims or []
    risk_claims = risk_claims or []
    best_support = f"The best-supported point is {strength_claims[0].text}" if strength_claims else "There is not yet a fully reliable proof point"
    lead_risk = f"the gating issue is {risk_claims[0].text}" if risk_claims else "the remaining issue is normal confirmatory diligence"
    if counts.get("contradicted", 0):
        return (
            f"The thesis should not be taken to IC as stated. {best_support}, but {lead_risk}; "
            "that contradiction has to be reconciled before the memo can argue from the company's narrative."
        )
    if grade == "green":
        return f"The supplied packet is directionally IC-ready. {best_support}, and no contradicted claim currently leads the decision."
    if grade == "yellow":
        return (
            f"The thesis is investable only as a diligence workstream, not as a conclusion. {best_support}, but {lead_risk}; "
            "IC should require customer, financial, or third-party proof before relying on the narrative."
        )
    return "The current packet is not IC-ready because material claims are contradicted, missing, or insufficiently supported."


def investment_question_for_report(company: str, profile: DealProfile, risk_claims: list[DealClaim]) -> str:
    if risk_claims:
        return f"Can {company}'s {profile.businessModel} case survive diligence if the team cannot substantiate: {risk_claims[0].text}"
    return f"Do the supplied materials support {company}'s core traction, market, and risk claims strongly enough for IC?"


def recommendation_for_report(grade: str, counts: dict[str, int], risk_claims: list[DealClaim]) -> str:
    if counts.get("contradicted", 0):
        return (
            f"Current grade: {grade}. Do not take the company narrative to IC unchanged; require source-level reconciliation "
            "for the contradicted claims and rewrite the investment case around only supported evidence."
        )
    if grade == "green":
        return "Current grade: green. Continue toward IC, with confirmatory diligence focused on freshness of citations and any customer-level checks still missing."
    if grade == "yellow":
        lead = f" The first gating item is: {risk_claims[0].text}" if risk_claims else ""
        return f"Current grade: yellow. Keep the deal active, but condition IC readiness on converting weak or missing claims into cited support.{lead}"
    return "Current grade: red. Pause IC work until the company supplies evidence that directly resolves the missing or weak high-impact claims."
