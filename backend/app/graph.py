from __future__ import annotations

import re
import uuid
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, TypedDict

from langgraph.graph import END, StateGraph

from . import db
from .config import AGENT_ROLE, APP_NAME
from .llm import DeepSeekClient
from .models import (
    AppSettings,
    ClaimExtraction,
    DealClaim,
    DealProfile,
    DealProfileGeneration,
    DiligenceReport,
    EvidenceItem,
    EvidenceReviews,
    MaterialChunk,
    MemoGeneration,
    QualityReview,
    ReportClaimRef,
    ReportGeneration,
    RiskMemo,
    SourceQualityNote,
    SourceMaterial,
)
from .retrieval import chunk_text, fallback_evidence_for_claim, source_authority_for_independence, source_independence
from .scoring import active_claims, apply_rule_based_status, derive_readiness_status, effective_disposition, has_audit_citation, score_claims
from .settings import get_app_settings
from .web_research import collect_public_web_evidence


class DiligenceState(TypedDict, total=False):
    deal_id: str
    company: str
    stage: str
    materials: list[SourceMaterial]
    chunks: list[MaterialChunk]
    profile: DealProfile
    source_quality: list[SourceQualityNote]
    claims: list[DealClaim]
    evidence: list[EvidenceItem]
    quality_review: QualityReview
    report: DiligenceReport
    memo: RiskMemo
    llm_outputs: dict[str, str]
    on_progress: ProgressCallback
    generated_at: str
    settings: AppSettings


ProgressCallback = Callable[[str, str, dict[str, int | str] | None], None]


def get_llm_client(state: DiligenceState | None = None) -> DeepSeekClient:
    settings = state.get("settings") if state else None
    model = (settings or get_app_settings()).deepseekModel
    try:
        return DeepSeekClient(model=model)
    except TypeError:
        client = DeepSeekClient()
        if hasattr(client, "model"):
            client.model = model
        return client
GraphStep = tuple[str, str, str]


def deterministic_analysis_enabled() -> bool:
    return os.getenv("DEALPROOF_DETERMINISTIC_ANALYSIS", "0").strip().lower() in {"1", "true", "yes"}


def run_settings(state: DiligenceState) -> AppSettings:
    return state.get("settings") or get_app_settings()


def max_claims(state: DiligenceState) -> int:
    return max(1, run_settings(state).maxClaims)


def max_claims_per_material(state: DiligenceState) -> int:
    return max(1, run_settings(state).maxClaimsPerMaterial)

GRAPH_STEPS: list[GraphStep] = [
    ("load_materials", "Read supplied materials", "Loading source packets from the deal workspace"),
    ("chunk_materials", "Split source text", "Creating retrievable evidence chunks"),
    ("profile_deal", "Profile deal context", "Inferring sector, buyer, model, stage, and material mix"),
    ("inventory_sources", "Inventory sources", "Classifying source authority and limitations"),
    ("extract_claims", "Extract candidate claims", "Extracting source-grounded candidate claims by material"),
    ("normalize_claims", "Normalize claims", "Splitting, de-duplicating, and decontextualizing claim text"),
    ("rank_claims", "Rank materiality", "Prioritizing claims by IC materiality and verification standard"),
    ("retrieve_evidence", "Retrieve evidence", "Searching supplied materials for support and contradictions"),
    ("assess_evidence", "Assess evidence", "Reviewing retrieved evidence stances and source authority"),
    ("search_public_web", "Search public web", "Gathering quote-backed third-party sources from the public internet"),
    ("score_claims", "Score claim support", "Applying support and risk scoring rules"),
    ("review_quality", "Review output quality", "Checking confidence, citations, and memo readiness"),
    ("generate_report", "Draft IC report", "Writing the structured IC diligence report"),
    ("generate_memo", "Draft red-team memo", "Writing the partner-ready diligence memo"),
    ("qa_report", "QA report", "Checking report claim references, coverage, and risk placement"),
    ("persist_results", "Save analysis results", "Persisting claims, evidence, memo, and run metadata"),
]


def build_graph():
    graph = StateGraph(DiligenceState)
    graph.add_node("load_materials", load_materials)
    graph.add_node("chunk_materials", chunk_materials)
    graph.add_node("profile_deal", profile_deal)
    graph.add_node("inventory_sources", inventory_sources)
    graph.add_node("extract_claims", extract_claims)
    graph.add_node("normalize_claims", normalize_claims)
    graph.add_node("rank_claims", rank_claims)
    graph.add_node("retrieve_evidence", retrieve_evidence)
    graph.add_node("assess_evidence", assess_evidence)
    graph.add_node("search_public_web", search_public_web)
    graph.add_node("score_claims", score_claim_statuses)
    graph.add_node("review_quality", review_quality)
    graph.add_node("generate_report", generate_report)
    graph.add_node("generate_memo", generate_memo)
    graph.add_node("qa_report", qa_report)
    graph.add_node("persist_results", persist_results)
    graph.set_entry_point("load_materials")
    graph.add_edge("load_materials", "chunk_materials")
    graph.add_edge("chunk_materials", "profile_deal")
    graph.add_edge("profile_deal", "inventory_sources")
    graph.add_edge("inventory_sources", "extract_claims")
    graph.add_edge("extract_claims", "normalize_claims")
    graph.add_edge("normalize_claims", "rank_claims")
    graph.add_edge("rank_claims", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "assess_evidence")
    graph.add_edge("assess_evidence", "search_public_web")
    graph.add_edge("search_public_web", "score_claims")
    graph.add_edge("score_claims", "review_quality")
    graph.add_edge("review_quality", "generate_report")
    graph.add_edge("generate_report", "generate_memo")
    graph.add_edge("generate_memo", "qa_report")
    graph.add_edge("qa_report", "persist_results")
    graph.add_edge("persist_results", END)
    return graph.compile()


def run_diligence(
    deal_id: str,
    on_progress: ProgressCallback | None = None,
    settings: AppSettings | None = None,
) -> DiligenceState:
    db.update_deal_status(deal_id, "running")
    try:
        deal = db.get_deal(deal_id)
        active_settings = settings or get_app_settings()
        if on_progress:
            result = run_diligence_with_progress(deal_id, deal.company, deal.stage, on_progress, active_settings)
        else:
            result = build_graph().invoke({"deal_id": deal_id, "company": deal.company, "stage": deal.stage, "settings": active_settings})
        return result
    except Exception as exc:
        db.update_deal_status(deal_id, "failed", error=str(exc))
        raise


def run_diligence_with_progress(
    deal_id: str,
    company: str,
    stage: str,
    on_progress: ProgressCallback,
    settings: AppSettings,
) -> DiligenceState:
    state: DiligenceState = {"deal_id": deal_id, "company": company, "stage": stage, "on_progress": on_progress, "settings": settings}
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
        "inventory_sources": f"materials={len(state.get('materials', []))}",
        "extract_claims": f"company={state['company']}; sector={state.get('profile', DealProfile()).sector}; materials={len(state.get('materials', []))}",
        "normalize_claims": f"claims={len(state.get('claims', []))}",
        "rank_claims": f"claims={len(state.get('claims', []))}",
        "retrieve_evidence": f"claims={len(state.get('claims', []))}; chunks={len(state.get('chunks', []))}",
        "assess_evidence": f"claims={len(state.get('claims', []))}; evidence={len(state.get('evidence', []))}",
        "search_public_web": f"company={state['company']}; claims={len(state.get('claims', []))}; local_evidence={len(state.get('evidence', []))}",
        "score_claims": f"claims={len(state.get('claims', []))}; evidence={len(state.get('evidence', []))}",
        "review_quality": f"claims={len(state.get('claims', []))}; evidence={len(state.get('evidence', []))}",
        "generate_report": f"company={state['company']}; claims={len(state.get('claims', []))}",
        "generate_memo": f"company={state['company']}; claims={len(state.get('claims', []))}",
        "qa_report": f"claims={len(state.get('claims', []))}; report={'yes' if state.get('report') else 'no'}",
        "persist_results": f"deal_id={state['deal_id']}; claims={len(state.get('claims', []))}; evidence={len(state.get('evidence', []))}",
    }
    return summaries.get(step_id, "state")


def tool_output_summary(state: DiligenceState, step_id: str) -> str:
    summaries = {
        "load_materials": f"Loaded {len(state.get('materials', []))} materials.",
        "chunk_materials": f"Created {len(state.get('chunks', []))} chunks.",
        "profile_deal": f"Profiled {state.get('profile', DealProfile()).sector} / {state.get('profile', DealProfile()).businessModel}.",
        "inventory_sources": f"Classified {len(state.get('source_quality', []))} source materials.",
        "extract_claims": f"Extracted {len(state.get('claims', []))} claims.",
        "normalize_claims": f"Normalized {len(state.get('claims', []))} target-company claims.",
        "rank_claims": f"Ranked {len(state.get('claims', []))} claims by materiality.",
        "retrieve_evidence": f"Retrieved {len(state.get('evidence', []))} evidence items.",
        "assess_evidence": f"Assessed {len(state.get('evidence', []))} evidence items.",
        "search_public_web": f"Attached {len([item for item in state.get('evidence', []) if item.sourceType == 'public_web'])} public web evidence items.",
        "score_claims": f"Scored {len(state.get('claims', []))} claims.",
        "review_quality": f"Memo readiness {state.get('quality_review').memoReadinessScore if state.get('quality_review') else 0}%.",
        "generate_report": "Generated structured IC report.",
        "generate_memo": "Generated red-team memo.",
        "qa_report": "Checked report coverage and claim references.",
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
    if deterministic_analysis_enabled():
        profile = deterministic_profile(state)
        return {**state, "profile": profile, **with_llm_output(state, "profile_deal", profile.model_dump_json())}
    llm = get_llm_client(state)
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
        profile = deterministic_profile(state)
        fallback_note = (
            f"Profile generation failed ({exc.__class__.__name__}: {str(exc)[:500]}). "
            "Continuing with an inferred profile from supplied materials.\n\n"
            f"{profile.model_dump_json()}"
        )
        emit = stream_llm_chunk(state, "profile_deal")
        if emit:
            emit(f"\n\n[fallback]\n{fallback_note}")
        return {**state, "profile": profile, **with_llm_output(state, "profile_deal", fallback_note)}


def deterministic_profile(state: DiligenceState) -> DealProfile:
    materials_text = " ".join(material.text[:2000].lower() for material in state.get("materials", []))
    sector = "Legal AI" if "law" in materials_text or "legal" in materials_text else "Healthcare" if "clinic" in materials_text or "hipaa" in materials_text else "AI software" if "ai" in materials_text else "Unknown"
    customer = "Law firms and in-house legal teams" if sector == "Legal AI" else "Dental clinics" if "clinic" in materials_text else "Enterprise customers" if "enterprise" in materials_text else "Unknown"
    business_model = "Enterprise SaaS" if any(term in materials_text for term in ["arr", "subscription", "contract", "seat"]) else "Unknown"
    return DealProfile(
        sector=sector,
        businessModel=business_model,
        customer=customer,
        stage=state.get("stage", "") or "Active diligence",
        materialMix=list(dict.fromkeys(material.kind for material in state.get("materials", []))),
    )


def inventory_sources(state: DiligenceState) -> DiligenceState:
    notes = [source_quality_note(material) for material in state["materials"]]
    return {**state, "source_quality": notes}


def source_quality_note(material: SourceMaterial) -> SourceQualityNote:
    independence = source_independence(material.name)
    authority = source_authority_for_independence(independence, material.name)
    limitations: list[str] = []
    lower = material.text[:1200].lower()
    if material.source_type in {"seed", "file"} and authority == "founder":
        limitations.append("Founder-supplied narrative; useful for claim discovery but not independent validation.")
    if "image-only" in lower or "could not be read" in lower:
        limitations.append("Some content may be missing because the source was not fully machine-readable.")
    if material.kind == "url":
        limitations.append("Fetched web text may omit charts, tables, scripts, or gated content.")
    if not limitations:
        limitations.append("Readable source with no parsing limitation detected.")
    reliability = "high" if authority in {"public_filing", "third_party", "customer"} else "medium" if authority == "internal_operating" else "low"
    return SourceQualityNote(
        materialId=material.id,
        materialName=material.name,
        sourceType=material.source_type,
        authority=authority,
        reliability=reliability,
        limitations=limitations,
    )


def extract_claims(state: DiligenceState) -> DiligenceState:
    if deterministic_analysis_enabled():
        claims = deterministic_extract_claims(state)
        return {**state, "claims": claims, **with_llm_output(state, "extract_claims", f"deterministic_claims={len(claims)}")}
    llm = get_llm_client(state)
    if not llm.enabled:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured. Add it to backend/.env.")
    profile = state.get("profile", DealProfile())
    system = (
        "You extract investor diligence claims from deal materials. Return JSON only. "
        "Extract concrete, source-grounded, verifiable VC/PE diligence claims about market, growth, ROI, competition, pricing, retention, "
        "compliance, financials, product, team, go-to-market, fundraising, legal, and operations. "
        "Every claim must include a sourceMaterial and direct sourceSnippet from the supplied context. "
        "Prefer specific claims with metrics, named customers, dates, cohorts, fundraising terms, product capabilities, legal status, "
        "or explicit assertions that would affect an IC decision. Split compound claims when they combine independent facts. "
        f"Extract at most {max_claims_per_material(state)} claims from each source material; choose the claims most likely to change an IC decision. "
        "Initial status must be missing and riskRationale can be empty. "
        "IMPORTANT: The claim text field must be a standalone assertion written in plain English. "
        "Do NOT include source navigation labels such as 'Slide 7:', 'Slide 4:', '### ', 'Claim:', or 'Source:' in the text field. "
        "Strip any such prefix before writing the claim text. "
        "Populate claimKind, extractedFact, sourceLocator, materialityReason, verificationStandard, reviewPriority, and isTargetCompanyClaim."
    )
    raw_outputs: list[str] = []
    claims: list[DealClaim] = []
    for material in state["materials"]:
        source_note = next((note for note in state.get("source_quality", []) if note.materialId == material.id), None)
        user = (
            f"Company: {state['company']}\nProfile: {profile.model_dump_json()}\n"
            f"Source inventory note: {source_note.model_dump_json() if source_note else '{}'}\n\n"
            "Return shape: {\"claims\":[{\"id\":\"claim-01\",\"text\":\"...\",\"category\":\"market|growth|customer_roi|competition|pricing|retention|compliance|financials|product|team|go_to_market|fundraising|legal|operations\","
            "\"sourceMaterial\":\"...\",\"sourceSnippet\":\"...\",\"importance\":\"high|medium|low\",\"status\":\"missing\",\"riskRationale\":\"\","
            "\"claimKind\":\"metric|customer|market|competition|product|compliance|financial|team|fundraising|legal|operational|other\","
            "\"extractedFact\":\"...\",\"sourceLocator\":\"...\",\"materialityReason\":\"...\",\"verificationStandard\":\"founder_statement|internal_document|customer_reference|third_party|audited_financials|legal_document|public_filing\","
            "\"reviewPriority\":\"critical|high|medium|low\",\"isTargetCompanyClaim\":true}]}\n\n"
            f"Material:\n### {material.name}\nKind: {material.kind}\n{material.text[:6_000]}"
        )
        try:
            extracted, raw_output = llm.complete_json_with_raw(system, user, ClaimExtraction, on_chunk=stream_llm_chunk(state, "extract_claims"))
            raw_outputs.append(raw_output)
            claims.extend(extracted.claims[:max_claims_per_material(state)])
        except Exception as exc:
            fallback_claims = deterministic_extract_claims({**state, "materials": [material]})
            fallback_note = (
                f"Claim extraction failed for {material.name} ({exc.__class__.__name__}: {str(exc)[:500]}). "
                f"Continuing with {len(fallback_claims)} deterministic claims from this material."
            )
            emit = stream_llm_chunk(state, "extract_claims")
            if emit:
                emit(f"\n\n[fallback]\n{fallback_note}")
            raw_outputs.append(fallback_note)
            claims.extend(fallback_claims[:max_claims_per_material(state)])
    state = {**state, **with_llm_output(state, "extract_claims", "\n\n".join(raw_outputs))}
    if not claims:
        raise ValueError("No diligence claims were extracted from the supplied materials.")
    return {**state, "claims": claims}


def normalize_claims(state: DiligenceState) -> DiligenceState:
    cleaned = clean_claim_text(state["claims"])
    split_claims = split_compound_claims(cleaned)
    enriched = [decontextualize_claim(claim, state["company"]) for claim in split_claims]
    target_claims = [
        claim for claim in enriched
        if is_target_company_claim(claim, state["company"]) and is_reviewable_claim(claim)
    ]
    deduped = dedupe_claims(target_claims)
    normalized = clean_claim_text(normalize_claim_ids(deduped))
    if not normalized:
        raise ValueError("No target-company diligence claims remained after normalization.")
    return {**state, "claims": normalized}


def rank_claims(state: DiligenceState) -> DiligenceState:
    ranked = [rank_claim_materiality(claim, state.get("source_quality", [])) for claim in state["claims"]]
    ranked.sort(key=claim_materiality_sort_key)
    return {**state, "claims": normalize_claim_ids(select_diverse_claims(ranked, max_claims(state)))}


def retrieve_evidence(state: DiligenceState) -> DiligenceState:
    all_evidence: list[EvidenceItem] = []
    updated_claims: list[DealClaim] = []
    for claim in state["claims"]:
        evidence = fallback_evidence_for_claim(claim, state["chunks"])
        updated = apply_rule_based_status(claim, evidence)
        all_evidence.extend(evidence)
        updated_claims.append(updated)
    return {**state, "claims": updated_claims, "evidence": all_evidence}


def assess_evidence(state: DiligenceState) -> DiligenceState:
    llm = get_llm_client(state)
    evidence = [enrich_evidence_item(item) for item in state.get("evidence", [])]
    if deterministic_analysis_enabled() or not llm.enabled:
        return {**state, "evidence": evidence}

    reviewable = [
        item for item in evidence
        if item.sourceType != "derived" and item.quoteSpan and item.stance in {"supports", "partially_supports", "contradicts"}
    ][:36]
    if not reviewable:
        return {**state, "evidence": evidence}
    claims_by_id = {claim.id: claim for claim in state["claims"]}
    system = (
        "You are reviewing evidence for investor diligence claims. Return JSON only. "
        "For each evidence item, keep or correct stance, assign evidenceRole, quoteConfidence, and assessorRationale. "
        "A support verdict requires entity, metric/date/value, and verification standard to match the claim. "
        "Contradictions outrank support."
    )
    user = (
        "Return shape: {\"reviews\":[{\"claimId\":\"claim-01\",\"evidenceId\":\"ev-...\","
        "\"stance\":\"supports|partially_supports|contradicts|not_found\",\"evidenceRole\":\"primary_support|corroborating_support|contradiction|context|gap\","
        "\"quoteConfidence\":\"high|medium|low\",\"assessorRationale\":\"...\"}]}\n\n"
        + "\n".join(
            f"Claim: {claims_by_id[item.claimId].model_dump_json()}\nEvidence: {item.model_dump_json()}"
            for item in reviewable
            if item.claimId in claims_by_id
        )
    )
    try:
        reviews, raw_output = llm.complete_json_with_raw(system, user, EvidenceReviews, on_chunk=stream_llm_chunk(state, "assess_evidence"))
    except Exception:
        return {**state, "evidence": evidence}
    reviews_by_id = {review.evidenceId: review for review in reviews.reviews}
    updated: list[EvidenceItem] = []
    for item in evidence:
        review = reviews_by_id.get(item.id)
        if review:
            updated.append(
                item.model_copy(
                    update={
                        "stance": review.stance,
                        "evidenceRole": review.evidenceRole,
                        "quoteConfidence": review.quoteConfidence,
                        "assessorRationale": review.assessorRationale,
                    }
                )
            )
        else:
            updated.append(item)
    evidence_by_claim = {claim.id: [item for item in updated if item.claimId == claim.id] for claim in state["claims"]}
    claims = [apply_rule_based_status(claim, evidence_by_claim.get(claim.id, [])) for claim in state["claims"]]
    return {**state, "claims": claims, "evidence": updated, **with_llm_output(state, "assess_evidence", raw_output)}


def enrich_evidence_item(item: EvidenceItem) -> EvidenceItem:
    role = item.evidenceRole
    if item.stance == "contradicts":
        role = "contradiction"
    elif item.stance == "supports":
        role = "primary_support"
    elif item.stance == "not_found":
        role = "gap"
    elif role == "context":
        role = "corroborating_support"
    if item.sourceAuthority == "internal_operating" and item.sourceIndependence in {"third_party", "founder_supplied", "derived"}:
        authority = source_authority_for_independence(item.sourceIndependence, item.citation)
    else:
        authority = item.sourceAuthority
    return item.model_copy(
        update={
            "evidenceRole": role,
            "sourceAuthority": authority,
            "locator": item.locator or item.citation,
            "quoteConfidence": "high" if item.quoteSpan and item.stance in {"supports", "contradicts"} else item.quoteConfidence,
            "assessorRationale": item.assessorRationale or f"Evidence was classified as {item.stance.replace('_', ' ')} by retrieval rules.",
        }
    )


def search_public_web(state: DiligenceState) -> DiligenceState:
    settings = run_settings(state)
    try:
        web_evidence = collect_public_web_evidence(
            state["company"],
            state.get("profile", DealProfile()),
            state["claims"],
            on_progress=web_progress_emitter(state),
            enabled=settings.webResearchEnabled,
            max_claims=settings.maxClaims,
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
    claims = active_claims(state["claims"])
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
    follow_up = [claim.resolutionRequest or claim.verificationNeed for claim in claims if claim.status != "supported"]
    unique_follow_up = list(dict.fromkeys(item for item in follow_up if item))[:6]
    avg_quality = round(sum(claim.qualityScore for claim in claims) / len(claims)) if claims else 0
    penalty = min(30, len(warnings) * 5 + len(duplicated) * 3)
    readiness_status, top_gating_issue, approved_requests = derive_readiness_status(claims, evidence)
    review = QualityReview(
        memoReadinessScore=max(0, min(100, avg_quality - penalty)),
        globalWarnings=warnings,
        duplicatedClaims=duplicated,
        lowValueClaims=low_value,
        recommendedFollowUpEvidence=unique_follow_up,
        overconfidenceWarnings=overconfidence,
        readinessStatus=readiness_status,
        topGatingIssue=top_gating_issue,
        approvedDiligenceRequests=approved_requests or unique_follow_up,
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


def generate_report(state: DiligenceState) -> DiligenceState:
    report = deterministic_diligence_report(state)
    if deterministic_analysis_enabled():
        return {**state, "report": report}
    llm = get_llm_client(state)
    if llm.enabled:
        system = (
            "You write structured IC diligence reports for VC/PE investors. Return JSON only. "
            "Use only the supplied claim ledger, evidence summaries, quality review, and source-quality notes. "
            "Every risk, diligence request, and decision driver must reference claim IDs. "
            "Do not present weak, missing, contradicted, or low-confidence claims as verified."
        )
        seen_quotes: set[str] = set()
        evidence_context = "\n".join(
            evidence_summary_for_claim(claim, state.get("evidence", []), seen_quotes)
            for claim in active_claims(state["claims"])
        )
        user = (
            f"Company: {state['company']}\nProfile: {state.get('profile', DealProfile()).model_dump_json()}\n"
            f"Quality review: {state.get('quality_review', QualityReview()).model_dump_json()}\n"
            f"Source quality notes: {[note.model_dump() for note in state.get('source_quality', [])]}\n"
            f"Claim ledger:\n" + "\n".join(claim.model_dump_json() for claim in active_claims(state["claims"])) + "\n\n"
            f"Evidence summaries:\n{evidence_context}\n\n"
            "Return shape: {\"report\":{\"reportVersion\":\"2.0\",\"company\":\"...\",\"decisionSummary\":\"...\","
            "\"investmentThesis\":\"...\",\"keyVerifiedClaims\":[...],\"disputedClaims\":[...],"
            "\"weakOrMissingClaims\":[...],\"evidenceAssessment\":[...],\"redFlags\":[...],"
            "\"diligencePlan\":[...],\"sourceQualityNotes\":[...],\"icRecommendation\":\"...\","
            "\"appendixClaimLedger\":[...]}}"
        )
        try:
            generated, raw_output = llm.complete_json_with_raw(system, user, ReportGeneration, on_chunk=stream_llm_chunk(state, "generate_report"))
            report = qa_diligence_report(generated.report, state)
            return {**state, "report": report, **with_llm_output(state, "generate_report", raw_output)}
        except Exception:
            pass
    return {**state, "report": report}


def generate_memo(state: DiligenceState) -> DiligenceState:
    if state.get("report"):
        memo = memo_from_report(state["report"], state)
        return {**state, "memo": memo}

    llm = get_llm_client(state)
    if not llm.enabled:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured. Add it to backend/.env.")
    reviewable_claims = active_claims(state["claims"])
    score_summary = score_claims(reviewable_claims, state.get("evidence", []), state.get("quality_review"))
    grade = score_summary.grade
    profile = state.get("profile", DealProfile())
    claim_context = "\n".join(
        f"- [{claim.status}/{claim.importance}/{claim.category}/confidence={claim.confidence}/quality={claim.qualityScore}] "
        f"{claim.text} Rationale: {claim.riskRationale} Verification need: {claim.verificationNeed}"
        for claim in reviewable_claims
        if effective_disposition(claim) not in {"ignored", "needs_evidence"}
    )
    seen_quotes: set[str] = set()
    evidence_context = "\n".join(
        evidence_summary_for_claim(claim, state.get("evidence", []), seen_quotes)
        for claim in reviewable_claims
    )
    quality_context = state.get("quality_review", QualityReview()).model_dump_json()

    # Build specific unresolved-claims block for Fix 6
    unresolved = [
        c for c in reviewable_claims
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
        "Use reviewer disposition as authoritative: ignored and needs_evidence claims must not be presented as strengths. "
        "Verified claims may be presented as trusted only if their evidence context supports that framing.\n\n"
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
        c for c in reviewable_claims
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


def qa_report(state: DiligenceState) -> DiligenceState:
    report = state.get("report")
    if not report:
        return state
    report = qa_diligence_report(report, state)
    memo = memo_from_report(report, state)
    return {**state, "report": report, "memo": memo}


def persist_results(state: DiligenceState) -> DiligenceState:
    generated_at = datetime.now(timezone.utc).isoformat()
    report = state.get("report")
    if report:
        report = report.model_copy(update={"generatedAt": generated_at})
        state = {**state, "report": report}
    db.save_analysis(
        state["deal_id"],
        state["claims"],
        state["evidence"],
        state["memo"],
        state.get("quality_review", QualityReview()),
        generated_at,
        state.get("profile"),
        state.get("report"),
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
    report = deterministic_diligence_report({**reviewed, "company": deal.company, "materials": deal.materials})
    reviewed["on_progress"] = None
    try:
        memo_state = generate_memo({**reviewed, "deal_id": deal_id, "company": deal.company, "stage": deal.stage, "report": report})
        memo = memo_state["memo"]
    except Exception:
        memo = deterministic_review_memo(deal, reviewed["quality_review"], grade)
    db.save_review_artifacts(deal_id, memo, reviewed["quality_review"], report)


def deterministic_review_memo(deal, quality_review: QualityReview, grade: str) -> RiskMemo:
    active = active_claims(deal.claims)
    verified = [claim for claim in active if effective_disposition(claim) == "verified" or claim.status == "supported"]
    unresolved = [claim for claim in active if effective_disposition(claim) != "verified" and claim.status in {"weak", "missing", "contradicted"}]
    strengths = [f"{claim.id}: {claim.text}" for claim in verified if effective_disposition(claim) != "needs_evidence"][:5]
    risks = [f"{claim.id}: {claim.text} — {claim.statusReason or claim.riskRationale}" for claim in unresolved[:6]]
    requests = quality_review.approvedDiligenceRequests or [claim.resolutionRequest for claim in unresolved if claim.resolutionRequest]
    return RiskMemo(
        company=deal.company,
        overallGrade=grade,  # type: ignore[arg-type]
        investmentQuestion=f"Is {deal.company} ready for IC based on verified evidence?",
        keyStrengths=strengths,
        materialRisks=risks,
        followUpQuestions=list(dict.fromkeys(requests))[:8],
        icRecommendation=f"Current readiness: {quality_review.readinessStatus.replace('_', ' ')}. Top gating issue: {quality_review.topGatingIssue or 'none'}.",
        executiveSummary=f"{deal.company} is {quality_review.readinessStatus.replace('_', ' ')} after reviewer updates.",
        thesisAssessment="Use verified strengths only; unresolved claims require the listed diligence requests before IC reliance.",
        evidenceMap=[f"{claim.id} ({claim.status}): {claim.statusReason or claim.riskRationale}" for claim in active[:8]],
        keyRisks=risks,
        nextDiligenceRequests=list(dict.fromkeys(requests))[:8],
        decisionDrivers=[quality_review.topGatingIssue] if quality_review.topGatingIssue else [],
    )


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
    if deterministic_analysis_enabled():
        return deterministic_chat_answer(question, claims, evidence)
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


def deterministic_chat_answer(question: str, claims: list[DealClaim], evidence: list[EvidenceItem]):
    from .models import ChatAnswer

    if not claims:
        return ChatAnswer(answer="No relevant claims were found in the stored analysis.", citations=[], confidence="low")
    citations = list(dict.fromkeys(item.citation for item in evidence if item.sourceType != "derived"))[:5]
    status_counts = Counter(claim.status for claim in claims)
    risky = [claim for claim in claims if claim.status in {"weak", "missing", "contradicted"}]
    supported = [claim for claim in claims if claim.status == "supported"]
    parts = []
    if supported:
        parts.append(f"Supported: {supported[0].id} - {supported[0].text}")
    if risky:
        parts.append(f"Needs diligence: {risky[0].id} is {risky[0].status} - {risky[0].text}")
    answer = (
        f"Based on stored claims and evidence for '{question}', "
        f"the relevant set has {status_counts.get('supported', 0)} supported, "
        f"{status_counts.get('weak', 0)} weak, {status_counts.get('contradicted', 0)} contradicted, "
        f"and {status_counts.get('missing', 0)} missing claims. "
        + " ".join(parts)
    )
    return ChatAnswer(answer=answer, citations=citations, confidence="medium" if citations else "low")


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


CLAIM_KEYWORDS = {
    "arr", "revenue", "growth", "grew", "customers", "signed", "active", "retention", "nrr", "churn",
    "gross margin", "burn", "cash", "market", "tam", "sam", "roi", "save", "savings", "hours",
    "competitor", "competitors", "pricing", "acv", "contract", "compliance", "soc 2", "hipaa",
    "lawsuit", "patent", "funding", "raise", "valuation", "runway", "security", "pilot", "pilots",
}

PUBLIC_ISSUERS = {"apple", "target", "microsoft", "amazon", "google", "alphabet", "meta", "tesla", "nvidia", "walmart"}


def deterministic_extract_claims(state: DiligenceState) -> list[DealClaim]:
    claims: list[DealClaim] = []
    per_material_limit = max_claims_per_material(state)
    for material in state.get("materials", []):
        for sentence in candidate_claim_sentences(material, limit=per_material_limit):
            category = infer_claim_category(sentence, state["company"])
            importance = "high" if category in {"growth", "financials", "customer_roi", "market", "competition", "compliance", "fundraising", "legal"} else "medium"
            claim = DealClaim(
                id=f"claim-{len(claims) + 1:02d}",
                text=standalone_claim_text(sentence, state["company"]),
                category=category,  # type: ignore[arg-type]
                sourceMaterial=material.name,
                sourceSnippet=sentence[:420],
                importance=importance,  # type: ignore[arg-type]
                status="missing",
                riskRationale="",
                claimKind=claim_kind_for_category(category),  # type: ignore[arg-type]
                extractedFact=sentence[:280],
                sourceLocator=material.name,
                materialityReason=materiality_reason_for_category(category),
                verificationStandard=verification_standard_for_category(category, source_quality_note(material).authority),  # type: ignore[arg-type]
                reviewPriority="high" if importance == "high" else "medium",
                isTargetCompanyClaim=True,
            )
            claims.append(claim)
    return claims


def candidate_claim_sentences(material: SourceMaterial, limit: int = 6) -> list[str]:
    text = re.sub(r"\s+", " ", material.text).strip()
    text = text.replace("U.S.", "US").replace("U.K.", "UK")
    pieces = [part.strip(" -•\t") for part in re.split(r"(?<=[.!?])\s+|\n+|(?<=\.)\s*(?=[A-Z][A-Za-z ]+:)", text) if part.strip()]
    scored: list[tuple[int, int, str]] = []
    for piece in pieces:
        if len(piece.split()) < 5 or len(piece) > 650:
            continue
        if is_low_value_sentence(piece):
            continue
        lower = piece.lower()
        keyword_hits = sum(1 for keyword in CLAIM_KEYWORDS if keyword in lower)
        number_hits = len(re.findall(r"\$?\d[\d,.]*(?:%|x|k|m|b)?", piece, flags=re.IGNORECASE))
        if keyword_hits == 0 and number_hits == 0:
            continue
        if lower.startswith(("table of contents", "copyright", "forward-looking statements")):
            continue
        scored.append((number_hits + keyword_hits, number_hits, piece))
    return [piece for _, __, piece in sorted(scored, key=lambda item: (item[0], item[1], len(item[2])), reverse=True)[:limit]]


def is_low_value_sentence(text: str) -> bool:
    stripped = text.strip()
    lower = stripped.lower()
    if stripped.count(",") > 8 or stripped.count("|") > 6:
        return True
    if re.match(r"^\(?\d+\)?\s+[a-z]", stripped):
        return True
    if re.match(r"^\(?\d+\)?\s*[-–—:]", stripped):
        return True
    if stripped.endswith((",", "—", "-", "–", ":")):
        return True
    if lower.startswith(("core capabilities", "current capabilities", "important limitations", "known ai legal tools")):
        return True
    if len(stripped.split()) < 7 and not re.search(r"\d|%|\$", stripped):
        return True
    return False


def infer_claim_category(text: str, company: str = "") -> str:
    lower = text.lower()
    if company:
        lower = lower.replace(company.lower(), "company")
    if any(term in lower for term in ["roi", "save", "savings", "hours", "efficiency"]):
        return "customer_roi"
    if any(term in lower for term in ["competitor", "competition", "alternative", "vs", "versus"]):
        return "competition"
    if any(term in lower for term in ["market", "tam", "sam", "billion opportunity", "forecast"]):
        return "market"
    if any(term in lower for term in ["arr", "mrr", "revenue", "gross margin", "burn", "cash", "financial"]):
        return "financials"
    if any(term in lower for term in ["growth", "grew", "signed", "active customers", "pilot", "pilots"]):
        return "growth"
    if any(term in lower for term in ["nrr", "retention", "churn", "renewal"]):
        return "retention"
    if any(term in lower for term in ["price", "pricing", "acv", "contract value"]):
        return "pricing"
    if any(term in lower for term in ["soc 2", "hipaa", "compliance", "regulatory", "security"]):
        return "compliance"
    if any(term in lower for term in ["raise", "funding", "valuation", "runway", "series"]):
        return "fundraising"
    if any(term in lower for term in ["lawsuit", "patent", "ip", "legal"]):
        return "legal"
    if any(term in lower for term in ["founder", "team", "engineer", "cto", "ceo"]):
        return "team"
    if any(term in lower for term in ["pipeline", "sales", "channel", "partner"]):
        return "go_to_market"
    if any(term in lower for term in ["manufacturing", "supply", "implementation", "operations"]):
        return "operations"
    return "product"


def claim_kind_for_category(category: str) -> str:
    return {
        "financials": "financial",
        "growth": "metric",
        "customer_roi": "customer",
        "market": "market",
        "competition": "competition",
        "compliance": "compliance",
        "fundraising": "fundraising",
        "legal": "legal",
        "operations": "operational",
        "team": "team",
    }.get(category, "product")


def materiality_reason_for_category(category: str) -> str:
    reasons = {
        "financials": "Financial claims directly affect valuation, runway, and IC readiness.",
        "growth": "Growth claims drive traction quality and stage fit.",
        "customer_roi": "Customer ROI claims determine whether adoption is referenceable and repeatable.",
        "market": "Market claims affect venture-scale outcome potential.",
        "competition": "Competition claims affect differentiation and pricing power.",
        "compliance": "Compliance claims can become IC blockers in regulated categories.",
        "fundraising": "Fundraising terms affect ownership, runway, and round risk.",
        "legal": "Legal claims can create direct deal blockers.",
    }
    return reasons.get(category, "This claim affects diligence context but is not the highest-risk category.")


def verification_standard_for_category(category: str, source_authority: str = "founder") -> str:
    if source_authority == "public_filing":
        return "public_filing"
    if category in {"financials", "growth", "retention", "pricing", "fundraising"}:
        return "internal_document"
    if category == "customer_roi":
        return "customer_reference"
    if category in {"market", "competition"}:
        return "third_party"
    if category in {"legal", "compliance"}:
        return "legal_document"
    return "founder_statement"


def standalone_claim_text(text: str, company: str) -> str:
    cleaned = _ARTIFACT_PREFIX.sub("", text).strip()
    cleaned = re.sub(r"^Source snapshot:.*?Snapshot date:\s*\d{4}-\d{2}-\d{2}\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^Public evidence excerpt:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^(?:The Problem|The Market|Go-to-Market|The Ask|Harvey['’]s assessment|Market Context|Core Capabilities|Risks and Mitigants)\s*:\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"^.*?Market Context:\s*(?=(?:US|U\.S\.|Global|In-house|Enterprise)\b)", "", cleaned, flags=re.IGNORECASE).strip()
    if " Harvey is " in cleaned and "—" in cleaned.split(" Harvey is ", 1)[0]:
        cleaned = "Harvey is " + cleaned.split(" Harvey is ", 1)[1]
    cleaned = re.sub(r"^(?:Investor|Winston|Gabriel|Question|Answer|Founder|CEO|CTO)\s*:\s+", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^(we're|we are)\b", f"{company} is", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^(we've|we have)\b", f"{company} has", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^(our)\b", f"{company}'s", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^(we|the company)\b", company, cleaned, flags=re.IGNORECASE).strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else text


def is_reviewable_claim(claim: DealClaim) -> bool:
    text = claim.text.strip()
    lower = text.lower()
    if is_low_value_sentence(text):
        return False
    if text.count(" ") < 4:
        return False
    if re.match(r"^\(?\d+\)?\s+", text):
        return False
    if lower in {"contract drafting", "legal research", "due diligence review"}:
        return False
    if re.match(r"^[A-Z][a-z]+(?:\\s+[a-z]+){0,4}$", text) and not re.search(r"\d|%|\$", text):
        return False
    predicate_terms = [
        " is ", " are ", " has ", " have ", " was ", " were ", " reached ", " grew ", " signed ",
        " says ", " can ", " will ", " costs ", " saves ", " implies ", " represents ", " exceeds ",
        " complete", " in progress", " raising ", " from ", " to ", " at ", " above ",
    ]
    if not any(term in f" {lower} " for term in predicate_terms) and not re.search(r"\$[\d,.]+|\d+%", text):
        return False
    return True


def split_compound_claims(claims: list[DealClaim]) -> list[DealClaim]:
    result: list[DealClaim] = []
    for claim in claims:
        parts = split_claim_text(claim.text)
        if len(parts) <= 1:
            result.append(claim)
            continue
        for part in parts:
            result.append(
                claim.model_copy(
                    update={
                        "text": part,
                        "extractedFact": part,
                        "sourceSnippet": claim.sourceSnippet or claim.text,
                    }
                )
            )
    return result


def split_claim_text(text: str) -> list[str]:
    if len(text) < 80:
        return [text]
    parts = [part.strip(" .;") for part in re.split(r";\s+|\s+\band\b\s+(?=(?:[^.]*\d|[^.]*\$|[^.]*%|[^.]*customers?|[^.]*ARR))", text) if part.strip()]
    claim_like = [part for part in parts if len(part.split()) >= 5]
    return claim_like if len(claim_like) > 1 else [text]


def decontextualize_claim(claim: DealClaim, company: str) -> DealClaim:
    text = standalone_claim_text(claim.text, company)
    return claim.model_copy(update={"text": text, "extractedFact": claim.extractedFact or text})


def is_target_company_claim(claim: DealClaim, company: str) -> bool:
    if not claim.isTargetCompanyClaim:
        return False
    lower = f"{claim.text} {claim.sourceMaterial}".lower().replace("_", " ")
    company_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", company.lower()) if len(token) > 2}
    mentioned_public = {issuer for issuer in PUBLIC_ISSUERS if re.search(rf"\b{re.escape(issuer)}\b", lower)}
    if mentioned_public and not (mentioned_public & company_tokens):
        return False
    return True


def dedupe_claims(claims: list[DealClaim]) -> list[DealClaim]:
    seen: set[str] = set()
    deduped: list[DealClaim] = []
    for claim in claims:
        signature = claim_signature(claim.text, claim.category)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(claim)
    return deduped


def claim_signature(text: str, category: str) -> str:
    stop = {"the", "and", "for", "with", "that", "this", "from", "into", "company", "claims", "claim"}
    terms = [term for term in re.findall(r"[a-zA-Z0-9$%]+", text.lower()) if term not in stop]
    return f"{category}:{' '.join(sorted(terms)[:12])}"


def rank_claim_materiality(claim: DealClaim, source_quality: list[SourceQualityNote]) -> DealClaim:
    category = claim.category
    priority = "critical" if category in {"financials", "growth", "customer_roi", "competition", "compliance", "fundraising", "legal"} and claim.importance == "high" else "high" if claim.importance == "high" else "medium"
    source_note = next((note for note in source_quality if note.materialName == claim.sourceMaterial), None)
    standard = claim.verificationStandard
    if standard == "founder_statement":
        standard = verification_standard_for_category(category, source_note.authority if source_note else "founder")  # type: ignore[arg-type]
    return claim.model_copy(
        update={
            "claimKind": claim.claimKind if claim.claimKind != "other" else claim_kind_for_category(category),
            "materialityReason": claim.materialityReason or materiality_reason_for_category(category),
            "verificationStandard": standard,
            "reviewPriority": priority,
            "decisionImpact": decision_impact_for_category(category, claim.importance),
            "sourceLocator": claim.sourceLocator or claim.sourceMaterial,
        }
    )


def decision_impact_for_category(category: str, importance: str) -> str:
    if importance == "high" or category in {"growth", "financials", "customer_roi", "fundraising", "legal", "compliance"}:
        return "high"
    if category in {"market", "competition", "pricing", "retention", "product", "go_to_market", "operations"}:
        return "medium"
    return "low"


def claim_materiality_sort_key(claim: DealClaim) -> tuple[int, int, int, int, str]:
    priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    importance_rank = {"high": 0, "medium": 1, "low": 2}
    category_rank = {
        "financials": 0,
        "growth": 1,
        "customer_roi": 2,
        "competition": 3,
        "market": 4,
        "compliance": 5,
        "fundraising": 6,
        "legal": 7,
    }
    return (
        priority_rank.get(claim.reviewPriority, 4),
        importance_rank.get(claim.importance, 3),
        category_rank.get(claim.category, 9),
        claim_metric_sort_rank(claim),
        claim.text,
    )


def claim_metric_sort_rank(claim: DealClaim) -> int:
    lower = claim.text.lower()
    if claim.category == "financials":
        if "arr" in lower:
            return 0
        if "gross margin" in lower:
            return 1
        if "revenue" in lower:
            return 2
        if "cash" in lower or "burn" in lower:
            return 3
    if claim.category == "customer_roi" and "roi" in lower:
        return 0
    if claim.category == "competition" and "no direct" in lower:
        return 0
    return 5


def select_diverse_claims(claims: list[DealClaim], limit: int) -> list[DealClaim]:
    category_caps = {
        "financials": 3,
        "growth": 1,
        "customer_roi": 1,
        "competition": 1,
        "market": 1,
        "compliance": 1,
        "fundraising": 1,
        "legal": 1,
    }
    selected: list[DealClaim] = []
    category_counts: Counter[str] = Counter()
    for claim in claims:
        if len(selected) >= limit:
            break
        if category_counts[claim.category] >= category_caps.get(claim.category, 1):
            continue
        selected.append(claim)
        category_counts[claim.category] += 1
    if len(selected) < limit:
        selected_ids = {claim.id for claim in selected}
        for claim in claims:
            if len(selected) >= limit:
                break
            if claim.id not in selected_ids:
                selected.append(claim)
                selected_ids.add(claim.id)
    selected.sort(key=claim_materiality_sort_key)
    return selected


def deterministic_diligence_report(state: DiligenceState) -> DiligenceReport:
    claims = active_claims(state.get("claims", []))
    evidence = state.get("evidence", [])
    evidence_by_claim = {claim.id: [item for item in evidence if item.claimId == claim.id] for claim in claims}
    review = state.get("quality_review", QualityReview())
    score = score_claims(claims, evidence, review)
    verified = [claim_ref(claim, evidence_by_claim.get(claim.id, [])) for claim in claims if claim.status == "supported"][:6]
    disputed = [claim_ref(claim, evidence_by_claim.get(claim.id, [])) for claim in claims if claim.status == "contradicted"][:8]
    weak_missing = [claim_ref(claim, evidence_by_claim.get(claim.id, [])) for claim in claims if claim.status in {"weak", "missing"}][:10]
    source_notes = state.get("source_quality") or [source_quality_note(material) for material in state.get("materials", [])]
    diligence_plan = review.approvedDiligenceRequests or list(dict.fromkeys(claim.resolutionRequest for claim in claims if claim.resolutionRequest))[:10]
    if not diligence_plan and weak_missing:
        diligence_plan = [f"Provide source-level evidence for {item.claimId}: {item.text}" for item in weak_missing[:5]]
    if not diligence_plan:
        diligence_plan = ["Confirm no newer contradictory source has emerged before relying on the supported claims at IC."]
    red_flags = report_red_flags(claims, review)
    decision = (
        f"{state['company']} is {review.readinessStatus.replace('_', ' ')} with a {score.grade} IC readiness grade "
        f"({score.overall}/100). {review.topGatingIssue or score.drivers[0]}"
    )
    thesis = (
        "The investable case should rely only on quote-backed supported claims; unresolved claims remain diligence gating items."
        if disputed or weak_missing else
        "The current packet supports the core diligence claims with quote-backed evidence."
    )
    return DiligenceReport(
        company=state["company"],
        decisionSummary=decision,
        investmentThesis=thesis,
        keyVerifiedClaims=verified,
        disputedClaims=disputed,
        weakOrMissingClaims=weak_missing,
        evidenceAssessment=[evidence_summary_for_claim(claim, evidence) for claim in claims[:8]],
        redFlags=red_flags,
        diligencePlan=diligence_plan[:12],
        sourceQualityNotes=source_notes,
        icRecommendation=recommendation_for_report(score.grade, review),
        appendixClaimLedger=[claim_ref(claim, evidence_by_claim.get(claim.id, [])) for claim in claims],
    )


def claim_ref(claim: DealClaim, evidence: list[EvidenceItem]) -> ReportClaimRef:
    return ReportClaimRef(
        claimId=claim.id,
        text=claim.text,
        status=claim.status,
        rationale=claim.statusReason or claim.riskRationale or claim.materialityReason,
        evidenceIds=[item.id for item in evidence if item.sourceType != "derived"][:4],
    )


def report_red_flags(claims: list[DealClaim], review: QualityReview) -> list[str]:
    flags = list(review.globalWarnings)
    for claim in claims:
        if claim.status == "contradicted":
            flags.append(f"{claim.id}: contradicted claim requires reconciliation before IC - {claim.text}")
        elif claim.status == "missing" and claim.importance == "high":
            flags.append(f"{claim.id}: high-importance claim has no quote-backed support - {claim.text}")
    return list(dict.fromkeys(flags))[:10]


def recommendation_for_report(grade: str, review: QualityReview) -> str:
    if review.readinessStatus == "blocked":
        return f"Do not take to IC until the blocker is resolved: {review.topGatingIssue}"
    if grade == "red":
        return f"Screen out or pause until source-level evidence resolves the top issue: {review.topGatingIssue or 'insufficient support.'}"
    if grade == "yellow":
        return f"Continue diligence, but require the listed evidence requests before IC reliance. Top issue: {review.topGatingIssue or 'none.'}"
    return "Proceed toward IC if no newer contradictory evidence appears and reviewer verification is complete."


def qa_diligence_report(report: DiligenceReport, state: DiligenceState) -> DiligenceReport:
    claims = active_claims(state.get("claims", []))
    claim_by_id = {claim.id: claim for claim in claims}
    evidence_by_claim = {claim.id: [item for item in state.get("evidence", []) if item.claimId == claim.id] for claim in claims}

    def valid_refs(refs: list[ReportClaimRef], statuses: set[str] | None = None) -> list[ReportClaimRef]:
        filtered: list[ReportClaimRef] = []
        for ref in refs:
            claim = claim_by_id.get(ref.claimId)
            if not claim or (statuses and claim.status not in statuses):
                continue
            filtered.append(claim_ref(claim, evidence_by_claim.get(claim.id, [])))
        return filtered

    verified = valid_refs(report.keyVerifiedClaims, {"supported"}) or [claim_ref(claim, evidence_by_claim.get(claim.id, [])) for claim in claims if claim.status == "supported"][:6]
    disputed = valid_refs(report.disputedClaims, {"contradicted"}) or [claim_ref(claim, evidence_by_claim.get(claim.id, [])) for claim in claims if claim.status == "contradicted"][:8]
    weak_missing = valid_refs(report.weakOrMissingClaims, {"weak", "missing"}) or [claim_ref(claim, evidence_by_claim.get(claim.id, [])) for claim in claims if claim.status in {"weak", "missing"}][:10]
    appendix = [claim_ref(claim, evidence_by_claim.get(claim.id, [])) for claim in claims]
    diligence_plan = list(dict.fromkeys(report.diligencePlan or [claim.resolutionRequest for claim in claims if claim.resolutionRequest]))[:12]
    if (disputed or weak_missing) and not diligence_plan:
        diligence_plan = [f"Resolve {ref.claimId}: {ref.text}" for ref in [*disputed, *weak_missing][:6]]
    if not diligence_plan:
        diligence_plan = ["Confirm no newer contradictory source has emerged before relying on the supported claims at IC."]
    source_notes = report.sourceQualityNotes or state.get("source_quality", [])
    return report.model_copy(
        update={
            "company": state["company"],
            "keyVerifiedClaims": verified,
            "disputedClaims": disputed,
            "weakOrMissingClaims": weak_missing,
            "appendixClaimLedger": appendix,
            "diligencePlan": diligence_plan,
            "sourceQualityNotes": source_notes,
            "redFlags": list(dict.fromkeys([*report.redFlags, *report_red_flags(claims, state.get("quality_review", QualityReview()))]))[:10],
        }
    )


def memo_from_report(report: DiligenceReport, state: DiligenceState) -> RiskMemo:
    score = score_claims(state.get("claims", []), state.get("evidence", []), state.get("quality_review"))
    risks = [f"{ref.claimId}: {ref.text} - {ref.rationale}" for ref in [*report.disputedClaims, *report.weakOrMissingClaims]][:8]
    risks = risks or report.redFlags or score.drivers
    strengths = [f"{ref.claimId}: {ref.text}" for ref in report.keyVerifiedClaims][:6]
    return RiskMemo(
        company=report.company,
        overallGrade=score.grade,  # type: ignore[arg-type]
        investmentQuestion=f"Is {report.company} ready for IC based on quote-backed evidence?",
        keyStrengths=strengths,
        materialRisks=risks or report.redFlags,
        followUpQuestions=report.diligencePlan,
        icRecommendation=report.icRecommendation,
        executiveSummary=report.decisionSummary,
        thesisAssessment=report.investmentThesis,
        evidenceMap=report.evidenceAssessment,
        keyRisks=risks or report.redFlags,
        nextDiligenceRequests=report.diligencePlan,
        decisionDrivers=report.redFlags[:5] or score.drivers,
    )


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
