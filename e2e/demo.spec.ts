import { expect, test } from "@playwright/test";

test("runs the gold-path DealProof demo", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "AI diligence red team" })).toBeVisible();
  await page.getByRole("button", { name: /Analyze Packet/i }).click();
  await expect(page.getByRole("heading", { name: "10 diligence claims" })).toBeVisible();

  await page.getByRole("button", { name: /Evidence/i }).click();
  await page.getByText("There is no direct competitor").click();
  await expect(page.getByText("Dental RCM vendors advertise denial workflows")).toBeVisible();

  await page.getByRole("button", { name: /Risk Memo/i }).click();
  await expect(page.getByText("1-page IC red team memo")).toBeVisible();
  await expect(page.locator(".recommendation")).toContainText("Proceed to partner diligence only if customer references validate ROI");

  await page.getByRole("button", { name: "Q&A" }).click();
  await page.getByRole("button", { name: "Can we trust the ROI claim?" }).click();
  await expect(page.getByText("DealProof answer")).toBeVisible();
});
