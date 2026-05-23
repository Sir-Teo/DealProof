from __future__ import annotations

from collections import Counter

from .models import DealClaim, EvidenceItem, QualityReview, RiskMemo, ScoreSummary
from .config import MEMO_TITLE

STATUS_SCORE = {"supported": 88, "weak": 55, "missing": 24, "contradicted": 8}
IMPORTANCE_WEIGHT = {"high": 1.5, "medium": 1.0, "low": 0.7}
DECISION_IMPACT_WEIGHT = {"high": 1.25, "medium": 1.0, "low": 0.85}
HIGH_RISK_CATEGORIES = {"customer_roi", "competition", "market", "growth", "financials", "retention", "compliance", "fundraising", "legal"}
COUNT_KEYS = ["supported", "weak", "contradicted", "missing"]


def score_claims(
    claims: list[DealClaim],
    evidence: list[EvidenceItem] | None = None,
    quality_review: QualityReview | None = None,
) -> ScoreSummary:
    evidence = evidence or []
    counts = status_counts(claims)
    if not claims:
        return ScoreSummary(overall=0, grade="red", counts=counts, drivers=["No diligence claims were scored."])

    evidence_by_claim = {claim.id: [item for item in evidence if item.claimId == claim.id] for claim in claims}
    weighted_score = 0.0
    total_weight = 0.0
    for claim in claims:
        weight = IMPORTANCE_WEIGHT[claim.importance] * DECISION_IMPACT_WEIGHT[claim.decisionImpact]
        weighted_score += claim_readiness_score(claim, evidence_by_claim.get(claim.id, [])) * weight
        total_weight += weight

    raw_score = round(weighted_score / total_weight) if total_weight else 0
    drivers: list[str] = []
    score = raw_score

    if evidence and not any(item.sourceIndependence == "third_party" for item in evidence):
        score -= 8
        drivers.append("No third-party validation is attached; score is capped below green.")

    if quality_review:
        if quality_review.memoReadinessScore < 60:
            score -= 8
            drivers.append(f"Memo readiness is low at {quality_review.memoReadinessScore}/100.")
        if quality_review.globalWarnings:
            penalty = min(12, len(quality_review.globalWarnings) * 4)
            score -= penalty
            drivers.extend(quality_review.globalWarnings[:2])

    score_cap = 100
    unresolved = [claim for claim in claims if claim.reviewerStatus != "verified"]
    if any(claim.status == "contradicted" and claim.decisionImpact == "high" for claim in unresolved):
        score_cap = min(score_cap, 59)
        drivers.append("Unresolved high-impact contradiction blocks IC readiness.")
    if any(claim.status == "missing" and claim.importance == "high" for claim in unresolved):
        score_cap = min(score_cap, 84)
        drivers.append("High-importance missing evidence prevents a green score.")
    if evidence and not any(item.sourceIndependence == "third_party" for item in evidence):
        score_cap = min(score_cap, 84)

    overall = clamp_score(min(score, score_cap))
    grade = "green" if overall >= 85 else "yellow" if overall >= 60 else "red"
    if not drivers:
        drivers.append("Claim quality, materiality, and evidence support are strong enough for this band.")

    return ScoreSummary(overall=overall, grade=grade, counts=counts, drivers=unique_items(drivers)[:4])


def status_counts(claims: list[DealClaim]) -> dict[str, int]:
    counts = Counter(c.status for c in claims)
    return {key: counts.get(key, 0) for key in COUNT_KEYS}


def claim_readiness_score(claim: DealClaim, evidence: list[EvidenceItem]) -> int:
    quality_score = claim.qualityScore if claim.qualityScore > 0 else STATUS_SCORE[claim.status]
    score = round(STATUS_SCORE[claim.status] * 0.35 + quality_score * 0.65)
    if claim.reviewerStatus == "verified":
        score = max(score, 90)
    elif claim.reviewerStatus == "needs_evidence":
        score -= 12
    if claim.status != "supported" and claim.category in HIGH_RISK_CATEGORIES:
        score -= 6
    if any(item.sourceIndependence == "third_party" and item.stance == "supports" for item in evidence):
        score += 6
    elif any(item.stance in {"supports", "partially_supports"} and item.sourceIndependence == "founder_supplied" for item in evidence):
        score -= 8
    if evidence and not any(item.sourceIndependence == "third_party" for item in evidence):
        score -= 4
    if any(item.stance == "contradicts" for item in evidence):
        score -= 12
    return clamp_score(score)


def clamp_score(score: int | float) -> int:
    return max(0, min(100, round(score)))


def unique_items(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def apply_rule_based_status(claim: DealClaim, evidence: list[EvidenceItem]) -> DealClaim:
    stances = {item.stance for item in evidence}
    independent_support = any(
        item.stance == "supports" and item.sourceIndependence != "founder_supplied" and has_audit_citation(item)
        for item in evidence
    )
    founder_only_support = any(item.stance in {"supports", "partially_supports"} for item in evidence) and not independent_support
    contradiction = any(item.stance == "contradicts" and has_audit_citation(item) for item in evidence)
    if contradiction:
        status = "contradicted"
    elif independent_support:
        status = "supported"
    elif "partially_supports" in stances or founder_only_support:
        status = "weak"
    else:
        status = "missing"

    quality_issues = quality_issues_for_claim(claim, evidence, status)
    quality_score = quality_score_for_claim(claim, evidence, status, quality_issues)
    confidence = "high" if quality_score >= 82 else "medium" if quality_score >= 55 else "low"
    verification_need = verification_need_for_claim(claim, evidence, status)
    has_public_web = any(item.sourceType == "public_web" for item in evidence)
    rationale = {
        "supported": "The claim is supported by quote-backed public web evidence." if has_public_web else "The claim is supported by cited material supplied for this deal.",
        "weak": "The claim has partial support, but methodology, cohort, or external validation is incomplete.",
        "contradicted": "The claim conflicts with cited public web evidence." if has_public_web else "The claim conflicts with cited material or supplied source evidence.",
        "missing": "No reliable uploaded or supplied-URL evidence supports this claim.",
    }[status]
    if claim.riskRationale and claim.status == status:
        rationale = claim.riskRationale
    return claim.model_copy(
        update={
            "status": status,
            "riskRationale": rationale,
            "confidence": confidence,
            "qualityScore": quality_score,
            "qualityIssues": quality_issues,
            "verificationNeed": verification_need,
            "decisionImpact": decision_impact_for_claim(claim),
        }
    )


def has_audit_citation(item: EvidenceItem) -> bool:
    return bool(
        item.citation.strip()
        and item.quoteSpan
        and item.quoteSpan.strip()
        and item.sourceType != "derived"
        and item.sourceIndependence != "derived"
    )


def quality_issues_for_claim(claim: DealClaim, evidence: list[EvidenceItem], status: str) -> list[str]:
    issues: list[str] = []
    if len(claim.text.split()) < 7:
        issues.append("Claim is too terse to verify precisely.")
    if not any(char.isdigit() for char in claim.text) and claim.category in {"growth", "market", "customer_roi", "financials", "pricing", "fundraising"}:
        issues.append("Claim lacks a concrete metric or threshold.")
    if status == "weak" and evidence and all(item.sourceIndependence == "founder_supplied" for item in evidence):
        issues.append("Only founder-supplied evidence was found.")
    if status == "missing":
        issues.append("No matching evidence was found in the uploaded packet.")
    if status == "contradicted":
        issues.append("Contradictory evidence should be resolved before IC.")
    if evidence and any(item.stance in {"supports", "contradicts"} and not has_audit_citation(item) for item in evidence):
        issues.append("Evidence is missing an exact quote-backed citation.")
    if evidence and not any(item.sourceIndependence == "third_party" for item in evidence):
        issues.append("No third-party validation is attached.")
    return issues


def quality_score_for_claim(claim: DealClaim, evidence: list[EvidenceItem], status: str, issues: list[str]) -> int:
    base = {"supported": 82, "weak": 55, "missing": 24, "contradicted": 12}[status]
    if any(item.sourceIndependence == "third_party" and item.stance == "supports" for item in evidence):
        base += 10
    if any(item.sourceIndependence == "internal" and item.stance == "supports" for item in evidence):
        base += 5
    if any(item.sourceIndependence == "founder_supplied" for item in evidence) and status != "supported":
        base -= 6
    if any(item.stance == "contradicts" for item in evidence):
        base -= 18
    base -= min(24, len(issues) * 6)
    if claim.importance == "high" and status != "supported":
        base -= 4
    return max(0, min(100, round(base)))


def verification_need_for_claim(claim: DealClaim, evidence: list[EvidenceItem], status: str) -> str:
    if status == "supported":
        return "Keep the citation attached and confirm no newer contradictory source exists."
    if status == "contradicted":
        return "Ask the company to reconcile the contradiction with source-level documentation."
    if any(item.sourceIndependence == "founder_supplied" for item in evidence):
        return "Request independent or customer-level evidence for this claim."
    if claim.category in {"growth", "financials", "pricing", "fundraising"}:
        return "Request financial backup with period, cohort, and calculation detail."
    if claim.category == "customer_roi":
        return "Request customer references or cohort methodology supporting the ROI claim."
    if claim.category == "product":
        return "Request product proof such as demos, usage logs, implementation detail, or customer validation."
    if claim.category == "team":
        return "Request background evidence for team claims and role-specific execution proof."
    if claim.category == "go_to_market":
        return "Request pipeline, conversion, channel, and cohort evidence for go-to-market claims."
    if claim.category == "legal":
        return "Request legal, IP, contract, or regulatory documentation that directly validates the claim."
    if claim.category == "operations":
        return "Request operating metrics, vendor documentation, or process evidence for this claim."
    return "Request source-level evidence that directly validates the claim."


def decision_impact_for_claim(claim: DealClaim) -> str:
    if claim.importance == "high" or claim.category in {"growth", "financials", "compliance", "customer_roi", "fundraising", "legal"}:
        return "high"
    if claim.category in {"market", "competition", "pricing", "retention", "product", "go_to_market", "operations"}:
        return "medium"
    return "low"


def memo_to_markdown(memo: RiskMemo, score: ScoreSummary | None = None) -> str:
    sections = [
        f"# {MEMO_TITLE}: {memo.company}",
        "",
        f"**Overall grade:** {memo.overallGrade.upper()}",
    ]
    if score:
        sections.extend(
            [
                f"**IC readiness score:** {score.overall}/100",
                "",
                "## Score Drivers",
                markdown_bullets(score.drivers),
            ]
        )
    if memo.executiveSummary:
        sections.extend(["", "## Executive Summary", memo.executiveSummary])
    if memo.thesisAssessment:
        sections.extend(["", "## Thesis Assessment", memo.thesisAssessment])
    if memo.decisionDrivers:
        sections.extend(["", "## Decision Drivers", markdown_bullets(memo.decisionDrivers)])
    if memo.evidenceMap:
        sections.extend(["", "## Evidence Map", markdown_bullets(memo.evidenceMap)])
    sections.extend(
        [
            "",
            "## Investment Question",
            memo.investmentQuestion,
            "",
            "## What We Can Trust",
            markdown_bullets(memo.keyStrengths),
            "",
            "## What Remains Unproven",
            markdown_bullets(memo.keyRisks or memo.materialRisks),
            "",
            "## What Would Change the Decision",
            markdown_bullets(memo.nextDiligenceRequests or memo.followUpQuestions),
            "",
            "## Recommendation",
            memo.icRecommendation,
            "",
        ]
    )
    return "\n".join(sections)


def markdown_bullets(items: list[str]) -> str:
    if not items:
        return "- None."
    return "\n".join(f"- {item}" for item in items)
