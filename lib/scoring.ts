import type { ClaimStatus, DealClaim, EvidenceItem, RiskMemo } from "@/lib/types";
import { UI_COPY } from "@/lib/app-config";

const statusWeights: Record<ClaimStatus, number> = {
  supported: 100,
  weak: 62,
  missing: 38,
  contradicted: 18
};

const importanceWeights: Record<DealClaim["importance"], number> = {
  high: 1.4,
  medium: 1,
  low: 0.7
};

export function scoreClaims(claims: DealClaim[]) {
  const weighted = claims.reduce(
    (acc, claim) => {
      const weight = importanceWeights[claim.importance];
      return {
        score: acc.score + statusWeights[claim.status] * weight,
        weight: acc.weight + weight
      };
    },
    { score: 0, weight: 0 }
  );

  const overall = Math.round(weighted.score / weighted.weight);
  const counts = claims.reduce<Record<ClaimStatus, number>>(
    (acc, claim) => {
      acc[claim.status] += 1;
      return acc;
    },
    { supported: 0, weak: 0, contradicted: 0, missing: 0 }
  );

  return {
    overall,
    counts,
    grade: overall >= 78 ? "green" : overall >= 48 ? "yellow" : "red"
  } as const;
}

export function evidenceForClaim(claimId: string, evidence: EvidenceItem[]) {
  return evidence.filter((item) => item.claimId === claimId);
}

export function generateMemoMarkdown(memo: RiskMemo) {
  return `# ${UI_COPY.appName} Red Team Memo: ${memo.company}

**Overall grade:** ${memo.overallGrade.toUpperCase()}

## Investment Question
${memo.investmentQuestion}

## Key Strengths
${memo.keyStrengths.map((item) => `- ${item}`).join("\n")}

## Material Risks
${memo.materialRisks.map((item) => `- ${item}`).join("\n")}

## Questions Before IC
${memo.followUpQuestions.map((item) => `- ${item}`).join("\n")}

## Recommendation
${memo.icRecommendation}
`;
}

export function findRelevantClaims(question: string, claims: DealClaim[]) {
  const normalized = question.toLowerCase();
  const categoryHints = claims.filter((claim) => {
    const category = claim.category.replace("_", " ");
    return normalized.includes(category) || claim.text.toLowerCase().split(/\W+/).some((word) => word.length > 5 && normalized.includes(word));
  });

  return categoryHints.length > 0 ? categoryHints.slice(0, 3) : claims.filter((claim) => claim.importance === "high").slice(0, 3);
}
