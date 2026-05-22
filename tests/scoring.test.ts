import { describe, expect, it } from "vitest";
import { deriveIcReadiness } from "@/lib/readiness";
import { evidenceForClaim, generateMemoMarkdown, scoreClaims } from "@/lib/scoring";
import type { DealClaim, EvidenceItem, RiskMemo } from "@/lib/types";

const claims: DealClaim[] = [
  {
    id: "claim-01",
    text: "ARR grew from $82k to $235k.",
    category: "financials",
    sourceMaterial: "financials.csv",
    sourceSnippet: "ARR,82000,235000",
    importance: "high",
    status: "supported",
    riskRationale: "Supported by financial snapshot.",
    confidence: "high",
    qualityScore: 92,
    qualityIssues: [],
    verificationNeed: "Keep citation attached.",
    decisionImpact: "high",
    reviewerStatus: "unreviewed",
    reviewerNotes: ""
  },
  {
    id: "claim-02",
    text: "Clinics save 18 hours per week.",
    category: "customer_roi",
    sourceMaterial: "deck.pdf",
    sourceSnippet: "recover 18 hours",
    importance: "high",
    status: "weak",
    riskRationale: "Methodology is not supplied.",
    confidence: "medium",
    qualityScore: 52,
    qualityIssues: ["No customer-level methodology."],
    verificationNeed: "Request customer cohort data.",
    decisionImpact: "high",
    reviewerStatus: "unreviewed",
    reviewerNotes: ""
  },
  {
    id: "claim-03",
    text: "No competitors exist.",
    category: "competition",
    sourceMaterial: "deck.pdf",
    sourceSnippet: "No direct competitor",
    importance: "medium",
    status: "contradicted",
    riskRationale: "Supplied source conflicts with this claim.",
    confidence: "high",
    qualityScore: 16,
    qualityIssues: ["Contradictory evidence should be resolved before IC."],
    verificationNeed: "Reconcile the contradiction.",
    decisionImpact: "medium",
    reviewerStatus: "unreviewed",
    reviewerNotes: ""
  },
  {
    id: "claim-04",
    text: "The market is $6B.",
    category: "market",
    sourceMaterial: "deck.pdf",
    sourceSnippet: "$6B opportunity",
    importance: "high",
    status: "missing",
    riskRationale: "No source is supplied.",
    confidence: "low",
    qualityScore: 20,
    qualityIssues: ["No matching evidence was found."],
    verificationNeed: "Request bottom-up market evidence.",
    decisionImpact: "high",
    reviewerStatus: "unreviewed",
    reviewerNotes: ""
  }
];

const evidence: EvidenceItem[] = [
  {
    id: "ev-01",
    claimId: "claim-03",
    title: "Competitor source",
    sourceType: "uploaded",
    citation: "source.txt",
    snippet: "Competitor exists.",
    stance: "contradicts",
    reliability: "medium",
    sourceIndependence: "third_party",
    relevanceScore: 0.84,
    quoteSpan: "source.txt"
  }
];

const memo: RiskMemo = {
  company: "CaviClear AI",
  overallGrade: "yellow",
  investmentQuestion: "Is this credible enough for IC?",
  keyStrengths: ["ARR support exists."],
  materialRisks: ["ROI methodology is missing."],
  followUpQuestions: ["Show customer cohort data."],
  icRecommendation: "Proceed only after validating weak claims.",
  executiveSummary: "CaviClear is a yellow diligence case with mixed support.",
  thesisAssessment: "The core thesis needs stronger customer proof before IC.",
  evidenceMap: ["claim-01: supported by financials.csv."],
  keyRisks: ["ROI methodology is missing."],
  nextDiligenceRequests: ["Show customer cohort data."],
  decisionDrivers: ["Resolve high-importance weak claims."]
};

describe("DealProof scoring", () => {
  it("scores the demo packet as a yellow risk deal", () => {
    const result = scoreClaims(claims);

    expect(result.grade).toBe("yellow");
    expect(result.counts.supported).toBe(1);
    expect(result.counts.weak).toBe(1);
    expect(result.counts.contradicted).toBe(1);
    expect(result.counts.missing).toBe(1);
  });

  it("returns evidence for a selected claim", () => {
    const selectedEvidence = evidenceForClaim("claim-03", evidence);

    expect(selectedEvidence).toHaveLength(1);
    expect(selectedEvidence[0].stance).toBe("contradicts");
  });

  it("generates a partner-ready markdown memo", () => {
    const markdown = generateMemoMarkdown(memo);

    expect(markdown).toContain("# DealProof Red Team Memo: CaviClear AI");
    expect(markdown).toContain("## Executive Summary");
    expect(markdown).toContain("## Evidence Map");
    expect(markdown).toContain("## What Would Change the Decision");
    expect(markdown).toMatchSnapshot();
  });

  it("treats high-impact contradicted claims as IC blockers", () => {
    const readiness = deriveIcReadiness(
      claims.map((claim) => (claim.id === "claim-03" ? { ...claim, importance: "high", decisionImpact: "high" } : claim)),
      evidence,
      null
    );

    expect(readiness.grade).toBe("blocked");
    expect(readiness.blockers.map((item) => item.claim.id)).toContain("claim-03");
    expect(readiness.topGatingIssue).toBe("No competitors exist.");
  });

  it("moves reviewer-verified claims into resolved readiness items", () => {
    const readiness = deriveIcReadiness(
      claims.map((claim) => (claim.id === "claim-02" ? { ...claim, reviewerStatus: "verified" } : claim)),
      evidence,
      null
    );

    expect(readiness.resolved.map((item) => item.claim.id)).toContain("claim-02");
    expect(readiness.blockers.map((item) => item.claim.id)).not.toContain("claim-02");
  });

  it("flags claims with no independent evidence as evidence requests", () => {
    const readiness = deriveIcReadiness(
      [
        {
          ...claims[0],
          id: "claim-05",
          text: "Customer reference confirms ROI.",
          importance: "medium",
          status: "supported",
          decisionImpact: "medium"
        }
      ],
      [
        {
          id: "ev-05",
          claimId: "claim-05",
          title: "Founder source",
          sourceType: "uploaded",
          citation: "deck.pdf",
          snippet: "ROI is confirmed.",
          stance: "supports",
          reliability: "medium",
          sourceIndependence: "founder_supplied",
          relevanceScore: 0.77
        }
      ],
      null
    );

    expect(readiness.evidenceRequests).toHaveLength(1);
    expect(readiness.evidenceRequests[0].reason).toBe("No third-party support is attached.");
  });
});
