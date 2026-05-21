import { demoAnalysis } from "@/lib/demo-data";
import { evidenceForClaim, findRelevantClaims } from "@/lib/scoring";
import type { ChatAnswer } from "@/lib/types";

export function answerFromFixtures(question: string): ChatAnswer {
  const claims = findRelevantClaims(question, demoAnalysis.claims);
  const citations = claims.flatMap((claim) =>
    evidenceForClaim(claim.id, demoAnalysis.evidence).map((item) => item.citation)
  );

  const weakClaims = claims.filter((claim) => claim.status !== "supported");
  const answer =
    weakClaims.length > 0
      ? `The evidence is not strong enough to underwrite this without follow-up. ${weakClaims
          .map((claim) => `${claim.text} is ${claim.status}: ${claim.riskRationale}`)
          .join(" ")}`
      : `The available packet supports this directionally. ${claims
          .map((claim) => `${claim.text}: ${claim.riskRationale}`)
          .join(" ")}`;

  return {
    answer,
    citations: Array.from(new Set(citations)).slice(0, 4),
    confidence: weakClaims.length > 0 ? "medium" : "high"
  };
}
