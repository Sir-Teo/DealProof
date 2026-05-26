import type { ClaimStatus, DealClaim, EvidenceItem, QualityReview, RiskMemo, ScoreSummary } from "@/lib/types";
import { UI_COPY } from "@/lib/app-config";

const statusWeights: Record<ClaimStatus, number> = {
  supported: 88,
  weak: 55,
  missing: 24,
  contradicted: 8
};

const importanceWeights: Record<DealClaim["importance"], number> = {
  high: 1.5,
  medium: 1,
  low: 0.7
};

const decisionImpactWeights: Record<DealClaim["decisionImpact"], number> = {
  high: 1.25,
  medium: 1,
  low: 0.85
};

const highRiskCategories = new Set<DealClaim["category"]>([
  "customer_roi",
  "competition",
  "market",
  "growth",
  "financials",
  "retention",
  "compliance",
  "fundraising",
  "legal"
]);

export function scoreClaims(claims: DealClaim[], evidence: EvidenceItem[] = [], qualityReview?: QualityReview | null): ScoreSummary {
  claims = claims.filter((claim) => effectiveDisposition(claim) !== "ignored");
  const counts = countStatuses(claims);
  if (!claims.length) {
    return { overall: 0, grade: "red", counts, drivers: ["No diligence claims were scored."] };
  }

  const evidenceByClaim = new Map<string, EvidenceItem[]>();
  for (const item of evidence) {
    evidenceByClaim.set(item.claimId, [...(evidenceByClaim.get(item.claimId) ?? []), item]);
  }

  const weighted = claims.reduce(
    (acc, claim) => {
      const weight = importanceWeights[claim.importance] * decisionImpactWeights[claim.decisionImpact];
      return {
        score: acc.score + claimReadinessScore(claim, evidenceByClaim.get(claim.id) ?? []) * weight,
        weight: acc.weight + weight
      };
    },
    { score: 0, weight: 0 }
  );

  const rawScore = Math.round(weighted.score / weighted.weight);
  const drivers: string[] = [];
  let score = rawScore;

  const hasThirdParty = evidence.some((item) => item.sourceIndependence === "third_party");
  if (evidence.length && !hasThirdParty) {
    score -= 8;
    drivers.push("No third-party validation is attached; score is capped below green.");
  }

  if (qualityReview) {
    if (qualityReview.memoReadinessScore < 60) {
      score -= 8;
      drivers.push(`Memo readiness is low at ${qualityReview.memoReadinessScore}/100.`);
    }
    if (qualityReview.globalWarnings.length) {
      score -= Math.min(12, qualityReview.globalWarnings.length * 4);
      drivers.push(...qualityReview.globalWarnings.slice(0, 2));
    }
  }

  let scoreCap = 100;
  const unresolved = claims.filter((claim) => effectiveDisposition(claim) !== "verified");
  if (unresolved.some((claim) => claim.status === "contradicted" && claim.decisionImpact === "high")) {
    scoreCap = Math.min(scoreCap, 59);
    drivers.push("Unresolved high-impact contradiction blocks IC readiness.");
  }
  if (unresolved.some((claim) => claim.status === "missing" && claim.importance === "high")) {
    scoreCap = Math.min(scoreCap, 84);
    drivers.push("High-importance missing evidence prevents a green score.");
  }
  if (evidence.length && !hasThirdParty) {
    scoreCap = Math.min(scoreCap, 84);
  }

  const overall = clampScore(Math.min(score, scoreCap));
  return {
    overall,
    counts,
    grade: overall >= 85 ? "green" : overall >= 60 ? "yellow" : "red",
    drivers: uniqueItems(drivers.length ? drivers : ["Claim quality, materiality, and evidence support are strong enough for this band."]).slice(0, 4)
  };
}

function countStatuses(claims: DealClaim[]) {
  return claims.reduce<Record<ClaimStatus, number>>(
    (acc, claim) => {
      acc[claim.status] += 1;
      return acc;
    },
    { supported: 0, weak: 0, contradicted: 0, missing: 0 }
  );
}

function claimReadinessScore(claim: DealClaim, evidence: EvidenceItem[]) {
  const qualityScore = claim.qualityScore > 0 ? claim.qualityScore : statusWeights[claim.status];
  let score = Math.round(statusWeights[claim.status] * 0.35 + qualityScore * 0.65);
  const disposition = effectiveDisposition(claim);
  if (disposition === "verified") {
    score = Math.max(score, 90);
  } else if (disposition === "needs_evidence" || disposition === "ic_blocker") {
    score -= 12;
  }
  if (claim.status !== "supported" && highRiskCategories.has(claim.category)) score -= 6;
  if (evidence.some((item) => item.sourceIndependence === "third_party" && item.stance === "supports")) {
    score += 6;
  } else if (evidence.some((item) => ["supports", "partially_supports"].includes(item.stance) && item.sourceIndependence === "founder_supplied")) {
    score -= 8;
  }
  if (evidence.length && !evidence.some((item) => item.sourceIndependence === "third_party")) score -= 4;
  if (evidence.some((item) => item.stance === "contradicts")) score -= 12;
  return clampScore(score);
}

export function effectiveDisposition(claim: DealClaim) {
  if (claim.reviewerDisposition && claim.reviewerDisposition !== "unreviewed") return claim.reviewerDisposition;
  if (claim.reviewerStatus === "verified") return "verified";
  if (claim.reviewerStatus === "needs_evidence") return "needs_evidence";
  return "unreviewed";
}

function clampScore(score: number) {
  return Math.max(0, Math.min(100, Math.round(score)));
}

function uniqueItems(items: string[]) {
  return Array.from(new Set(items.filter(Boolean)));
}

export function evidenceForClaim(claimId: string, evidence: EvidenceItem[]) {
  return evidence.filter((item) => item.claimId === claimId);
}

export function generateMemoMarkdown(memo: RiskMemo, score?: ScoreSummary | null) {
  const sections = [
    `# ${UI_COPY.appName} Red Team Memo: ${memo.company}`,
    "",
    `**Overall grade:** ${memo.overallGrade.toUpperCase()}`
  ];
  if (score) {
    sections.push(`**IC readiness score:** ${score.overall}/100`, "", "## Score Drivers", markdownBullets(score.drivers));
  }
  if (memo.executiveSummary) sections.push("", "## Executive Summary", memo.executiveSummary);
  if (memo.thesisAssessment) sections.push("", "## Thesis Assessment", memo.thesisAssessment);
  if (memo.decisionDrivers?.length) sections.push("", "## Decision Drivers", markdownBullets(memo.decisionDrivers));
  if (memo.evidenceMap?.length) sections.push("", "## Evidence Map", markdownBullets(memo.evidenceMap));
  sections.push(
    "",
    "## Investment Question",
    memo.investmentQuestion,
    "",
    "## What We Can Trust",
    markdownBullets(memo.keyStrengths),
    "",
    "## What Remains Unproven",
    markdownBullets(memo.keyRisks?.length ? memo.keyRisks : memo.materialRisks),
    "",
    "## What Would Change the Decision",
    markdownBullets(memo.nextDiligenceRequests?.length ? memo.nextDiligenceRequests : memo.followUpQuestions),
    "",
    "## Recommendation",
    memo.icRecommendation,
    ""
  );
  return sections.join("\n");
}

function markdownBullets(items: string[]) {
  return items.length ? items.map((item) => `- ${item}`).join("\n") : "- None.";
}

export function findRelevantClaims(question: string, claims: DealClaim[]) {
  const normalized = question.toLowerCase();
  const categoryHints = claims.filter((claim) => {
    const category = claim.category.replace("_", " ");
    return normalized.includes(category) || claim.text.toLowerCase().split(/\W+/).some((word) => word.length > 5 && normalized.includes(word));
  });

  return categoryHints.length > 0 ? categoryHints.slice(0, 3) : claims.filter((claim) => claim.importance === "high").slice(0, 3);
}
