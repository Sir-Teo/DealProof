from __future__ import annotations

from collections import Counter

from .models import DealAnalysis, DealClaim, DiligenceReport, EvidenceItem, QualityReview, RiskMemo, ScoreSummary
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
    claims = active_claims(claims)
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
    unresolved = [claim for claim in claims if effective_disposition(claim) != "verified"]
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
    disposition = effective_disposition(claim)
    if disposition == "verified":
        score = max(score, 90)
    elif disposition in {"needs_evidence", "ic_blocker"}:
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
    if verification_standard_satisfied(claim, evidence):
        score += 4
    elif claim.decisionImpact == "high":
        score -= 6
    return clamp_score(score)


def clamp_score(score: int | float) -> int:
    return max(0, min(100, round(score)))


def unique_items(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def apply_rule_based_status(claim: DealClaim, evidence: list[EvidenceItem]) -> DealClaim:
    stances = {item.stance for item in evidence}
    independent_support = any(
        item.stance == "supports"
        and (
            item.sourceIndependence == "third_party"
            or item.sourceAuthority in {"third_party", "public_filing", "customer"}
        )
        and has_audit_citation(item)
        for item in evidence
    )
    # Internal financial/operating documents (CSV models, data rooms) with matching numbers are authoritative
    # even when same-source, as long as they are not founder-deck narrative (sourceIndependence != founder_supplied).
    internal_doc_support = (
        claim.category in {"financials", "growth", "pricing", "retention", "fundraising", "operations"}
        and any(
            item.sourceIndependence == "internal"
            and item.stance in {"supports", "partially_supports"}
            and has_audit_citation(item)
            for item in evidence
        )
    )
    standard_support = verification_standard_satisfied(claim, evidence)
    founder_only_support = any(item.stance in {"supports", "partially_supports"} for item in evidence) and not independent_support and not internal_doc_support and not standard_support
    contradiction = any(item.stance == "contradicts" and has_audit_citation(item) for item in evidence)
    if contradiction:
        status = "contradicted"
    elif standard_support or independent_support or internal_doc_support:
        status = "supported"
    elif "partially_supports" in stances or founder_only_support:
        status = "weak"
    else:
        status = "missing"

    quality_issues = quality_issues_for_claim(claim, evidence, status)
    quality_score = quality_score_for_claim(claim, evidence, status, quality_issues)
    confidence = "high" if quality_score >= 82 else "medium" if quality_score >= 55 else "low"
    verification_need = verification_need_for_claim(claim, evidence, status)
    status_reason = status_reason_for_claim(claim, evidence, status)
    resolution_request = claim.resolutionRequest or resolution_request_for_claim(claim, status, verification_need)
    has_public_web = any(item.sourceType == "public_web" for item in evidence)
    has_internal_doc = any(item.sourceIndependence == "internal" for item in evidence)
    rationale = {
        "supported": (
            "The claim is supported by quote-backed public web evidence." if has_public_web
            else f"The claim satisfies the {claim.verificationStandard.replace('_', ' ')} verification standard." if standard_support
            else "The claim is supported by internal financial or operating data supplied for this deal." if has_internal_doc
            else "The claim is supported by cited material supplied for this deal."
        ),
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
            "statusReason": status_reason,
            "resolutionRequest": resolution_request,
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


def verification_standard_satisfied(claim: DealClaim, evidence: list[EvidenceItem]) -> bool:
    cited_support = [
        item for item in evidence
        if item.stance == "supports" and has_audit_citation(item)
    ]
    if not cited_support:
        return False
    authorities = {item.sourceAuthority for item in cited_support}
    independence = {item.sourceIndependence for item in cited_support}
    standard = claim.verificationStandard
    if standard == "founder_statement":
        return bool(cited_support)
    if standard == "internal_document":
        return bool({"internal_operating", "customer", "third_party", "public_filing"} & authorities) or "internal" in independence or "third_party" in independence
    if standard == "customer_reference":
        return bool({"customer", "third_party", "public_filing"} & authorities) or "third_party" in independence
    if standard == "third_party":
        return bool({"third_party", "public_filing", "press"} & authorities) or "third_party" in independence
    if standard == "audited_financials":
        return bool({"public_filing", "third_party", "internal_operating"} & authorities)
    if standard == "legal_document":
        return bool({"public_filing", "third_party", "internal_operating"} & authorities)
    if standard == "public_filing":
        return "public_filing" in authorities
    return False


def quote_backed_evidence(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    return [item for item in evidence if has_audit_citation(item)]


def status_reason_for_claim(claim: DealClaim, evidence: list[EvidenceItem], status: str) -> str:
    cited = quote_backed_evidence(evidence)
    source_counts = Counter(item.sourceIndependence for item in evidence)
    source_summary = ", ".join(f"{key.replace('_', ' ')}: {value}" for key, value in sorted(source_counts.items())) or "no source evidence"
    if status == "supported":
        strongest = next((item for item in cited if item.stance == "supports"), None)
        source = strongest.sourceName or strongest.citation if strongest else "a quote-backed source"
        return f"Supported because {source} directly matches the claim; source mix: {source_summary}."
    if status == "contradicted":
        strongest = next((item for item in cited if item.stance == "contradicts"), None)
        source = strongest.sourceName or strongest.citation if strongest else "a quote-backed source"
        return f"Contradicted because {source} conflicts with the claim; source mix: {source_summary}."
    if status == "weak":
        return f"Partial support exists, but it is not enough for IC reliance; source mix: {source_summary}."
    return "No quote-backed uploaded, supplied-url, or public evidence directly supports this claim."


def resolution_request_for_claim(claim: DealClaim, status: str, verification_need: str) -> str:
    if status == "supported":
        return ""
    prefix = {
        "contradicted": "Reconcile this conflicting claim with source-level backup",
        "weak": "Provide stronger source-level evidence",
        "missing": "Provide source-level evidence",
    }.get(status, "Provide source-level evidence")
    return f"{prefix}: {claim.text} ({verification_need})"


def effective_disposition(claim: DealClaim) -> str:
    if claim.reviewerDisposition != "unreviewed":
        return claim.reviewerDisposition
    if claim.reviewerStatus == "verified":
        return "verified"
    if claim.reviewerStatus == "needs_evidence":
        return "needs_evidence"
    return "unreviewed"


def active_claims(claims: list[DealClaim]) -> list[DealClaim]:
    return [claim for claim in claims if effective_disposition(claim) != "ignored"]


def derive_readiness_status(claims: list[DealClaim], evidence: list[EvidenceItem], quality_review: QualityReview | None = None) -> tuple[str, str, list[str]]:
    considered = active_claims(claims)
    evidence_by_claim = {claim.id: [item for item in evidence if item.claimId == claim.id] for claim in considered}
    blockers = [
        claim for claim in considered
        if effective_disposition(claim) == "ic_blocker"
        or (
            effective_disposition(claim) != "verified"
            and claim.status == "contradicted"
            and claim.decisionImpact == "high"
        )
    ]
    missing_high = [
        claim for claim in considered
        if effective_disposition(claim) != "verified"
        and claim.status == "missing"
        and claim.importance == "high"
    ]
    founder_only = [
        claim for claim in considered
        if effective_disposition(claim) != "verified"
        and claim.status == "supported"
        and evidence_by_claim.get(claim.id)
        and not any(item.sourceIndependence == "third_party" for item in evidence_by_claim[claim.id])
    ]
    needs_evidence = [
        claim for claim in considered
        if effective_disposition(claim) == "needs_evidence"
        or (claim.status in {"weak", "missing"} and effective_disposition(claim) != "verified")
    ]
    unresolved = blockers + missing_high + needs_evidence + founder_only
    requests = list(dict.fromkeys(claim.resolutionRequest for claim in unresolved if claim.resolutionRequest))[:12]
    if blockers:
        top = blockers[0]
        return "blocked", f"{top.id}: {top.text} requires resolution before IC.", requests
    if score_claims(considered, evidence, quality_review).grade == "red":
        top = (missing_high or needs_evidence or founder_only or considered[:1])
        issue = f"{top[0].id}: {top[0].text}" if top else "Insufficient evidence for IC."
        return "screen_out", issue, requests
    if missing_high or needs_evidence or founder_only:
        top = (missing_high or needs_evidence or founder_only)[0]
        return "needs_diligence", f"{top.id}: {top.text} needs more evidence.", requests
    return "ic_ready", "No unresolved IC blockers.", requests


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
    if claim.decisionImpact == "high" and not verification_standard_satisfied(claim, evidence):
        issues.append(f"Evidence does not satisfy the {claim.verificationStandard.replace('_', ' ')} verification standard.")
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


def memo_to_markdown(
    memo: RiskMemo,
    score: ScoreSummary | None = None,
    quality_review: QualityReview | None = None,
) -> str:
    grade_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(memo.overallGrade.upper(), "")
    sections = [
        f"# {MEMO_TITLE}: {memo.company}",
        "",
        f"**Overall grade:** {grade_emoji} {memo.overallGrade.upper()}",
    ]
    if score:
        counts = score.counts
        count_line = (
            f"**Claim breakdown:** {counts.get('supported', 0)} supported · "
            f"{counts.get('weak', 0)} weak · "
            f"{counts.get('contradicted', 0)} contradicted · "
            f"{counts.get('missing', 0)} missing"
        )
        sections.extend([
            f"**IC readiness:** {score.overall}/100",
            count_line,
        ])
        if score.drivers:
            sections.extend(["", "## Key Score Drivers", markdown_bullets(score.drivers)])
    if memo.executiveSummary:
        sections.extend(["", "## Executive Summary", memo.executiveSummary])
    if memo.thesisAssessment:
        sections.extend(["", "## Thesis Assessment", memo.thesisAssessment])
    sections.extend([
        "",
        "## Investment Question",
        f"> {memo.investmentQuestion}",
    ])
    if memo.keyStrengths:
        sections.extend(["", "## What We Can Trust", markdown_bullets(memo.keyStrengths)])
    risks = memo.keyRisks or memo.materialRisks
    if risks:
        sections.extend(["", "## Material Risks", markdown_bullets(risks)])
    if memo.decisionDrivers:
        sections.extend(["", "## Decision Drivers", markdown_bullets(memo.decisionDrivers)])
    if memo.evidenceMap:
        sections.extend(["", "## Evidence Map", markdown_bullets(memo.evidenceMap)])
    diligence = (
        quality_review.approvedDiligenceRequests
        if quality_review and quality_review.approvedDiligenceRequests
        else memo.nextDiligenceRequests or memo.followUpQuestions
    )
    if diligence:
        sections.extend(["", "## Next Diligence Requests", markdown_bullets(diligence)])
    sections.extend([
        "",
        "## Recommendation",
        memo.icRecommendation,
        "",
    ])
    return "\n".join(sections)


def report_to_markdown(
    report: DiligenceReport,
    score: ScoreSummary | None = None,
    quality_review: QualityReview | None = None,
) -> str:
    sections = [
        f"# {MEMO_TITLE}: {report.company}",
        "",
        "**Report version:** 2.0",
    ]
    if score:
        counts = score.counts
        sections.extend([
            f"**Overall grade:** {score.grade.upper()}",
            f"**IC readiness:** {score.overall}/100",
            (
                f"**Claim breakdown:** {counts.get('supported', 0)} supported · "
                f"{counts.get('weak', 0)} weak · {counts.get('contradicted', 0)} contradicted · "
                f"{counts.get('missing', 0)} missing"
            ),
        ])
        if score.drivers:
            sections.extend(["", "## Key Score Drivers", markdown_bullets(score.drivers)])
    if quality_review:
        sections.extend([
            "",
            "## Readiness",
            f"- Status: {quality_review.readinessStatus.replace('_', ' ')}",
            f"- Top gating issue: {quality_review.topGatingIssue or 'No unresolved IC blockers.'}",
        ])
    sections.extend([
        "",
        "## Decision Summary",
        report.decisionSummary,
        "",
        "## Investment Thesis",
        report.investmentThesis,
        "",
        "## Key Verified Claims",
        markdown_report_claims(report.keyVerifiedClaims),
        "",
        "## Disputed Claims",
        markdown_report_claims(report.disputedClaims),
        "",
        "## Weak or Missing Claims",
        markdown_report_claims(report.weakOrMissingClaims),
        "",
        "## Evidence Assessment",
        markdown_bullets(report.evidenceAssessment),
        "",
        "## Red Flags",
        markdown_bullets(report.redFlags),
        "",
        "## Diligence Plan",
        markdown_bullets(report.diligencePlan),
        "",
        "## Source Quality",
        markdown_bullets([
            f"{note.materialName}: {note.authority.replace('_', ' ')} / {note.reliability} reliability - {'; '.join(note.limitations)}"
            for note in report.sourceQualityNotes
        ]),
        "",
        "## IC Recommendation",
        report.icRecommendation,
        "",
        "## Appendix: Claim Ledger",
        markdown_report_claims(report.appendixClaimLedger),
        "",
    ])
    return "\n".join(sections)


def markdown_report_claims(items) -> str:
    if not items:
        return "- None."
    return "\n".join(
        f"- {item.claimId} ({item.status}): {item.text}"
        + (f" — {item.rationale}" if item.rationale else "")
        + (f" [evidence: {', '.join(item.evidenceIds)}]" if item.evidenceIds else "")
        for item in items
    )


def markdown_bullets(items: list[str]) -> str:
    if not items:
        return "- None."
    return "\n".join(f"- {item}" for item in items)


def diligence_requests_to_markdown(deal: DealAnalysis) -> str:
    review = deal.qualityReview or QualityReview()
    requests = (deal.report.diligencePlan if deal.report and deal.report.diligencePlan else None) or review.approvedDiligenceRequests or [
        claim.resolutionRequest
        for claim in active_claims(deal.claims)
        if claim.status in {"weak", "missing", "contradicted"} and claim.resolutionRequest
    ]
    sections = [
        f"# DealProof Diligence Requests: {deal.company}",
        "",
        f"**Readiness:** {review.readinessStatus.replace('_', ' ').title()}",
        f"**Top gating issue:** {review.topGatingIssue or 'No unresolved IC blockers.'}",
        "",
        "## Requests",
    ]
    if requests:
        for index, request in enumerate(list(dict.fromkeys(requests)), start=1):
            sections.append(f"{index}. {request}")
    else:
        sections.append("No open diligence requests.")
    sections.extend(["", "## Claim Links"])
    linked = [
        claim
        for claim in active_claims(deal.claims)
        if claim.resolutionRequest and claim.resolutionRequest in requests
    ]
    if linked:
        for claim in linked:
            sections.append(f"- {claim.id} ({claim.status}, {claim.decisionImpact} impact): {claim.text}")
    else:
        sections.append("- None.")
    sections.append("")
    return "\n".join(sections)
