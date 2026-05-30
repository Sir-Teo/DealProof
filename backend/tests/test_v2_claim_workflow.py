import uuid

from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.graph import (
    deterministic_diligence_report,
    extract_claims,
    generate_memo,
    generate_report,
    memo_from_report,
    normalize_claims,
    profile_deal,
    rank_claims,
    source_quality_note,
)
from app.models import AppSettings, DealClaim, EvidenceItem, MemoGeneration, QualityReview, RiskMemo, SourceMaterial
from app.scoring import apply_rule_based_status


def base_claim(**updates) -> DealClaim:
    data = {
        "id": "claim-01",
        "text": "DMs Revenue Flow reached $2.56M ARR by month 24 and gross margin reached 75% in Q4.",
        "category": "financials",
        "sourceMaterial": "pitch.txt",
        "sourceSnippet": "ARR and gross margin claims.",
        "importance": "high",
    }
    data.update(updates)
    return DealClaim(**data)


def test_normalize_claims_splits_dedupes_and_filters_off_target_public_issuers():
    state = {
        "company": "DMs Revenue Flow",
        "claims": [
            base_claim(),
            base_claim(id="claim-02"),
            base_claim(
                id="claim-03",
                text="Apple grew services revenue in fiscal 2025.",
                sourceMaterial="apple_10k.txt",
                sourceSnippet="Apple services revenue.",
            ),
        ],
    }

    normalized = normalize_claims(state)["claims"]
    text = "\n".join(claim.text for claim in normalized)

    assert len({claim.text for claim in normalized}) == len(normalized)
    assert "Apple grew services revenue" not in text
    assert any("$2.56M ARR" in claim.text for claim in normalized)
    assert any("gross margin" in claim.text.lower() for claim in normalized)


def test_rank_claims_assigns_materiality_and_verification_standard():
    material = SourceMaterial(
        id="mat-01",
        deal_id="deal-01",
        name="financial_model.txt",
        kind="financials",
        source_type="file",
        text="ARR reached $2.56M by month 24.",
    )
    state = {
        "claims": [base_claim(text="ARR reached $2.56M by month 24.")],
        "source_quality": [source_quality_note(material)],
    }

    ranked = rank_claims(state)["claims"][0]

    assert ranked.reviewPriority in {"critical", "high"}
    assert ranked.verificationStandard == "internal_document"
    assert ranked.materialityReason
    assert ranked.decisionImpact == "high"


def test_evidence_standard_controls_supported_status_and_rationale():
    claim = base_claim(
        text="Customer ROI is proven by independent references.",
        category="customer_roi",
        verificationStandard="customer_reference",
    )

    founder_evidence = [
        EvidenceItem(
            id="ev-founder",
            claimId=claim.id,
            title="Founder deck",
            sourceType="uploaded",
            citation="pitch_deck.txt, chunk 1",
            snippet="Customer ROI is proven.",
            stance="supports",
            reliability="high",
            sourceIndependence="founder_supplied",
            sourceAuthority="founder",
            quoteSpan="Customer ROI is proven.",
        )
    ]
    customer_evidence = [
        founder_evidence[0].model_copy(
            update={
                "id": "ev-customer",
                "sourceIndependence": "third_party",
                "sourceAuthority": "customer",
                "citation": "customer_reference.txt, chunk 1",
            }
        )
    ]

    assert apply_rule_based_status(claim, founder_evidence).status == "weak"
    supported = apply_rule_based_status(claim, customer_evidence)
    assert supported.status == "supported"
    assert "customer reference verification standard" in supported.riskRationale


def test_profile_step_falls_back_when_llm_profile_generation_fails(monkeypatch):
    class FailingProfileLlm:
        enabled = True

        def complete_json_with_raw(self, *args, **kwargs):
            raise ValueError("profile response was not valid JSON")

    monkeypatch.setattr("app.graph.get_llm_client", lambda _state: FailingProfileLlm())
    material = SourceMaterial(
        id="mat-profile",
        deal_id="deal-profile",
        name="legal_ai_deck.txt",
        kind="deck",
        source_type="file",
        text="Legal AI workflow software sold as enterprise seat subscriptions to law firms.",
    )

    result = profile_deal({
        "deal_id": "deal-profile",
        "company": "ProfileCo",
        "stage": "Seed",
        "materials": [material],
    })

    assert result["profile"].sector == "Legal AI"
    assert result["profile"].businessModel == "Enterprise SaaS"
    assert "Profile generation failed" in result["llm_outputs"]["profile_deal"]


def test_claim_extraction_falls_back_when_llm_claim_generation_fails(monkeypatch):
    class FailingClaimsLlm:
        enabled = True

        def complete_json_with_raw(self, *args, **kwargs):
            raise ValueError("claim response was not valid JSON")

    monkeypatch.setattr("app.graph.get_llm_client", lambda _state: FailingClaimsLlm())
    material = SourceMaterial(
        id="mat-claims",
        deal_id="deal-claims",
        name="financial_model.txt",
        kind="financials",
        source_type="file",
        text="ARR reached $2.56M by month 24. Gross margin reached 75% in Q4.",
    )

    result = extract_claims({
        "deal_id": "deal-claims",
        "company": "ClaimCo",
        "stage": "Seed",
        "materials": [material],
        "source_quality": [source_quality_note(material)],
        "settings": AppSettings(maxClaims=6, maxClaimsPerMaterial=6, deepseekModel="deepseek-v4-flash", webResearchEnabled=False),
    })

    assert result["claims"]
    assert result["claims"][0].sourceMaterial == "financial_model.txt"
    assert "Claim extraction failed for financial_model.txt" in result["llm_outputs"]["extract_claims"]


def test_diligence_report_persists_and_keeps_weak_claims_out_of_verified_section():
    deal_id = f"deal-v2-{uuid.uuid4().hex[:8]}"
    supported = base_claim(status="supported", qualityScore=92, statusReason="Supported by financial model.")
    weak = base_claim(
        id="claim-02",
        text="ROI is independently proven.",
        category="customer_roi",
        status="weak",
        qualityScore=45,
        resolutionRequest="Provide customer-level ROI evidence.",
    )
    evidence = [
        EvidenceItem(
            id="ev-01",
            claimId=supported.id,
            title="Financial model",
            sourceType="uploaded",
            citation="financial_model.txt, chunk 1",
            snippet="ARR reached $2.56M by month 24.",
            stance="supports",
            reliability="high",
            sourceIndependence="internal",
            sourceAuthority="internal_operating",
            quoteSpan="ARR reached $2.56M by month 24.",
        )
    ]
    review = QualityReview(
        memoReadinessScore=68,
        readinessStatus="needs_diligence",
        topGatingIssue="claim-02: ROI needs evidence.",
        approvedDiligenceRequests=[weak.resolutionRequest],
    )
    report = deterministic_diligence_report(
        {
            "company": "DMs Revenue Flow",
            "claims": [supported, weak],
            "evidence": evidence,
            "quality_review": review,
            "materials": [],
        }
    )
    memo = memo_from_report(
        report,
        {"claims": [supported, weak], "evidence": evidence, "quality_review": review},
    )

    db.init_db()
    db.create_deal(deal_id, "DMs Revenue Flow", stage="Seed")
    db.save_analysis(deal_id, [supported, weak], evidence, memo, review, "2026-05-26T00:00:00+00:00", report=report)
    loaded = db.get_deal(deal_id)

    assert loaded.report is not None
    assert loaded.report.keyVerifiedClaims[0].claimId == supported.id
    assert all(item.claimId != weak.id for item in loaded.report.keyVerifiedClaims)
    assert loaded.report.diligencePlan == [weak.resolutionRequest]
    assert loaded.report.icRecommendation.startswith("Continue diligence")


def test_report_generation_fallback_records_llm_failure(monkeypatch):
    class FailingReportLlm:
        enabled = True

        def complete_json_with_raw(self, *args, **kwargs):
            raise ValueError("report response was not valid JSON")

    monkeypatch.setattr("app.graph.get_llm_client", lambda _state: FailingReportLlm())
    supported = base_claim(status="supported", qualityScore=92, statusReason="Supported by financial model.")
    review = QualityReview(memoReadinessScore=80, readinessStatus="ic_ready", topGatingIssue="No unresolved IC blockers.")

    result = generate_report({
        "company": "DMs Revenue Flow",
        "claims": [supported],
        "evidence": [],
        "quality_review": review,
        "materials": [],
    })

    assert result["report"].company == "DMs Revenue Flow"
    assert "Report generation failed" in result["llm_outputs"]["generate_report"]


def test_memo_generation_uses_live_llm_when_report_exists(monkeypatch):
    calls = []

    class MemoLlm:
        enabled = True

        def complete_json_with_raw(self, system, user, schema, **kwargs):
            calls.append(user)
            return (
                MemoGeneration(
                    memo=RiskMemo(
                        company="DMs Revenue Flow",
                        overallGrade="red",
                        investmentQuestion="Can the deal clear IC?",
                        keyStrengths=["LLM strength"],
                        materialRisks=["LLM risk"],
                        followUpQuestions=["LLM follow-up"],
                        icRecommendation="LLM recommendation.",
                        executiveSummary="LLM memo summary.",
                    )
                ),
                '{"memo":{"executiveSummary":"LLM memo summary."}}',
            )

    monkeypatch.setattr("app.graph.get_llm_client", lambda _state: MemoLlm())
    supported = base_claim(status="supported", qualityScore=92, statusReason="Supported by financial model.")
    review = QualityReview(memoReadinessScore=80, readinessStatus="ic_ready", topGatingIssue="No unresolved IC blockers.")
    report = deterministic_diligence_report({
        "company": "DMs Revenue Flow",
        "claims": [supported],
        "evidence": [],
        "quality_review": review,
        "materials": [],
    })

    result = generate_memo({
        "company": "DMs Revenue Flow",
        "claims": [supported],
        "evidence": [],
        "quality_review": review,
        "report": report,
    })

    assert calls
    assert "Structured report context" in calls[0]
    assert result["memo"].executiveSummary == "LLM memo summary."
    assert result["memo"].overallGrade == "green"
    assert result["llm_outputs"]["generate_memo"]


def test_demo_packet_can_run_with_deterministic_v2_fixture_without_live_llm(monkeypatch):
    monkeypatch.setenv("DEALPROOF_DETERMINISTIC_ANALYSIS", "1")
    monkeypatch.setenv("DEALPROOF_WEB_SEARCH_ENABLED", "0")
    monkeypatch.setattr("app.graph.DeepSeekClient", lambda: type("FakeDeepSeek", (), {"enabled": False})())
    monkeypatch.setattr("app.graph.collect_public_web_evidence", lambda *args, **kwargs: [])

    with TestClient(app) as client:
        created = client.post("/deals/demo")
        analyzed = client.post(f"/deals/{created.json()['id']}/analyze")

    assert analyzed.status_code == 200
    payload = analyzed.json()
    assert payload["report"]["reportVersion"] == "2.0"
    assert payload["report"]["decisionSummary"]
    assert payload["memo"]["overallGrade"] == payload["score"]["grade"]
    assert len(payload["claims"]) == 5
    assert all(claim["verificationStandard"] for claim in payload["claims"])
