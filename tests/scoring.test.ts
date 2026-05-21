import { describe, expect, it } from "vitest";
import { demoAnalysis } from "@/lib/demo-data";
import { evidenceForClaim, generateMemoMarkdown, scoreClaims } from "@/lib/scoring";

describe("DealProof scoring", () => {
  it("scores the demo packet as a yellow risk deal", () => {
    const result = scoreClaims(demoAnalysis.claims);

    expect(result.grade).toBe("yellow");
    expect(result.counts.supported).toBe(5);
    expect(result.counts.weak).toBe(3);
    expect(result.counts.contradicted).toBe(1);
    expect(result.counts.missing).toBe(1);
  });

  it("returns evidence for a selected claim", () => {
    const evidence = evidenceForClaim("claim-04", demoAnalysis.evidence);

    expect(evidence).toHaveLength(1);
    expect(evidence[0].stance).toBe("contradicts");
  });

  it("generates a partner-ready markdown memo", () => {
    const markdown = generateMemoMarkdown(demoAnalysis.memo);

    expect(markdown).toContain("# DealProof Red Team Memo: CaviClear AI");
    expect(markdown).toContain("## Questions Before IC");
    expect(markdown).toMatchSnapshot();
  });
});
