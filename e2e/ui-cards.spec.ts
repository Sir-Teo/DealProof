import { expect, test, type Page } from "@playwright/test";

const DEAL_ID = "test-deal-01";

const MOCK_DEAL_SEEDED = {
  id: DEAL_ID,
  company: "CaviClear AI",
  tagline: "AI billing automation for dental clinics",
  stage: "Series A",
  status: "materials_loaded",
  generatedAt: null,
  materials: [{ id: "m1", name: "pitch.pdf", kind: "deck", summary: "Pitch deck", excerpt: "Deck excerpt" }],
  claims: [],
  evidence: [],
  memo: null,
  profile: null,
  qualityReview: null,
  score: null,
  chatHistory: []
};

const MOCK_DEAL_ANALYZED = {
  ...MOCK_DEAL_SEEDED,
  profile: { sector: "Healthcare", businessModel: "B2B SaaS", customer: "dental clinics", stage: "Series A", materialMix: ["deck: 1"] },
  claims: [
    claim("c1", "NRR is above 140%.", "supported", "financials", "high"),
    claim("c2", "37 signed clinics are active.", "weak", "growth", "medium"),
    claim("c3", "Full HIPAA compliance is complete.", "missing", "compliance", "high")
  ],
  evidence: [
    {
      id: "e1",
      claimId: "c1",
      title: "Public web supporting evidence",
      stance: "supports",
      snippet: "NRR is above 140%",
      quoteSpan: "NRR is above 140%",
      sourceName: "Public source",
      sourceType: "public_web",
      sourceUrl: "https://example.com/nrr",
      sourceIndependence: "third_party",
      reliability: "high",
      relevanceScore: 0.95,
      citation: "Public source (https://example.com/nrr)",
      chunkIndex: 1
    },
    {
      id: "e2",
      claimId: "c2",
      title: "Founder deck",
      stance: "partially_supports",
      snippet: "37 clinics are active, but signed status needs validation.",
      quoteSpan: "37 clinics are active",
      sourceName: "Founder deck",
      sourceType: "uploaded",
      sourceUrl: "https://example.com/clinics",
      sourceIndependence: "founder_supplied",
      reliability: "medium",
      relevanceScore: 0.78,
      citation: "Founder deck (https://example.com/clinics)",
      chunkIndex: 2
    }
  ],
  memo: {
    company: "CaviClear AI",
    overallGrade: "yellow",
    icRecommendation: "Current grade: yellow. Continue only after validating weak claims.",
    executiveSummary: "CaviClear is an early-stage dental billing automation company.",
    thesisAssessment: "Strong NRR but limited independent evidence.",
    investmentQuestion: "Can CaviClear scale beyond 50 clinics?",
    keyStrengths: ["Strong NRR"],
    materialRisks: ["HIPAA documentation gap"],
    keyRisks: ["HIPAA documentation gap"],
    decisionDrivers: ["Audit financials", "Reference checks"],
    followUpQuestions: ["Provide audited P&L"],
    nextDiligenceRequests: ["Audited P&L"],
    evidenceMap: ["c1 (supported): NRR is above 140%."]
  },
  qualityReview: {
    memoReadinessScore: 72,
    globalWarnings: ["TAM lacks external citation"],
    duplicatedClaims: [],
    lowValueClaims: [],
    recommendedFollowUpEvidence: ["Provide audited P&L"],
    overconfidenceWarnings: [],
    readinessStatus: "needs_diligence",
    topGatingIssue: "c3: Full HIPAA compliance is complete. needs more evidence.",
    approvedDiligenceRequests: ["Audited P&L"]
  },
  score: {
    overall: 72,
    grade: "yellow",
    counts: { supported: 1, weak: 1, contradicted: 0, missing: 1 },
    drivers: ["High-importance missing evidence prevents a green score."]
  },
  generatedAt: "2026-05-22T12:00:00Z",
  status: "completed"
};

function claim(id: string, text: string, status: string, category: string, importance: string) {
  return {
    id,
    text,
    category,
    sourceMaterial: "pitch.pdf",
    sourceSnippet: text,
    importance,
    status,
    riskRationale: "Risk rationale.",
    confidence: status === "supported" ? "high" : "medium",
    qualityScore: status === "supported" ? 88 : 54,
    qualityIssues: [],
    verificationNeed: "Request source-level evidence.",
    decisionImpact: importance,
    reviewerStatus: "unreviewed",
    reviewerDisposition: "unreviewed",
    reviewerNotes: "",
    statusReason: "Evidence status reason.",
    resolutionRequest: status === "supported" ? "" : `Provide source-level evidence: ${text}`
  };
}

async function setupAnalyzedMocks(page: Page, streamBody?: string) {
  await page.route("**/deals/demo", (route) => route.fulfill({ json: MOCK_DEAL_SEEDED }));
  await page.route(`**/deals/${DEAL_ID}/analyze-stream`, (route) =>
    route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
      body: streamBody ?? `data: ${JSON.stringify({ event: "run_complete", step: "agent", label: "Analysis complete" })}\n\n`
    })
  );
  await page.route(`**/deals/${DEAL_ID}`, (route) => route.fulfill({ json: MOCK_DEAL_ANALYZED }));
}

async function runMockDemo(page: Page) {
  await page.getByRole("button", { name: /Try demo/i }).evaluate((button: HTMLButtonElement) => button.click());
}

test("composer and empty state render correctly", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator(".brandLine strong")).toHaveText("DealProof");
  await expect(page.locator(".brandMark")).toBeVisible();
  await expect(page.getByText("Add deal materials to begin.")).toBeVisible();
  await expect(page.locator(".composerCard")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Ask about the deal evidence..." })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Run agent", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: /Load Harvey/i })).toBeEnabled();
});

test("attach drawer opens and closes on paperclip click", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator(".attachDrawer")).not.toBeVisible();
  await page.getByRole("button", { name: "Attach files or URL" }).evaluate((button: HTMLButtonElement) => button.click());
  await expect(page.locator(".attachDrawer")).toBeVisible();
  await expect(page.locator('input[type="file"]')).toBeAttached();
  await page.getByRole("button", { name: "Attach files or URL" }).evaluate((button: HTMLButtonElement) => button.click());
  await expect(page.locator(".attachDrawer")).not.toBeVisible();
});

test("loading a deal clears stale attachment input", async ({ page }) => {
  await page.route("**/deals/demo", (route) => route.fulfill({ json: MOCK_DEAL_SEEDED }));
  await page.goto("/");

  await page.getByRole("button", { name: "Attach files or URL" }).evaluate((button: HTMLButtonElement) => button.click());
  await page.getByPlaceholder("Add URL").fill("example.com");
  await page.getByRole("button", { name: /^Add$/ }).click();
  await expect(page.getByText("Invalid URL")).toHaveCount(2);

  await page.getByRole("button", { name: /Load Harvey/i }).click();

  await expect(page.getByText("Materials loaded — ready to analyze.")).toBeVisible();
  await expect(page.locator(".attachDrawer")).not.toBeVisible();
  await expect(page.getByText("Invalid URL")).toHaveCount(0);
});

test("post-analysis panels show memo, claims, and evidence", async ({ page }) => {
  await setupAnalyzedMocks(page);
  await page.goto("/");
  await runMockDemo(page);

  await expect(page.locator(".messageTitle").filter({ hasText: /Analysis complete/i })).toBeVisible({ timeout: 5_000 });
  await expect(page.locator(".agentOutput")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".gradeBar")).toHaveClass(/card--yellow/);
  await expect(page.locator(".gradeBar strong")).toHaveText("Needs diligence · yellow · 72/100");
  await expect(page.locator(".scoreDrivers")).toContainText("High-importance missing evidence prevents a green score.");
  await expect(page.locator(".memoArtifact")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Red team memo" })).toBeVisible();
  await expect(page.locator(".profileGrid .metric")).toHaveCount(4);
  await expect(page.getByRole("heading", { name: "3 priority diligence claims" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Needs evidence" })).toBeVisible();

  const evidence = page.locator('details.claimEvidence:has(summary:has-text("evidence"))').first();
  await evidence.locator("summary").click();
  await expect(evidence.locator(".evidenceItem").first()).toBeVisible();
  await expect(evidence.locator(".quoteBlock").first()).toBeVisible();
  await expect(evidence.getByRole("link", { name: /Open source/i })).toBeVisible();
});

test("agent stream renders web-search research details", async ({ page }) => {
  const streamBody = [
    { event: "run_start", step: "agent", label: "Starting diligence agent" },
    { event: "tool_start", step: "search_public_web", label: "Search public web", toolName: "search_public_web", input: "claims=3" },
    { event: "tool_delta", step: "search_public_web", label: "\"CaviClear\" competitors", toolName: "search_public_web", webEvent: "web_query", query: "\"CaviClear\" competitors", rawOutput: "Search: \"CaviClear\" competitors\n" },
    { event: "tool_delta", step: "search_public_web", label: "2 search results", toolName: "search_public_web", webEvent: "web_results", results: 2, rawOutput: "Results: 2\n" },
    { event: "tool_delta", step: "search_public_web", label: "supports: Public source", toolName: "search_public_web", webEvent: "web_evidence", stance: "supports", relevanceScore: "0.91", sourceName: "Public source", sourceUrl: "https://example.com/nrr", rawOutput: "Evidence: supports\n" },
    { event: "tool_complete", step: "search_public_web", label: "Search public web", toolName: "search_public_web", output: "Attached 1 public web evidence items." },
    { event: "run_complete", step: "agent", label: "Analysis complete" }
  ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");

  await setupAnalyzedMocks(page, streamBody);
  await page.goto("/");
  await runMockDemo(page);

  const webTool = page.locator(".toolCall").filter({ hasText: "search public web" }).first();
  await expect(webTool).toBeVisible({ timeout: 10_000 });
  await webTool.locator("summary").click();
  await expect(webTool.locator(".webResearchLog")).toBeVisible();
  await expect(webTool.locator(".webEventBadge.web_query")).toContainText("Search");
  await expect(webTool.locator(".webEventBadge.web_evidence")).toContainText("Evidence");
  await expect(webTool.getByText("supports · relevance 0.91")).toBeVisible();
});

test("mobile keeps composer and artifact panels usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setupAnalyzedMocks(page);
  await page.goto("/");
  await runMockDemo(page);

  await expect(page.locator(".composerCard")).toBeVisible();
  await expect(page.locator(".agentOutput")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".memoArtifact")).toBeVisible();
  await expect(page.locator(".claimGroups")).toBeVisible();
  const memoColumns = await page.locator(".memoColumns").evaluate((el) => getComputedStyle(el).gridTemplateColumns);
  expect(memoColumns.trim().split(/\s+/).length).toBe(1);
});
