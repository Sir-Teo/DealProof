import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

type ClaimStatus = "supported" | "weak" | "contradicted" | "missing";
type Importance = "high" | "medium" | "low";

type DealClaim = {
  id: string;
  text: string;
  category: string;
  importance: Importance;
  status: ClaimStatus;
  confidence: "high" | "medium" | "low";
  qualityScore: number;
  qualityIssues: string[];
  verificationNeed: string;
  decisionImpact: "high" | "medium" | "low";
};

type EvidenceItem = {
  claimId: string;
  citation: string;
  stance: "supports" | "partially_supports" | "contradicts" | "not_found";
  sourceIndependence: "founder_supplied" | "internal" | "third_party" | "derived";
  quoteSpan?: string | null;
};

type RiskMemo = {
  overallGrade: "green" | "yellow" | "red";
  investmentQuestion: string;
  keyStrengths: string[];
  materialRisks: string[];
  followUpQuestions: string[];
  icRecommendation: string;
  executiveSummary?: string;
  thesisAssessment?: string;
  evidenceMap?: string[];
  keyRisks?: string[];
  nextDiligenceRequests?: string[];
  decisionDrivers?: string[];
};

type QualityReview = {
  memoReadinessScore: number;
  globalWarnings: string[];
  duplicatedClaims: string[];
  lowValueClaims: string[];
  recommendedFollowUpEvidence: string[];
  overconfidenceWarnings: string[];
};

type DealAnalysis = {
  id: string;
  materials: unknown[];
  claims: DealClaim[];
  evidence: EvidenceItem[];
  memo: RiskMemo | null;
  qualityReview: QualityReview | null;
  chatHistory?: ChatTurn[];
};

type ChatTurn = {
  question: string;
  answer: string;
  citations: string[];
  confidence: "high" | "medium" | "low";
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const fixtureDir = path.join(process.cwd(), "backend", "tests", "fixtures", "real_cases");
const largeFixtureDir = path.join(fixtureDir, "large_data_room");

const realCaseFiles = [
  "dm_revenue_flow_pitch.txt",
  "dm_revenue_flow_public_evidence.txt",
  "apple_2025_10k_evidence.txt",
  "real_case_claim_packet.txt"
].map((name) => path.join(fixtureDir, name));

const largeRealCaseFiles = [
  "01_company_overview.txt",
  "02_raise_terms.txt",
  "03_traction_observed.txt",
  "04_financial_model.txt",
  "05_roi_unit_economics.txt",
  "06_market_and_competition.txt",
  "07_founder_call_notes.txt",
  "08_customer_reference_notes.txt",
  "09_risk_and_validation_notes.txt",
  "10_apple_10k_financials.txt",
  "11_apple_10k_supply_chain.txt",
  "12_target_annual_report_retail.txt",
  "13_public_source_index.txt",
  "14_analyst_claim_packet.txt"
].map((name) => path.join(largeFixtureDir, name));

const statusWeights: Record<ClaimStatus, number> = {
  supported: 100,
  weak: 62,
  missing: 38,
  contradicted: 18
};

const importanceWeights: Record<Importance, number> = {
  high: 1.4,
  medium: 1,
  low: 0.7
};

test.describe("deterministic report-quality gates", () => {
  test("seed demo real run produces a decision-grade memo and grounded follow-up answers", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "Report-quality E2E runs on desktop Chromium only.");

    const dealId = await seedDemoAndRunThroughUi(page);
    const deal = await fetchDeal(page, dealId);

    assertReportQuality(deal);
    assertDemoOutputQuality(deal);
    await assertExportedMarkdownParity(page, deal);

    const firstTurn = await askQuestionThroughApi(page, dealId, "Can we trust the ROI and retention claims?");
    expect(firstTurn.answer).toMatch(/evidence|claim|support|trust|insufficient|weak/i);
    expect(firstTurn.citations.length).toBeGreaterThan(0);
    expect(firstTurn.confidence).not.toBe("low");

    const followUp = await askQuestionThroughApi(page, dealId, "What about competition?");
    expect(followUp.answer).toMatch(/compet/i);
    expect(followUp.citations.length).toBeGreaterThan(0);

    const reloaded = await fetchDeal(page, dealId);
    expect(reloaded.chatHistory?.map((turn) => turn.question).slice(-2)).toEqual([
      "Can we trust the ROI and retention claims?",
      "What about competition?"
    ]);
  });

  test("real public-material packet produces a cited, risk-aware memo", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "Report-quality E2E runs on desktop Chromium only.");

    const dealId = await uploadFixturePacketThroughUi(page, realCaseFiles);
    await runAnalysisWithoutStreamError(page);
    const deal = await fetchDeal(page, dealId);

    assertReportQuality(deal);

    const memo = requireMemo(deal);
    const qualityReview = requireQualityReview(deal);
    const risks = memoRisks(memo).join("\n");
    const strengths = memo.keyStrengths.join("\n");

    expect(risks).toContain("no direct or adjacent competitors");
    expect(strengths).not.toContain("no direct or adjacent competitors");
    expect(qualityReview.globalWarnings).toContain("At least one important claim is contradicted by supplied evidence.");
    expect(qualityReview.globalWarnings).toContain("High-importance claims remain weak or missing.");

    await assertExportedMarkdownParity(page, deal);
  });

  test("large data room report keeps off-target public issuer claims out of leading memo sections", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "Report-quality E2E runs on desktop Chromium only.");

    const dealId = await uploadFixturePacketThroughUi(page, largeRealCaseFiles);
    await runAnalysisWithoutStreamError(page);
    const deal = await fetchDeal(page, dealId);

    assertReportQuality(deal);
    expect(deal.materials.length).toBeGreaterThanOrEqual(14);

    const offTargetClaims = deal.claims.filter((claim) => /\b(Apple|Target)\b/i.test(claim.text));
    expect(offTargetClaims.length).toBeGreaterThan(0);

    const memo = requireMemo(deal);
    const leadingMemoText = [
      memo.executiveSummary,
      memo.thesisAssessment,
      memo.decisionDrivers?.join("\n"),
      memo.keyStrengths.join("\n"),
      memoRisks(memo).join("\n"),
      memo.icRecommendation
    ].join("\n");

    expect(leadingMemoText).not.toMatch(/\bApple\b/);
    expect(leadingMemoText).not.toMatch(/\bTarget\b/);
    expect(memoRisks(memo).join("\n")).toContain("100-500x ROI");

    await assertExportedMarkdownParity(page, deal);
  });

  test("reviewer status edits refresh memo grade and quality review deterministically", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "Report-quality E2E runs on desktop Chromium only.");

    const dealId = await uploadFixturePacketThroughUi(page, realCaseFiles);
    await runAnalysisWithoutStreamError(page);
    const before = await fetchDeal(page, dealId);
    assertReportQuality(before);

    const targetClaim = before.claims.find((claim) => claim.status === "contradicted" && /no direct or adjacent competitors/i.test(claim.text));
    expect(targetClaim).toBeTruthy();
    const beforeScore = scoreClaims(before.claims);

    await page.getByRole("button", { name: /Claim ledger/i }).click();
    await page.locator(".claimRow").filter({ hasText: /no direct or adjacent competitors/i }).first().click();

    const patchResponse = page.waitForResponse(
      (response) => response.url().includes(`/deals/${dealId}/claims/${targetClaim!.id}/review`) && response.request().method() === "PATCH"
    );
    await page.getByLabel("Status").selectOption("supported");
    await expect((await patchResponse).ok()).toBe(true);

    const after = await fetchDeal(page, dealId);
    const updatedClaim = after.claims.find((claim) => claim.id === targetClaim!.id);
    expect(updatedClaim?.status).toBe("supported");

    const afterScore = scoreClaims(after.claims);
    expect(afterScore.overall).toBeGreaterThan(beforeScore.overall);
    expect(requireMemo(after).overallGrade).toBe(afterScore.grade);
    expect(requireQualityReview(after).overconfidenceWarnings.some((warning) => warning.includes(targetClaim!.id))).toBe(true);

    await page.getByRole("button", { name: /Risk memo/i }).click();
    await expect(page.locator(".recommendation").filter({ hasText: `Current grade: ${afterScore.grade}` })).toBeVisible();
  });
});

async function seedDemoAndRunThroughUi(page: Page) {
  const seedResponsePromise = page.waitForResponse((response) => response.url().endsWith("/deals/demo") && response.request().method() === "POST");
  const analyzeResponsePromise = page.waitForResponse((response) => response.url().includes("/analyze-stream") && response.request().method() === "POST");

  await page.goto("/");
  await page.getByRole("button", { name: /Seed demo/i }).click();

  const seedResponse = await seedResponsePromise;
  const analyzeResponse = await analyzeResponsePromise;
  await expect(seedResponse.ok()).toBe(true);
  await expect(analyzeResponse.ok()).toBe(true);
  await expect(await analyzeResponse.text()).not.toContain('"event": "run_error"');
  await expect(page.getByText("Analysis complete", { exact: true }).first()).toBeVisible({ timeout: 90_000 });
  await expect(page.locator(".errorBanner")).toHaveCount(0);

  return ((await seedResponse.json()) as DealAnalysis).id;
}

async function uploadFixturePacketThroughUi(page: Page, files: string[]) {
  await page.goto("/");
  await page.getByRole("button", { name: "Attach files or URL" }).click();
  await page.locator('input[type="file"]').setInputFiles(files);

  const createResponse = page.waitForResponse((response) => response.url().endsWith("/deals") && response.request().method() === "POST");
  const materialsResponse = page.waitForResponse((response) => response.url().includes("/materials") && response.request().method() === "POST");
  await page.getByRole("button", { name: /^Add$/ }).click();

  const created = await createResponse;
  const materials = await materialsResponse;
  await expect(created.ok()).toBe(true);
  await expect(materials.ok()).toBe(true);
  await expect(page.getByText("Added diligence material")).toBeVisible();

  return ((await created.json()) as DealAnalysis).id;
}

async function runAnalysisWithoutStreamError(page: Page) {
  const analyzeResponse = page.waitForResponse((response) => response.url().includes("/analyze-stream") && response.request().method() === "POST");
  await page.getByRole("button", { name: /Run agent/i }).click();
  const response = await analyzeResponse;
  await expect(response.ok()).toBe(true);
  await expect(await response.text()).not.toContain('"event": "run_error"');
  await expect(page.getByText("Analysis complete", { exact: true }).first()).toBeVisible({ timeout: 90_000 });
  await expect(page.locator(".errorBanner")).toHaveCount(0);
}

async function fetchDeal(page: Page, dealId: string) {
  const response = await page.request.get(`${API_BASE_URL}/deals/${dealId}`);
  await expect(response.ok()).toBe(true);
  return (await response.json()) as DealAnalysis;
}

async function askQuestionThroughApi(page: Page, dealId: string, question: string) {
  const response = await page.request.post(`${API_BASE_URL}/deals/${dealId}/chat`, {
    data: { question }
  });
  await expect(response.ok()).toBe(true);
  return (await response.json()) as ChatTurn;
}

async function assertExportedMarkdownParity(page: Page, deal: DealAnalysis) {
  const memo = requireMemo(deal);
  const response = await page.request.get(`${API_BASE_URL}/deals/${deal.id}/export-memo`);
  await expect(response.ok()).toBe(true);
  const markdown = await response.text();

  expect(markdown).toContain("# DealProof Red Team Memo:");
  expect(markdown).toContain(`**Overall grade:** ${memo.overallGrade.toUpperCase()}`);
  for (const section of [
    "## Executive Summary",
    "## Thesis Assessment",
    "## Decision Drivers",
    "## Evidence Map",
    "## What We Can Trust",
    "## What Remains Unproven",
    "## What Would Change the Decision",
    "## Recommendation"
  ]) {
    expect(markdown).toContain(section);
  }
  expect(markdown).toContain(memo.icRecommendation);
  expect(markdown).toContain(memoRisks(memo)[0]);
}

function assertReportQuality(deal: DealAnalysis) {
  const memo = requireMemo(deal);
  const qualityReview = requireQualityReview(deal);
  const score = scoreClaims(deal.claims);

  expect(deal.claims.length).toBeGreaterThan(0);
  expect(memo.overallGrade).toBe(score.grade);
  expect(nonEmpty(memo.executiveSummary)).toBe(true);
  expect(nonEmpty(memo.thesisAssessment)).toBe(true);
  expect(nonEmpty(memo.investmentQuestion)).toBe(true);
  expect(nonEmpty(memo.icRecommendation)).toBe(true);
  expect(nonEmptyList(memo.keyStrengths)).toBe(true);
  expect(nonEmptyList(memoRisks(memo))).toBe(true);
  expect(nonEmptyList(memoDiligenceRequests(memo))).toBe(true);
  expect(nonEmptyList(memo.decisionDrivers)).toBe(true);
  expect(nonEmptyList(memo.evidenceMap)).toBe(true);

  assertRiskClaimsLeadRiskSections(deal.claims, memo);
  assertEvidenceMapQuality(memo, deal.evidence);
  assertQualityReviewReflectsLedger(deal);
}

function assertDemoOutputQuality(deal: DealAnalysis) {
  const memo = requireMemo(deal);
  const qualityReview = requireQualityReview(deal);
  const claimText = deal.claims.map((claim) => claim.text).join("\n");
  const riskText = memoRisks(memo).join("\n");
  const strengthText = memo.keyStrengths.join("\n");
  const diligenceText = memoDiligenceRequests(memo).join("\n");

  expect(deal.materials.length).toBeGreaterThanOrEqual(3);
  expect(deal.claims.length).toBeGreaterThanOrEqual(8);
  expect(deal.evidence.length).toBeGreaterThanOrEqual(deal.claims.length);
  expect(new Set(deal.claims.map((claim) => claim.text)).size).toBe(deal.claims.length);
  expect(new Set(deal.evidence.map((item) => item.citation)).size).toBeGreaterThanOrEqual(3);
  expect(deal.evidence.some((item) => item.quoteSpan && item.stance !== "not_found")).toBe(true);

  expect(Array.from(new Set(deal.claims.map((claim) => claim.status)))).toContain("weak");
  expect(claimText).toMatch(/ROI|retention|NRR|compliance|compet/i);
  expect(deal.claims.some((claim) => claim.status !== "supported" && /compet/i.test(claim.text))).toBe(true);
  expect(deal.claims.every((claim) => claim.status !== "supported")).toBe(true);
  expect(deal.claims.every((claim) => claim.verificationNeed.trim() && claim.riskRationale.trim())).toBe(true);

  expect(memo.overallGrade).toBe(scoreClaims(deal.claims).grade);
  expect(memo.investmentQuestion).toMatch(/CaviClear|investment|IC|trust|ready|scale/i);
  expect(riskText).toMatch(/compet|compliance|ROI|retention|unsupported|contradict/i);
  expect(diligenceText).toMatch(/customer|evidence|reference|compliance|cohort|retention|ROI/i);
  expect(strengthText).not.toMatch(/no direct competitors/i);

  expect(qualityReview.memoReadinessScore).toBeLessThan(90);
  expect(qualityReview.globalWarnings.length).toBeGreaterThan(0);
  expect(qualityReview.recommendedFollowUpEvidence.length).toBeGreaterThan(0);
}

function assertRiskClaimsLeadRiskSections(claims: DealClaim[], memo: RiskMemo) {
  const strengths = memo.keyStrengths.join("\n").toLowerCase();
  const risks = memoRisks(memo).join("\n").toLowerCase();
  const unresolved = claims.filter((claim) => claim.status !== "supported" && !isOffTargetPublicIssuerClaim(claim)).sort(riskSortKey).slice(0, 3);

  expect(unresolved.length).toBeGreaterThan(0);
  for (const claim of unresolved) {
    const snippet = claimSnippet(claim);
    expect(risks).toContain(snippet);
    expect(strengths).not.toContain(snippet);
  }
}

function assertEvidenceMapQuality(memo: RiskMemo, evidence: EvidenceItem[]) {
  const evidenceMap = memo.evidenceMap ?? [];
  expect(evidenceMap.length).toBeGreaterThan(0);
  expect(evidenceMap.every((entry) => /^claim-\d+ \((supported|weak|missing|contradicted)\):/i.test(entry))).toBe(true);
  expect(evidenceMap.every((entry) => entry.includes("primary source:") && entry.includes("citations:"))).toBe(true);

  const hasQuoteBackedEvidence = evidence.some((item) => item.quoteSpan && item.stance !== "not_found");
  if (hasQuoteBackedEvidence) {
    expect(evidenceMap.some((entry) => entry.includes("Primary quote:"))).toBe(true);
  }
}

function assertQualityReviewReflectsLedger(deal: DealAnalysis) {
  const qualityReview = requireQualityReview(deal);
  const warnings = qualityReview.globalWarnings;
  const claims = deal.claims;

  expect(qualityReview.memoReadinessScore).toBeGreaterThanOrEqual(0);
  expect(qualityReview.memoReadinessScore).toBeLessThanOrEqual(100);

  if (claims.some((claim) => claim.status === "contradicted")) {
    expect(warnings).toContain("At least one important claim is contradicted by supplied evidence.");
  }
  if (claims.some((claim) => claim.status === "supported" && claim.confidence !== "high")) {
    expect(warnings).toContain("Some supported claims have less than high reviewer confidence.");
  }
  if (!deal.evidence.some((item) => item.sourceIndependence === "third_party")) {
    expect(warnings).toContain("No third-party validation was attached to the analysis.");
  }
  if (claims.some((claim) => claim.status !== "supported" && claim.importance === "high")) {
    expect(warnings).toContain("High-importance claims remain weak or missing.");
  }

  const expectedLowValue = claims
    .filter((claim) => claim.qualityScore < 35 || claim.qualityIssues.includes("Claim is too terse to verify precisely."))
    .map((claim) => claim.id);
  expect(qualityReview.lowValueClaims).toEqual(expectedLowValue);

  const expectedFollowUp = Array.from(new Set(claims.filter((claim) => claim.status !== "supported").map((claim) => claim.verificationNeed))).slice(0, 6);
  expect(qualityReview.recommendedFollowUpEvidence).toEqual(expectedFollowUp);

  const expectedOverconfidence = claims.filter(
    (claim) => claim.status === "supported" && (claim.qualityIssues.includes("No third-party validation is attached.") || claim.confidence !== "high")
  );
  for (const claim of expectedOverconfidence) {
    expect(qualityReview.overconfidenceWarnings.some((warning) => warning.includes(`${claim.id}: ${claim.text}`))).toBe(true);
  }
}

function scoreClaims(claims: DealClaim[]) {
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
  const overall = claims.length ? Math.round(weighted.score / weighted.weight) : 0;
  const grade = overall >= 78 ? "green" : overall >= 48 ? "yellow" : "red";

  return { overall, grade } as const;
}

function riskSortKey(left: DealClaim, right: DealClaim) {
  const statusRank: Record<ClaimStatus, number> = { contradicted: 0, missing: 1, weak: 2, supported: 3 };
  const impactRank = { high: 0, medium: 1, low: 2 };
  const categoryRank: Record<string, number> = {
    customer_roi: 0,
    market: 1,
    competition: 2,
    compliance: 3,
    legal: 4,
    growth: 5,
    fundraising: 6,
    financials: 7
  };
  const confidenceRank = { low: 0, medium: 1, high: 2 };
  const leftKey = [
    statusRank[left.status],
    impactRank[left.decisionImpact],
    categoryRank[left.category] ?? 8,
    confidenceRank[left.confidence]
  ];
  const rightKey = [
    statusRank[right.status],
    impactRank[right.decisionImpact],
    categoryRank[right.category] ?? 8,
    confidenceRank[right.confidence]
  ];

  for (let index = 0; index < leftKey.length; index += 1) {
    if (leftKey[index] !== rightKey[index]) return leftKey[index] - rightKey[index];
  }
  return left.id.localeCompare(right.id);
}

function requireMemo(deal: DealAnalysis) {
  expect(deal.memo).toBeTruthy();
  return deal.memo!;
}

function requireQualityReview(deal: DealAnalysis) {
  expect(deal.qualityReview).toBeTruthy();
  return deal.qualityReview!;
}

function memoRisks(memo: RiskMemo) {
  return memo.keyRisks?.length ? memo.keyRisks : memo.materialRisks;
}

function memoDiligenceRequests(memo: RiskMemo) {
  return memo.nextDiligenceRequests?.length ? memo.nextDiligenceRequests : memo.followUpQuestions;
}

function nonEmpty(value: string | undefined) {
  return Boolean(value?.trim());
}

function nonEmptyList(items: string[] | undefined) {
  return Boolean(items?.length && items.every((item) => item.trim()));
}

function claimSnippet(claim: DealClaim) {
  return claim.text.toLowerCase().slice(0, 56);
}

function isOffTargetPublicIssuerClaim(claim: DealClaim) {
  return /\b(Apple|Target|Microsoft|Amazon|Google|Alphabet|Meta|Tesla|Nvidia)\b/i.test(claim.text);
}
