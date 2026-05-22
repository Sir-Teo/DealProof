from __future__ import annotations

from collections import Counter

from .models import DealClaim, EvidenceItem, RiskMemo
from .config import MEMO_TITLE

STATUS_SCORE = {"supported": 100, "weak": 62, "missing": 38, "contradicted": 18}
IMPORTANCE_WEIGHT = {"high": 1.4, "medium": 1.0, "low": 0.7}


def score_claims(claims: list[DealClaim]) -> tuple[int, str, dict[str, int]]:
    if not claims:
      return 0, "red", {"supported": 0, "weak": 0, "contradicted": 0, "missing": 0}
    score = sum(STATUS_SCORE[c.status] * IMPORTANCE_WEIGHT[c.importance] for c in claims)
    weight = sum(IMPORTANCE_WEIGHT[c.importance] for c in claims)
    overall = round(score / weight)
    grade = "green" if overall >= 78 else "yellow" if overall >= 48 else "red"
    counts = Counter(c.status for c in claims)
    return overall, grade, {key: counts.get(key, 0) for key in ["supported", "weak", "contradicted", "missing"]}


def apply_rule_based_status(claim: DealClaim, evidence: list[EvidenceItem]) -> DealClaim:
    stances = {item.stance for item in evidence}
    independent_support = any(item.stance == "supports" and item.sourceIndependence != "founder_supplied" for item in evidence)
    founder_only_support = any(item.stance in {"supports", "partially_supports"} for item in evidence) and not independent_support
    if "contradicts" in stances:
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
    rationale = {
        "supported": "The claim is supported by cited material supplied for this deal.",
        "weak": "The claim has partial support, but methodology, cohort, or external validation is incomplete.",
        "contradicted": "The claim conflicts with cited material or supplied source evidence.",
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


def quality_issues_for_claim(claim: DealClaim, evidence: list[EvidenceItem], status: str) -> list[str]:
    issues: list[str] = []
    if len(claim.text.split()) < 7:
        issues.append("Claim is too terse to verify precisely.")
    if not any(char.isdigit() for char in claim.text) and claim.category in {"growth", "market", "customer_roi", "financials", "pricing"}:
        issues.append("Claim lacks a concrete metric or threshold.")
    if status == "weak" and evidence and all(item.sourceIndependence == "founder_supplied" for item in evidence):
        issues.append("Only founder-supplied evidence was found.")
    if status == "missing":
        issues.append("No matching evidence was found in the uploaded packet.")
    if status == "contradicted":
        issues.append("Contradictory evidence should be resolved before IC.")
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
    if claim.category in {"growth", "financials", "pricing"}:
        return "Request financial backup with period, cohort, and calculation detail."
    if claim.category == "customer_roi":
        return "Request customer references or cohort methodology supporting the ROI claim."
    return "Request source-level evidence that directly validates the claim."


def decision_impact_for_claim(claim: DealClaim) -> str:
    if claim.importance == "high" or claim.category in {"growth", "financials", "compliance", "customer_roi"}:
        return "high"
    if claim.category in {"market", "competition", "pricing", "retention"}:
        return "medium"
    return "low"


def memo_to_markdown(memo: RiskMemo) -> str:
    return f"""# {MEMO_TITLE}: {memo.company}

**Overall grade:** {memo.overallGrade.upper()}

## Investment Question
{memo.investmentQuestion}

## What We Can Trust
{chr(10).join(f"- {item}" for item in memo.keyStrengths)}

## What Remains Unproven
{chr(10).join(f"- {item}" for item in memo.materialRisks)}

## What Would Change the Decision
{chr(10).join(f"- {item}" for item in memo.followUpQuestions)}

## Recommendation
{memo.icRecommendation}
"""
