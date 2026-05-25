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


def get_llm_client() -> DeepSeekClient:
    return DeepSeekClient()
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
            {"label": "Streaming LLM response", "toolName": step_id, "rawOutput": chunk},
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
    llm = get_llm_client()
    if not llm.enabled:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured. Add it to backend/.env.")
    context = format_material_context(state["materials"], max_chars=9_000)
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
        raise RuntimeError("LLM profile step failed.") from exc


def extract_claims(state: DiligenceState) -> DiligenceState:
    llm = get_llm_client()
    if not llm.enabled:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured. Add it to backend/.env.")
    context = format_material_context(state["materials"], max_chars=18_000)
    profile = state.get("profile", DealProfile())
    system = (
        "You extract investor diligence claims from deal materials. Return JSON only. "
        "Extract concrete, verifiable VC/PE diligence claims about market, growth, ROI, competition, pricing, retention, "
        "compliance, financials, product, team, go-to-market, fundraising, legal, and operations. "
        "Every claim must include a sourceMaterial and direct sourceSnippet from the supplied context. "
        "Prefer specific claims with metrics, named customers, dates, cohorts, fundraising terms, product capabilities, legal status, "
        "or explicit assertions that would affect an IC decision. Initial status must be missing and riskRationale can be empty. "
        "IMPORTANT: The claim text field must be a standalone assertion written in plain English. "
        "Do NOT include source navigation labels such as 'Slide 7:', 'Slide 4:', '### ', 'Claim:', or 'Source:' in the text field. "
        "Strip any such prefix before writing the claim text."
    )
    user = (
        f"Company: {state['company']}\nProfile: {profile.model_dump_json()}\n\n"
        "Return shape: {\"claims\":[{\"id\":\"claim-01\",\"text\":\"...\",\"category\":\"market|growth|customer_roi|competition|pricing|retention|compliance|financials|product|team|go_to_market|fundraising|legal|operations\","
        "\"sourceMaterial\":\"...\",\"sourceSnippet\":\"...\",\"importance\":\"high|medium|low\",\"status\":\"missing\",\"riskRationale\":\"\"}]}\n\n"
        f"Materials:\n{context}"
    )
    extracted, raw_output = llm.complete_json_with_raw(system, user, ClaimExtraction, on_chunk=stream_llm_chunk(state, "extract_claims"))
    claims = clean_claim_text(normalize_claim_ids(extracted.claims))
    state = {**state, **with_llm_output(state, "extract_claims", raw_output)}
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
    llm = get_llm_client()
    if not llm.enabled:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured. Add it to backend/.env.")
    score_summary = score_claims(state["claims"], state.get("evidence", []), state.get("quality_review"))
    grade = score_summary.grade
    profile = state.get("profile", DealProfile())
    claim_context = "\n".join(
        f"- [{claim.status}/{claim.importance}/{claim.category}/confidence={claim.confidence}/quality={claim.qualityScore}] "
        f"{claim.text} Rationale: {claim.riskRationale} Verification need: {claim.verificationNeed}"
        for claim in state["claims"]
    )
    seen_quotes: set[str] = set()
    evidence_context = "\n".join(
        evidence_summary_for_claim(claim, state.get("evidence", []), seen_quotes)
        for claim in state["claims"]
    )
    quality_context = state.get("quality_review", QualityReview()).model_dump_json()

    # Build specific unresolved-claims block for Fix 6
    unresolved = [
        c for c in state["claims"]
        if c.status in {"contradicted", "missing", "weak"} and c.importance == "high"
    ]
    unresolved_block = "\n".join(
        f"- [{c.status.upper()}] {c.text} → {c.verificationNeed}"
        for c in unresolved[:6]
    )

    # Fix 5: human-readable IC readiness label (no internal jargon)
    ic_readiness_label = "strong" if score_summary.overall >= 85 else "moderate" if score_summary.overall >= 60 else "weak"

    system = (
        "You write concise partner-ready VC/PE IC diligence memos. Return JSON only. "
        "Use decision-oriented sections: executive summary, thesis assessment, evidence map, what can be trusted, "
        "material risks, decision drivers, next diligence requests, open questions, and recommendation. "
        "Do not present weak, missing, contradicted, or low-confidence claims as strengths. Do not invent facts. "
        "The overallGrade must match the scoring rules supplied by the caller. "
        "Do not include internal scoring labels such as 'full ledger', 'target-company memo focus', or raw score "
        "fractions in the executive summary or any narrative section — write as a partner memo, not a system report. "
        "The nextDiligenceRequests list must contain one specific follow-up request per high-priority unresolved claim "
        "listed below, referencing the actual claim text. Do not use generic placeholder requests."
    )
    user = (
        f"Company: {state['company']}\nProfile: {profile.model_dump_json()}\nOverall grade from scoring rules: {grade}\n"
        f"IC readiness: {ic_readiness_label} ({score_summary.overall}/100). "
        f"Key issues: {'; '.join(score_summary.drivers[:2])}\n"
        f"Quality review: {quality_context}\n\n"
        + (f"High-priority unresolved claims (use these verbatim in nextDiligenceRequests):\n{unresolved_block}\n\n" if unresolved_block else "")
        + f"Claims:\n{claim_context}\n\nEvidence summaries:\n{evidence_context}\n\n"
        "Return shape: {\"memo\":{\"company\":\"...\",\"overallGrade\":\"green|yellow|red\",\"investmentQuestion\":\"...\","
        "\"keyStrengths\":[...],\"materialRisks\":[...],\"followUpQuestions\":[...],\"icRecommendation\":\"...\","
        "\"executiveSummary\":\"...\",\"thesisAssessment\":\"...\",\"evidenceMap\":[...],\"keyRisks\":[...],"
        "\"nextDiligenceRequests\":[...],\"decisionDrivers\":[...]}}"
    )
    generated, raw_output = llm.complete_json_with_raw(system, user, MemoGeneration, on_chunk=stream_llm_chunk(state, "generate_memo"))
    memo = generated.memo.model_copy(update={"overallGrade": grade})

    # Fix 4: append reconciliation note when grade is green/yellow but contradictions exist
    unresolved_contradictions = [
        c for c in state["claims"]
        if c.status == "contradicted" and c.reviewerStatus != "verified"
    ]
    if unresolved_contradictions and grade in {"green", "yellow"}:
        contradiction_texts = "; ".join(c.text[:120] for c in unresolved_contradictions[:2])
        qualifier = (
            f" NOTE: {len(unresolved_contradictions)} contradicted claim(s) remain unresolved "
            f"({contradiction_texts}) — do not present this grade as IC-ready until reconciled."
        )
        memo = memo.model_copy(
            update={"icRecommendation": memo.icRecommendation.rstrip(".") + qualifier}
        )

    return {**state, "memo": memo, **with_llm_output(state, "generate_memo", raw_output)}


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
    score_summary = score_claims(deal.claims, deal.evidence, reviewed["quality_review"])
    grade = score_summary.grade
    reviewed["on_progress"] = None
    memo_state = generate_memo({**reviewed, "deal_id": deal_id, "company": deal.company, "stage": deal.stage})
    db.save_review_artifacts(deal_id, memo_state["memo"], reviewed["quality_review"])


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
    llm = get_llm_client()
    if not llm.enabled:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured. Add it to backend/.env.")
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
    answer = llm.complete_json(system, user, ChatAnswer)
    known_citations = [item.citation for item in evidence]
    if not answer.citations or any(citation not in known_citations for citation in answer.citations):
        answer = answer.model_copy(update={"citations": list(dict.fromkeys(known_citations))[:5]})
    return answer


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


_ARTIFACT_PREFIX = re.compile(
    r"^(?:"
    r"Slide\s*\d+\s*(?:[:–\-—]\s*)?"      # Slide 7: / Slide 7 -
    r"|Page\s*\d+\s*[:–\-—]\s*"            # Page 3:
    r"|Section\s*\d*\s*[:–\-—]\s*"         # Section 2:
    r"|##?\s*"                              # ## or ###
    r"|Source\s*:\s*"                       # Source:
    r"|Note\s*:\s*"                         # Note:
    r"|Claim\s*:\s*"                        # Claim:
    r"|Key\s+Claim\s*:\s*"                  # Key Claim:
    r"|Finding\s*:\s*"                      # Finding:
    r"|Assertion\s*:\s*"                    # Assertion:
    r"|Evidence\s*:\s*"                     # Evidence:
    r")",
    re.IGNORECASE,
)

_TRAILING_SOURCE = re.compile(r"\s*[\(\[]\s*(?:source|from|see|ref|slide|page)\s*[:\d][^\)\]]*[\)\]]\.?$", re.IGNORECASE)


def clean_claim_text(claims: list[DealClaim]) -> list[DealClaim]:
    cleaned = []
    for claim in claims:
        text = claim.text
        # Strip leading artifact prefixes (possibly repeated, e.g. "Slide 4: Slide 4: ...")
        for _ in range(3):
            if _ARTIFACT_PREFIX.match(text):
                text = _ARTIFACT_PREFIX.sub("", text).strip()
            else:
                break
        # Strip trailing source annotations like "(Source: deck slide 4)"
        text = _TRAILING_SOURCE.sub("", text).strip()
        if text != claim.text:
            cleaned.append(claim.model_copy(update={"text": text}))
        else:
            cleaned.append(claim)
    return cleaned


def normalize_profile(profile: DealProfile, state: DiligenceState) -> DealProfile:
    return DealProfile(
        sector=profile.sector.strip() or "Unknown",
        businessModel=profile.businessModel.strip() or "Unknown",
        customer=profile.customer.strip() or "Unknown",
        stage=profile.stage.strip() or state.get("stage", ""),
        materialMix=profile.materialMix or [],
    )



def primary_evidence_for_claim(claim: DealClaim, evidence: list[EvidenceItem]) -> EvidenceItem | None:
    claim_evidence = [item for item in evidence if item.claimId == claim.id]
    for stance in ["supports", "contradicts", "partially_supports", "not_found"]:
        for item in claim_evidence:
            if item.stance == stance and (has_audit_citation(item) or stance in {"partially_supports", "not_found"}):
                return item
    return claim_evidence[0] if claim_evidence else None



def evidence_summary_for_claim(
    claim: DealClaim, evidence: list[EvidenceItem], seen_quotes: set[str] | None = None
) -> str:
    claim_evidence = [item for item in evidence if item.claimId == claim.id]
    if not claim_evidence:
        return f"{claim.id} ({claim.status}): {claim.text} - no evidence item attached."
    independence = Counter(item.sourceIndependence for item in claim_evidence)
    stances = Counter(item.stance for item in claim_evidence)
    citations = list(dict.fromkeys(item.citation for item in claim_evidence))[:3]
    primary = primary_evidence_for_claim(claim, evidence)
    primary_source = primary.sourceName or primary.citation if primary else "not attached"
    primary_quote_text = primary.quoteSpan if primary and primary.quoteSpan else ""
    # Suppress quote if this same text was already shown for another claim
    if seen_quotes is not None and primary_quote_text:
        key = primary_quote_text[:80]
        if key in seen_quotes:
            primary_quote_text = ""
        else:
            seen_quotes.add(key)
    primary_quote = f" Primary quote: \"{primary_quote_text}\"." if primary_quote_text else ""
    independence_summary = ", ".join(f"{key}: {value}" for key, value in sorted(independence.items()))
    stance_summary = ", ".join(f"{key}: {value}" for key, value in sorted(stances.items()))
    return (
        f"{claim.id} ({claim.status}): {claim.text} - primary source: {primary_source}; "
        f"sources [{independence_summary}], stances [{stance_summary}], citations: {', '.join(citations)}.{primary_quote}"
    )


