from app.models import DealClaim, EvidenceItem
from app.scoring import apply_rule_based_status, score_claims


def claim() -> DealClaim:
    return DealClaim(
        id="claim-01",
        text="ARR doubled in Q1.",
        category="growth",
        sourceMaterial="deck",
        sourceSnippet="ARR doubled in Q1.",
        importance="high",
    )


def test_supported_status_from_evidence():
    updated = apply_rule_based_status(
        claim(),
        [
            EvidenceItem(
                id="ev-01",
                claimId="claim-01",
                title="ARR table",
                sourceType="uploaded",
                citation="financials.csv",
                snippet="ARR doubled",
                stance="supports",
                reliability="high",
                quoteSpan="ARR doubled in Q1.",
            )
        ],
    )

    assert updated.status == "supported"
    assert updated.confidence in {"medium", "high"}
    assert updated.qualityScore > 0


def test_support_requires_quote_backed_citation():
    updated = apply_rule_based_status(
        claim(),
        [
            EvidenceItem(
                id="ev-01",
                claimId="claim-01",
                title="ARR table",
                sourceType="uploaded",
                citation="financials.csv",
                snippet="ARR doubled",
                stance="supports",
                reliability="high",
            )
        ],
    )

    assert updated.status == "weak"
    assert "Evidence is missing an exact quote-backed citation." in updated.qualityIssues


def test_founder_only_support_is_not_overconfident():
    updated = apply_rule_based_status(
        claim(),
        [
            EvidenceItem(
                id="ev-01",
                claimId="claim-01",
                title="Founder deck",
                sourceType="uploaded",
                citation="pitch_deck.txt",
                snippet="ARR doubled in Q1.",
                stance="supports",
                reliability="high",
                sourceIndependence="founder_supplied",
                relevanceScore=0.91,
            )
        ],
    )

    assert updated.status == "weak"
    assert updated.confidence != "high"
    assert "Only founder-supplied evidence was found." in updated.qualityIssues


def test_missing_status_from_no_evidence():
    updated = apply_rule_based_status(claim(), [])

    assert updated.status == "missing"


def test_score_claims_counts_statuses():
    claims = [
        claim().model_copy(update={"status": "supported"}),
        claim().model_copy(update={"id": "claim-02", "status": "missing"}),
    ]

    score = score_claims(claims)

    assert score.grade == "red"
    assert score.counts["supported"] == 1
    assert score.counts["missing"] == 1


def test_high_impact_contradiction_forces_red_score():
    claims = [
        claim().model_copy(update={"status": "supported", "qualityScore": 94, "decisionImpact": "high"}),
        claim().model_copy(update={"id": "claim-02", "status": "contradicted", "qualityScore": 15, "decisionImpact": "high"}),
    ]

    score = score_claims(claims)

    assert score.grade == "red"
    assert score.overall <= 59
    assert "Unresolved high-impact contradiction blocks IC readiness." in score.drivers


def test_high_importance_missing_claim_prevents_green_score():
    claims = [
        claim().model_copy(update={"status": "supported", "qualityScore": 96, "decisionImpact": "high"}),
        claim().model_copy(update={"id": "claim-02", "status": "missing", "qualityScore": 20, "importance": "high", "decisionImpact": "medium"}),
    ]

    score = score_claims(claims)

    assert score.grade != "green"
    assert score.overall <= 84
    assert "High-importance missing evidence prevents a green score." in score.drivers


def test_independent_supported_claims_can_be_green():
    claims = [
        claim().model_copy(update={"status": "supported", "qualityScore": 94, "decisionImpact": "high"}),
        claim().model_copy(update={"id": "claim-02", "status": "supported", "qualityScore": 91, "decisionImpact": "medium"}),
    ]
    evidence = [
        EvidenceItem(
            id="ev-01",
            claimId="claim-01",
            title="ARR table",
            sourceType="uploaded",
            citation="financials.csv",
            snippet="ARR doubled",
            stance="supports",
            reliability="high",
            sourceIndependence="third_party",
            quoteSpan="ARR doubled in Q1.",
        ),
        EvidenceItem(
            id="ev-02",
            claimId="claim-02",
            title="Customer cohort",
            sourceType="uploaded",
            citation="cohort.csv",
            snippet="ARR doubled",
            stance="supports",
            reliability="high",
            sourceIndependence="third_party",
            quoteSpan="ARR doubled in Q1.",
        ),
    ]

    score = score_claims(claims, evidence)

    assert score.grade == "green"
    assert score.overall >= 85


def test_founder_only_or_no_third_party_support_does_not_over_score():
    claims = [claim().model_copy(update={"status": "supported", "qualityScore": 92, "decisionImpact": "high"})]
    evidence = [
        EvidenceItem(
            id="ev-01",
            claimId="claim-01",
            title="Founder deck",
            sourceType="uploaded",
            citation="deck.txt",
            snippet="ARR doubled",
            stance="supports",
            reliability="high",
            sourceIndependence="founder_supplied",
            quoteSpan="ARR doubled in Q1.",
        )
    ]

    score = score_claims(claims, evidence)

    assert score.grade != "green"
    assert score.overall <= 84
    assert "No third-party validation is attached; score is capped below green." in score.drivers
