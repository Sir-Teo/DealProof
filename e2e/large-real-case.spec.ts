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
  await expect(page.getByText("Added diligence material")).toBeVisible();
  await expect(page.getByText(/14_analyst_claim_packet\.txt/)).toBeVisible();

  const analyzeResponse = page.waitForResponse((response) => response.url().includes("/analyze-stream") && response.request().method() === "POST");
  await page.getByRole("button", { name: /Run agent/i }).click();
  await expect((await analyzeResponse).ok()).toBe(true);
  await expect(page.getByText("Analysis complete")).toBeVisible({ timeout: 90_000 });

  const claimLedger = page.getByRole("button", { name: /Claim ledger 18/i });
  await expect(claimLedger).toBeEnabled({ timeout: 90_000 });
  await claimLedger.click();
  await expect(page.getByRole("heading", { name: /18 diligence claims/i })).toBeVisible();
  await expect(page.locator(".claimRow").filter({ hasText: "contradicted" }).first()).toBeVisible();
  await expect(page.locator(".claimRow").filter({ hasText: "supported" }).first()).toBeVisible();
  await expect(page.locator(".claimRow").filter({ hasText: "weak" }).first()).toBeVisible();

  await page.locator(".claimRow").filter({ hasText: "contradicted" }).first().click();
  await expect(page.locator(".evidenceItem").filter({ hasText: "contradicts" }).first()).toBeVisible();

  const chatResponse = page.waitForResponse((response) => response.url().includes("/chat") && response.request().method() === "POST");
  await page.getByPlaceholder("Ask about the deal evidence...").fill("What are the biggest unsupported or contradicted claims?");
  await page.getByPlaceholder("Ask about the deal evidence...").press("Enter");
  await expect((await chatResponse).ok()).toBe(true);
  await expect(page.locator(".answerBox")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".answerBox footer span").first()).toBeVisible();

  const memoResponse = page.waitForResponse((response) => response.url().includes("/export-memo") && response.request().method() === "GET");
  await page.getByRole("button", { name: /Risk memo/i }).click();
  await expect(page.getByText("Red team memo", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /Export Markdown/i }).click();
  await expect((await memoResponse).ok()).toBe(true);
});
