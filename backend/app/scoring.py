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
    if "contradicts" in stances:
        status = "contradicted"
    elif "supports" in stances and "partially_supports" not in stances:
        status = "supported"
    elif "supports" in stances or "partially_supports" in stances:
        status = "weak"
    else:
        status = "missing"

    rationale = claim.riskRationale or {
        "supported": "The claim is supported by cited material supplied for this deal.",
        "weak": "The claim has partial support, but methodology, cohort, or external validation is incomplete.",
        "contradicted": "The claim conflicts with cited material or supplied source evidence.",
        "missing": "No reliable uploaded or supplied-URL evidence supports this claim.",
    }[status]
    return claim.model_copy(update={"status": status, "riskRationale": rationale})


def memo_to_markdown(memo: RiskMemo) -> str:
    return f"""# {MEMO_TITLE}: {memo.company}

**Overall grade:** {memo.overallGrade.upper()}

## Investment Question
{memo.investmentQuestion}

## Key Strengths
{chr(10).join(f"- {item}" for item in memo.keyStrengths)}

## Material Risks
{chr(10).join(f"- {item}" for item in memo.materialRisks)}

## Questions Before IC
{chr(10).join(f"- {item}" for item in memo.followUpQuestions)}

## Recommendation
{memo.icRecommendation}
"""
