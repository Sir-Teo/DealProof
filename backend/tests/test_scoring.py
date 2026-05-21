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
            )
        ],
    )

    assert updated.status == "supported"


def test_missing_status_from_no_evidence():
    updated = apply_rule_based_status(claim(), [])

    assert updated.status == "missing"


def test_score_claims_yellow():
    claims = [
        claim().model_copy(update={"status": "supported"}),
        claim().model_copy(update={"id": "claim-02", "status": "missing"}),
    ]

    _, grade, counts = score_claims(claims)

    assert grade == "yellow"
    assert counts["supported"] == 1
    assert counts["missing"] == 1
