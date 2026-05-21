import { expect, test } from "@playwright/test";

test("runs the gold-path DealProof demo", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "AI diligence red team" })).toBeVisible();
  await page.getByRole("button", { name: /Seed CaviClear Packet/i }).click();
  await expect(page.getByText("CaviClear Seed Deck.txt")).toBeVisible();

  await page.getByRole("button", { name: /Run LangGraph Agent/i }).click();
  await expect(page.getByText(/diligence claims/i)).toBeVisible({ timeout: 90_000 });

  await page.getByRole("button", { name: /Evidence/i }).click();
  await expect(page.getByText("Evidence drawer")).toBeVisible();

  await page.getByRole("button", { name: /Risk Memo/i }).click();
  await expect(page.getByText("1-page IC red team memo")).toBeVisible();
  await expect(page.locator(".recommendation")).toBeVisible();

  await page.getByRole("button", { name: "Q&A" }).click();
  await page.getByRole("button", { name: "Can we trust the ROI claim?" }).click();
  await expect(page.getByText("DealProof answer")).toBeVisible({ timeout: 60_000 });
});
