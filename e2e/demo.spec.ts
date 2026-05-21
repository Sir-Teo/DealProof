import { expect, test } from "@playwright/test";

test("runs the gold-path DealProof chat demo", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Drop in a deal packet or seed the demo.")).toBeVisible();
  await page.getByRole("button", { name: /Seed demo/i }).click();
  await expect(page.getByText("Seeded the CaviClear demo packet")).toBeVisible();

  await page.getByRole("button", { name: /Run agent/i }).click();
  await expect(page.getByText("Working").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Analysis complete")).toBeVisible({ timeout: 90_000 });

  const claimLedger = page.getByRole("button", { name: /Claim ledger [1-9]/i });
  await expect(claimLedger).toBeEnabled({ timeout: 90_000 });
  await claimLedger.click();
  await expect(page.getByText("Claim Ledger", { exact: true })).toBeVisible();

  await page.locator(".claimRow").first().click();
  await expect(page.getByText("Evidence Drawer")).toBeVisible();

  await page.getByRole("button", { name: /Risk memo/i }).click();
  await expect(page.getByText("Partner-ready red team memo")).toBeVisible();
  await expect(page.getByRole("link", { name: /Export Markdown/i })).toBeVisible();

  await page.getByRole("button", { name: "Can we trust the ROI claim?" }).click();
  await expect(page.getByText("DealProof answer")).toBeVisible({ timeout: 60_000 });
});
