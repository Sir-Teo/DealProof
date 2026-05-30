import path from "node:path";
import { expect, test } from "@playwright/test";

const fixtureDir = path.join(process.cwd(), "backend", "tests", "fixtures", "real_cases", "large_data_room");
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
].map((name) => path.join(fixtureDir, name));

test("runs a larger public-material data room through the diligence workflow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "Large real-case E2E runs on desktop Chromium only.");

  await page.goto("/");
  await page.getByRole("button", { name: "Attach files or URL" }).click();
  await page.locator('input[type="file"]').setInputFiles(largeRealCaseFiles);

  const createResponse = page.waitForResponse((response) => response.url().endsWith("/deals") && response.request().method() === "POST");
  const materialsResponse = page.waitForResponse((response) => response.url().includes("/materials") && response.request().method() === "POST");
  await page.getByRole("button", { name: /^Add$/ }).click();
  await expect((await createResponse).ok()).toBe(true);
  await expect((await materialsResponse).ok()).toBe(true);
  await expect(page.locator(".materialRow").filter({ hasText: /14_analyst_claim_packet\.txt/ }).first()).toBeVisible();

  const analyzeResponse = page.waitForResponse((response) => response.url().includes("/analyze-stream") && response.request().method() === "POST");
  await page.locator(".materialsReady .primaryButton").click();
  await expect((await analyzeResponse).ok()).toBe(true);
  await expect(page.getByText("Analysis complete", { exact: true }).first()).toBeVisible({ timeout: 90_000 });

  await expect(page.locator(".agentOutput")).toBeVisible();
  await expect(page.locator(".gradeBar")).toBeVisible();
  await expect(page.locator(".memoArtifact")).toBeVisible();
  await expect(page.getByRole("heading", { name: /priority diligence claims/i })).toBeVisible();
  await expect(page.locator(".claimRow").filter({ hasText: "contradicted" }).first()).toBeVisible();
  await expect(page.locator(".claimRow").filter({ hasText: "supported" }).first()).toBeVisible();
  await expect(page.locator(".claimRow").filter({ hasText: "weak" }).first()).toBeVisible();

  const contradictedEvidence = page.locator(".claimRow").filter({ hasText: "contradicted" }).first().locator(".claimEvidence");
  await contradictedEvidence.locator("summary").click();
  await expect(contradictedEvidence.locator(".evidenceItem").first()).toBeVisible();

  const chatResponse = page.waitForResponse((response) => response.url().includes("/chat") && response.request().method() === "POST");
  await page.locator(".promptRow input").fill("What are the biggest unsupported or contradicted claims?");
  await page.locator(".iconButton--send").click();
  await expect((await chatResponse).ok()).toBe(true);
  await expect(page.locator(".answerBox")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".answerBox footer span").first()).toBeVisible();

  const memoResponse = page.waitForResponse((response) => response.url().includes("/export-memo") && response.request().method() === "GET");
  await expect(page.getByText("Red team memo", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /Export Markdown/i }).click();
  await expect((await memoResponse).ok()).toBe(true);
});
