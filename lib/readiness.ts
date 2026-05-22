import type { ClaimStatus, DealClaim, EvidenceItem, QualityReview } from "@/lib/types";

export type ReadinessGrade = "ready" | "conditional" | "blocked";
export type ReadinessItemKind = "critical" | "evidence_request" | "resolved";

export type ReadinessItem = {
  claim: DealClaim;
  kind: ReadinessItemKind;
  reason: string;
  evidenceCount: number;
  independentEvidenceCount: number;
};

export type ReadinessSummary = {
  score: number;
  grade: ReadinessGrade;
  blockers: ReadinessItem[];
  evidenceRequests: ReadinessItem[];
  resolved: ReadinessItem[];
  blockerCount: number;
  topGatingIssue: string;
};

const riskyStatuses = new Set<ClaimStatus>(["weak", "missing", "contradicted"]);

export function deriveIcReadiness(claims: DealClaim[], evidence: EvidenceItem[], qualityReview?: QualityReview | null): ReadinessSummary {
  const evidenceByClaim = new Map<string, EvidenceItem[]>();
  for (const item of evidence) {
    evidenceByClaim.set(item.claimId, [...(evidenceByClaim.get(item.claimId) ?? []), item]);
  }

  const items = claims.map((claim) => toReadinessItem(claim, evidenceByClaim.get(claim.id) ?? []));
  const resolved = items.filter((item) => item.claim.reviewerStatus === "verified");
  const blockers = items
    .filter((item) => item.claim.reviewerStatus !== "verified")
    .filter((item) => item.claim.importance === "high" && riskyStatuses.has(item.claim.status))
    .sort(compareReadinessItems);
  const evidenceRequests = items
    .filter((item) => item.claim.reviewerStatus !== "verified")
    .filter((item) => item.claim.reviewerStatus === "needs_evidence" || item.independentEvidenceCount === 0)
    .filter((item) => !blockers.some((blocker) => blocker.claim.id === item.claim.id))
    .sort(compareReadinessItems);

  const qualityScore = qualityReview?.memoReadinessScore;
  const derivedScore = claims.length ? Math.round((resolved.length / claims.length) * 25 + Math.max(0, 75 - blockers.length * 14 - evidenceRequests.length * 6)) : 0;
  const score = clampScore(qualityScore ?? derivedScore);
  const blockerCount = blockers.length + evidenceRequests.length;
  const grade: ReadinessGrade = blockers.length > 0 ? "blocked" : blockerCount > 0 || score < 85 ? "conditional" : "ready";
  const topGatingIssue = blockers[0]?.claim.text ?? evidenceRequests[0]?.claim.text ?? qualityReview?.globalWarnings[0] ?? "No unresolved IC blockers.";

  return {
    score,
    grade,
    blockers,
    evidenceRequests,
    resolved: resolved.sort(compareReadinessItems),
    blockerCount,
    topGatingIssue
  };
}

function toReadinessItem(claim: DealClaim, evidence: EvidenceItem[]): ReadinessItem {
  const independentEvidenceCount = new Set(
    evidence.filter((item) => item.sourceIndependence === "third_party").map((item) => item.sourceName ?? item.citation)
  ).size;
  return {
    claim,
    kind: claim.reviewerStatus === "verified" ? "resolved" : claim.reviewerStatus === "needs_evidence" || independentEvidenceCount === 0 ? "evidence_request" : "critical",
    reason: readinessReason(claim, evidence.length, independentEvidenceCount),
    evidenceCount: evidence.length,
    independentEvidenceCount
  };
}

function readinessReason(claim: DealClaim, evidenceCount: number, independentEvidenceCount: number) {
  if (claim.reviewerStatus === "verified") return "Reviewer marked this claim as verified.";
  if (claim.reviewerStatus === "needs_evidence") return "Reviewer requested more evidence before IC.";
  if (claim.status === "contradicted") return "Contradictory evidence must be reconciled before IC.";
  if (claim.status === "missing") return "No matching support was found for this claim.";
  if (independentEvidenceCount === 0) return "No third-party support is attached.";
  if (claim.status === "weak") return "Support exists, but methodology or source quality is incomplete.";
  return evidenceCount ? "Evidence is attached for review." : "No evidence is attached.";
}

function compareReadinessItems(a: ReadinessItem, b: ReadinessItem) {
  return (
    statusRiskRank(b.claim.status) - statusRiskRank(a.claim.status) ||
    impactRank(b.claim.decisionImpact) - impactRank(a.claim.decisionImpact) ||
    importanceRank(b.claim.importance) - importanceRank(a.claim.importance) ||
    categoryRiskRank(b.claim.category) - categoryRiskRank(a.claim.category) ||
    a.claim.qualityScore - b.claim.qualityScore
  );
}

function statusRiskRank(value: ClaimStatus) {
  if (value === "contradicted") return 4;
  if (value === "missing") return 3;
  if (value === "weak") return 2;
  return 1;
}

function impactRank(value: DealClaim["decisionImpact"]) {
  return value === "high" ? 3 : value === "medium" ? 2 : 1;
}

function importanceRank(value: DealClaim["importance"]) {
  return value === "high" ? 3 : value === "medium" ? 2 : 1;
}

function categoryRiskRank(value: DealClaim["category"]) {
  if (value === "customer_roi") return 5;
  if (value === "competition") return 4;
  if (value === "market") return 3;
  if (value === "growth" || value === "financials" || value === "retention") return 2;
  return 1;
}

function clampScore(score: number) {
  return Math.max(0, Math.min(100, Math.round(score)));
}
