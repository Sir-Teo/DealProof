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
    reviewerDisposition: "unreviewed",
    reviewerNotes: "",
    statusReason: "Supported by financial snapshot.",
    resolutionRequest: ""
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
    reviewerDisposition: "unreviewed",
    reviewerNotes: "",
    statusReason: "Partial support exists.",
    resolutionRequest: "Provide customer cohort data."
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
    reviewerDisposition: "unreviewed",
    reviewerNotes: "",
    statusReason: "Contradictory evidence conflicts with this claim.",
    resolutionRequest: "Reconcile competitor evidence."
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
    reviewerDisposition: "unreviewed",
    reviewerNotes: "",
    statusReason: "No support was found.",
    resolutionRequest: "Provide bottom-up market evidence."
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
  it("scores the demo packet as a red IC readiness case", () => {
    const result = scoreClaims(claims);

    expect(result.grade).toBe("red");
    expect(result.counts.supported).toBe(1);
    expect(result.counts.weak).toBe(1);
    expect(result.counts.contradicted).toBe(1);
    expect(result.counts.missing).toBe(1);
  });

  it("caps high-impact contradictions at red", () => {
    const result = scoreClaims(claims.map((claim) => (claim.id === "claim-03" ? { ...claim, decisionImpact: "high" } : claim)), evidence);

    expect(result.grade).toBe("red");
    expect(result.overall).toBeLessThanOrEqual(59);
    expect(result.drivers).toContain("Unresolved high-impact contradiction blocks IC readiness.");
  });

  it("caps high-importance missing claims below green", () => {
    const result = scoreClaims(
      [
        { ...claims[0], status: "supported", qualityScore: 96 },
        { ...claims[3], status: "missing", qualityScore: 20, importance: "high", decisionImpact: "medium" }
      ],
      evidence
    );

    expect(result.grade).not.toBe("green");
    expect(result.overall).toBeLessThanOrEqual(84);
    expect(result.drivers).toContain("High-importance missing evidence prevents a green score.");
  });

  it("allows independently supported high-quality claims to score green", () => {
    const greenClaims = [
      { ...claims[0], status: "supported", qualityScore: 94, decisionImpact: "high" },
      { ...claims[1], id: "claim-02", status: "supported", qualityScore: 91, decisionImpact: "medium" }
    ] satisfies DealClaim[];
    const greenEvidence = greenClaims.map((claim, index) => ({
      id: `ev-green-${index}`,
      claimId: claim.id,
      title: "Third-party support",
      sourceType: "uploaded" as const,
      citation: "support.csv",
      snippet: "Supported claim.",
      stance: "supports" as const,
      reliability: "high" as const,
      sourceIndependence: "third_party" as const,
      relevanceScore: 0.9,
      quoteSpan: "Supported claim."
    }));

    const result = scoreClaims(greenClaims, greenEvidence);

    expect(result.grade).toBe("green");
    expect(result.overall).toBeGreaterThanOrEqual(85);
  });

  it("does not let founder-only support score green", () => {
    const result = scoreClaims(
      [{ ...claims[0], status: "supported", qualityScore: 92 }],
      [{
        id: "ev-founder",
        claimId: "claim-01",
        title: "Founder deck",
        sourceType: "uploaded",
        citation: "deck.pdf",
        snippet: "ARR grew.",
        stance: "supports",
        reliability: "high",
        sourceIndependence: "founder_supplied",
        relevanceScore: 0.82,
        quoteSpan: "ARR grew."
      }]
    );

    expect(result.grade).not.toBe("green");
    expect(result.overall).toBeLessThanOrEqual(84);
    expect(result.drivers).toContain("No third-party validation is attached; score is capped below green.");
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
