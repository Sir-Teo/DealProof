import { expect, test } from "@playwright/test";

const DEAL_ID = "test-deal-01";

const MOCK_DEAL_SEEDED = {
  id: DEAL_ID,
  company: "CaviClear AI",
  tagline: "AI billing automation for dental clinics",
  stage: "Series A",
  materials: [{ id: "m1", name: "pitch.pdf", type: "pdf" }],
  claims: [],
  evidence: [],
  memo: null,
  profile: null,
  qualityReview: null,
};

const MOCK_DEAL_ANALYZED = {
  ...MOCK_DEAL_SEEDED,
  profile: { sector: "Healthcare", businessModel: "SaaS", customer: "SMB", stage: "Series A" },
  claims: [
    { id: "c1", text: "NRR above 140%", status: "supported", category: "financials", confidence: "high", qualityScore: 88, decisionImpact: "high", reviewerStatus: "pending", reviewerNotes: "", riskRationale: "Strong retention metric", qualityIssues: [] },
    { id: "c2", text: "37 signed clinics", status: "weak", category: "traction", confidence: "medium", qualityScore: 61, decisionImpact: "medium", reviewerStatus: "pending", reviewerNotes: "", riskRationale: "Early cohort", qualityIssues: ["Small sample"] },
    { id: "c3", text: "Full HIPAA compliance", status: "missing", category: "legal", confidence: "low", qualityScore: 30, decisionImpact: "high", reviewerStatus: "pending", reviewerNotes: "", riskRationale: "Not documented", qualityIssues: ["No evidence"] },
  ],
  evidence: [
    { id: "e1", claimId: "c1", stance: "supports", snippet: "NRR is above 140%", quoteSpan: "NRR is above 140%", sourceName: "Founder interview", sourceType: "interview", sourceUrl: null, sourceIndependence: "first_party", relevanceScore: 0.95, citation: "pitch.pdf, chunk 1", chunkIndex: 1 },
  ],
  memo: {
    overallGrade: "yellow",
    icRecommendation: "Conditional proceed pending financial audit.",
    executiveSummary: "CaviClear is an early-stage dental billing automation company.",
    thesisAssessment: "Strong NRR but limited independent evidence.",
    investmentQuestion: "Can CaviClear scale beyond 50 clinics?",
    keyStrengths: ["Strong NRR", "Sticky workflow"],
    materialRisks: ["Small cohort", "HIPAA documentation gap"],
    keyRisks: ["HIPAA documentation gap"],
    decisionDrivers: ["Audit financials", "Reference checks"],
    followUpQuestions: ["Provide audited P&L"],
    nextDiligenceRequests: ["Audited P&L"],
    evidenceMap: [],
  },
  qualityReview: {
    memoReadinessScore: 72,
    globalWarnings: ["TAM lacks external citation"],
  },
};


async function setupMocks(page: import("@playwright/test").Page) {
  await page.route("**/deals/demo", (route) => route.fulfill({ json: MOCK_DEAL_SEEDED }));
  await page.route(`**/deals/${DEAL_ID}`, (route) => route.fulfill({ json: MOCK_DEAL_ANALYZED }));
  await page.route(`**/deals/${DEAL_ID}/claims/*/review`, (route) =>
    route.fulfill({ json: { ...MOCK_DEAL_ANALYZED, claims: MOCK_DEAL_ANALYZED.claims.map((c) => c.id === "c2" ? { ...c, reviewerStatus: "verified" } : c) } })
  );
}

test("pending cards: kicker + em-dash + descriptions visible", async ({ page }) => {
  await page.route("**/deals/demo", (route) => route.fulfill({ json: MOCK_DEAL_SEEDED }));
  await page.goto("/");
  await expect(page.getByText("Add deal materials to begin.")).toBeVisible();

  await page.getByRole("button", { name: /Seed demo/i }).click();
  await expect(page.locator(".messageTitle").filter({ hasText: /Seeded/ })).toBeVisible({ timeout: 5_000 });

  // Three cards in pending state
  await expect(page.locator(".artifactCard")).toHaveCount(3);

  // Eyebrow kickers
  const kickers = page.locator(".artifactKicker");
  await expect(kickers.nth(0)).toContainText("Claim ledger");
  await expect(kickers.nth(1)).toContainText("IC readiness");
  await expect(kickers.nth(2)).toContainText("Risk memo");

  // All metrics show em-dash (no data yet)
  for (const metric of await page.locator(".artifactPrimary strong").all()) {
    await expect(metric).toHaveText("—");
  }

  // Pending copy
  await expect(page.getByText("Run the agent to extract verifiable claims.")).toBeVisible();
  await expect(page.getByText("Run the agent to unlock IC readiness.")).toBeVisible();
  await expect(page.getByText("Run the agent to generate the memo.")).toBeVisible();

  // No grade border classes applied before analysis
  await expect(page.locator(".artifactCard").nth(0)).not.toHaveClass(/card--red|card--green|card--yellow|card--amber/);
});

test("post-analysis cards: real metrics + grade borders", async ({ page }) => {
  await setupMocks(page);
  await page.goto("/");
  await page.getByRole("button", { name: /Seed demo/i }).click();
  await expect(page.locator(".messageTitle").filter({ hasText: /Seeded/ })).toBeVisible({ timeout: 5_000 });

  // Inject analyzed state by navigating as if analysis complete
  await page.route(`**/deals/${DEAL_ID}`, (route) => route.fulfill({ json: MOCK_DEAL_ANALYZED }));

  // Simulate analysis completion: manually set deal state via the analyze-stream endpoint
  await page.route(`**/deals/${DEAL_ID}/analyze-stream`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
      body: `data: ${JSON.stringify({ event: "run_complete", step: "done", label: "Analysis complete", status: "done" })}\n\ndata: ${JSON.stringify({ event: "run_complete", step: "done", label: "Analysis complete", status: "done" })}\n\n`,
    });
  });

  await page.getByRole("button", { name: /Run agent/i }).click();
  await expect(page.locator(".artifactCard")).toHaveCount(4, { timeout: 10_000 }); // 4th = qualityReview card

  // Claim Ledger shows count
  await expect(page.locator(".artifactKicker").nth(0)).toContainText("Claim ledger");
  await expect(page.locator(".artifactPrimary strong").nth(0)).toHaveText("3");

  // IC Readiness shows grade word
  const readinessMetric = page.locator(".artifactPrimary strong").nth(1);
  await expect(readinessMetric).not.toHaveText("—");

  // Risk Memo shows grade
  const memoMetric = page.locator(".artifactPrimary strong").nth(2);
  await expect(memoMetric).toHaveText("yellow"); // CSS text-transform: capitalize renders it as "Yellow"

  // Memo readiness shows score
  await expect(page.locator(".artifactPrimary strong").nth(3)).toHaveText("72%");

  // Grade border applied: risk memo card should have card--yellow
  await expect(page.locator(".artifactCard").nth(2)).toHaveClass(/card--yellow/);
});

test("composer: header, input, and composer card render correctly", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator(".brandLine strong")).toHaveText("DealProof");
  await expect(page.locator(".brandMark")).toBeVisible();
  await expect(page.locator(".composerCard")).toBeVisible();
  await expect(page.locator(".promptArea input")).toBeDisabled();
  await expect(page.getByRole("button", { name: /Run agent/i })).toBeDisabled();
  await expect(page.getByRole("button", { name: /Seed demo/i })).toBeEnabled();
});

test("attach drawer: opens and closes on paperclip click", async ({ page }) => {
  await page.route("**/deals/demo", (route) => route.fulfill({ json: MOCK_DEAL_SEEDED }));
  await page.goto("/");
  await page.getByRole("button", { name: /Seed demo/i }).click();
  await expect(page.locator(".messageTitle").filter({ hasText: /Seeded/ })).toBeVisible({ timeout: 5_000 });

  await expect(page.locator(".attachDrawer")).not.toBeVisible();
  await page.locator(".iconButton").click();
  await expect(page.locator(".attachDrawer")).toBeVisible();
  await page.locator(".iconButton").click();
  await expect(page.locator(".attachDrawer")).not.toBeVisible();
});

test("mobile: artifact cards stack to single column", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/deals/demo", (route) => route.fulfill({ json: MOCK_DEAL_SEEDED }));
  await page.goto("/");
  await page.getByRole("button", { name: /Seed demo/i }).click();
  await expect(page.locator(".messageTitle").filter({ hasText: /Seeded/ })).toBeVisible({ timeout: 5_000 });

  const grid = page.locator(".artifactGrid");
  await expect(grid).toBeVisible();
  const cols = await grid.evaluate((el) => getComputedStyle(el).gridTemplateColumns);
  expect(cols.trim().split(/\s+/).length).toBe(1);
});
