import { expect, test } from "@playwright/test";

test("runs the gold-path DealProof chat demo", async ({ page }) => {
  const seedResponse = page.waitForResponse((response) => response.url().endsWith("/deals/demo") && response.request().method() === "POST");
  await page.goto("/");

  await expect(page.getByText("Add deal materials to begin.")).toBeVisible();
  await page.getByRole("button", { name: /Seed demo/i }).click();
  await expect((await seedResponse).ok()).toBe(true);
  await expect(page.getByText(/Seeded CaviClear AI/)).toBeVisible();

  const analyzeResponse = page.waitForResponse((response) => response.url().includes("/analyze-stream") && response.request().method() === "POST");
  await page.getByRole("button", { name: /Run agent/i }).click();
  await expect((await analyzeResponse).ok()).toBe(true);
  await expect(page.getByText("Analysis complete", { exact: true }).first()).toBeVisible({ timeout: 90_000 });

  const claimLedger = page.getByRole("button", { name: /Claim ledger [1-9]/i });
  await expect(claimLedger).toBeEnabled({ timeout: 90_000 });
  await claimLedger.click();
  await expect(page.getByRole("heading", { name: /diligence claims/i })).toBeVisible();

  await page.locator(".claimRow").first().click();
  await expect(page.locator(".evidenceItem").first()).toBeVisible();
  await expect(page.locator(".citationSummary")).toBeVisible();
  await expect(page.locator(".quoteBlock").first()).toBeVisible();

  await page.getByRole("button", { name: /^IC readiness/i }).click();
  await expect(page.getByRole("heading", { name: /IC readiness workbench/i })).toBeVisible();
  await expect(page.getByText("Top gating issue")).toBeVisible();
  await expect(page.getByText("Critical blockers")).toBeVisible();

  await page.locator(".readinessClaim").first().click();
  await expect(page.locator(".evidenceItem").first()).toBeVisible();

  await page.getByRole("button", { name: /^IC readiness/i }).click();
  const reviewResponse = page.waitForResponse((response) => response.url().includes("/claims/") && response.url().includes("/review") && response.request().method() === "PATCH");
  await page.locator(".readinessRow").first().getByRole("button", { name: /Mark verified/i }).click();
  await expect((await reviewResponse).ok()).toBe(true);
  await expect(page.getByText("Reviewer marked this claim as verified.")).toBeVisible();

  const memoResponse = page.waitForResponse((response) => response.url().includes("/export-memo") && response.request().method() === "GET");
  await page.getByRole("button", { name: /Risk memo/i }).click();
  await expect(page.getByText("Red team memo", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /Export Markdown/i }).click();
  await expect((await memoResponse).ok()).toBe(true);

  const chatResponse = page.waitForResponse((response) => response.url().includes("/chat") && response.request().method() === "POST");
  await page.getByRole("button", { name: /^What evidence supports/i }).first().click();
  await expect((await chatResponse).ok()).toBe(true);
  await expect(page.locator(".answerBox")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".chatCitationChip").first()).toBeVisible();
});
