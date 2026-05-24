import path from "node:path";
import { expect, test } from "@playwright/test";

const fixtureDir = path.join(process.cwd(), "backend", "tests", "fixtures", "real_cases");
const realCaseFiles = [
  "dm_revenue_flow_pitch.txt",
  "dm_revenue_flow_public_evidence.txt",
  "apple_2025_10k_evidence.txt",
  "real_case_claim_packet.txt"
].map((name) => path.join(fixtureDir, name));

test("runs a real-world public-material diligence case", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "Real-case E2E runs on desktop Chromium only.");

  await page.goto("/");
  await page.getByRole("button", { name: "Attach files or URL" }).click();
  await page.locator('input[type="file"]').setInputFiles(realCaseFiles);

  const createResponse = page.waitForResponse((response) => response.url().endsWith("/deals") && response.request().method() === "POST");
  const materialsResponse = page.waitForResponse((response) => response.url().includes("/materials") && response.request().method() === "POST");
  await page.getByRole("button", { name: /^Add$/ }).click();
  await expect((await createResponse).ok()).toBe(true);
  await expect((await materialsResponse).ok()).toBe(true);
  await expect(page.getByText(/real_case_claim_packet\.txt/)).toBeVisible();

  const analyzeResponse = page.waitForResponse((response) => response.url().includes("/analyze-stream") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Run agent", exact: true }).click();
  await expect((await analyzeResponse).ok()).toBe(true);
  await expect(page.getByText("Analysis complete", { exact: true }).first()).toBeVisible({ timeout: 90_000 });

  await expect(page.locator(".agentOutput")).toBeVisible();
  await expect(page.locator(".gradeBar")).toBeVisible();
  await expect(page.locator(".memoArtifact")).toBeVisible();
  await expect(page.getByRole("heading", { name: /diligence claims/i })).toBeVisible();
  await expect(page.locator(".claimGroup").filter({ hasText: "supported" }).first()).toBeVisible();
  await expect(page.locator(".claimGroup").filter({ hasText: "weak" }).first()).toBeVisible();
  await expect(page.locator(".claimGroup").filter({ hasText: "contradicted" }).first()).toBeVisible();
  await expect(page.locator(".claimRow").filter({ hasText: /supported|weak|contradicted|missing/i }).first()).toBeVisible();

  const firstEvidence = page.locator(".claimEvidence").first();
  await firstEvidence.locator("summary").click();
  await expect(firstEvidence.locator(".evidenceItem").first()).toBeVisible();
  await expect(firstEvidence.locator(".quoteBlock").first()).toBeVisible();

  const chatResponse = page.waitForResponse((response) => response.url().includes("/chat") && response.request().method() === "POST");
  await page.locator(".promptRow input").fill("Can we trust the ROI and no-competitor claims?");
  await page.locator(".iconButton--send").click();
  await expect((await chatResponse).ok()).toBe(true);
  await expect(page.locator(".answerBox")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".chatCitationChip").first()).toBeVisible();

  const memoResponse = page.waitForResponse((response) => response.url().includes("/export-memo") && response.request().method() === "GET");
  await expect(page.getByText("Red team memo", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /Export Markdown/i }).click();
  await expect((await memoResponse).ok()).toBe(true);
});
