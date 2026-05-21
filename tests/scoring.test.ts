import { describe, expect, it } from "vitest";
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
    riskRationale: "Supported by financial snapshot."
  },
  {
    id: "claim-02",
    text: "Clinics save 18 hours per week.",
    category: "customer_roi",
    sourceMaterial: "deck.pdf",
    sourceSnippet: "recover 18 hours",
    importance: "high",
    status: "weak",
    riskRationale: "Methodology is not supplied."
  },
  {
    id: "claim-03",
    text: "No competitors exist.",
    category: "competition",
    sourceMaterial: "deck.pdf",
    sourceSnippet: "No direct competitor",
    importance: "medium",
    status: "contradicted",
    riskRationale: "Supplied source conflicts with this claim."
  },
  {
    id: "claim-04",
    text: "The market is $6B.",
    category: "market",
    sourceMaterial: "deck.pdf",
    sourceSnippet: "$6B opportunity",
    importance: "high",
    status: "missing",
    riskRationale: "No source is supplied."
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
    reliability: "medium"
  }
];

const memo: RiskMemo = {
  company: "CaviClear AI",
  overallGrade: "yellow",
  investmentQuestion: "Is this credible enough for IC?",
  keyStrengths: ["ARR support exists."],
  materialRisks: ["ROI methodology is missing."],
  followUpQuestions: ["Show customer cohort data."],
  icRecommendation: "Proceed only after validating weak claims."
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
    expect(markdown).toContain("## Questions Before IC");
    expect(markdown).toMatchSnapshot();
  });
});
