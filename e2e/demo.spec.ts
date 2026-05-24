import { expect, test } from "@playwright/test";

test("runs the gold-path DealProof chat demo", async ({ page }) => {
  const seedResponse = page.waitForResponse((response) => response.url().endsWith("/deals/demo") && response.request().method() === "POST");
  const analyzeResponse = page.waitForResponse((response) => response.url().includes("/analyze-stream") && response.request().method() === "POST");
  await page.goto("/");

  await expect(page.getByText("Add deal materials to begin.")).toBeVisible();
  await page.getByRole("button", { name: /Try demo/i }).click();
  await expect((await seedResponse).ok()).toBe(true);
  await expect((await analyzeResponse).ok()).toBe(true);
  await expect(page.getByText("Analysis complete", { exact: true }).first()).toBeVisible({ timeout: 90_000 });

  await expect(page.locator(".agentStream")).toBeVisible();
  await expect(page.locator(".toolCall").filter({ hasText: "search public web" }).first()).toBeVisible();
  await expect(page.locator(".agentOutput")).toBeVisible();
  await expect(page.locator(".gradeBar")).toBeVisible();
  await expect(page.locator(".memoArtifact")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Red team memo" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /diligence claims/i })).toBeVisible();
  await expect(page.locator(".claimGroup").first()).toBeVisible();

  const firstEvidence = page.locator(".claimEvidence").first();
  await firstEvidence.locator("summary").click();
  await expect(firstEvidence.locator(".evidenceItem").first()).toBeVisible();
  await expect(firstEvidence.locator(".quoteBlock").first()).toBeVisible();

  const memoResponse = page.waitForResponse((response) => response.url().includes("/export-memo") && response.request().method() === "GET");
  await page.getByRole("link", { name: /Export Markdown/i }).click();
  await expect((await memoResponse).ok()).toBe(true);

  const chatResponse = page.waitForResponse((response) => response.url().includes("/chat") && response.request().method() === "POST");
  await page.getByRole("button", { name: /^What evidence supports/i }).first().click();
  await expect((await chatResponse).ok()).toBe(true);
  await expect(page.locator(".answerBox")).toHaveCount(1, { timeout: 60_000 });
  await expect(page.locator(".chatCitationChip").first()).toBeVisible();

  const followUpResponse = page.waitForResponse((response) => response.url().includes("/chat") && response.request().method() === "POST");
  await page.locator(".promptRow input").fill("What about retention?");
  await page.locator(".iconButton--send").click();
  await expect((await followUpResponse).ok()).toBe(true);
  await expect(page.locator(".answerBox")).toHaveCount(2, { timeout: 60_000 });
  await expect(page.getByText("What about retention?")).toHaveCount(1);
  await expect(page.locator(".chatCitationChip").nth(1)).toBeVisible();
});
