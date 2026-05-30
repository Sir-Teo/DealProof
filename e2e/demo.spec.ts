import { expect, test } from "@playwright/test";

test("demo analysis completes with deterministic E2E backend", async ({ page }) => {
  const seedResponse = page.waitForResponse((response) => response.url().endsWith("/deals/demo") && response.request().method() === "POST");
  const analyzeResponse = page.waitForResponse((response) => response.url().includes("/analyze-stream") && response.request().method() === "POST");
  await page.goto("/");

  await expect(page.getByText("Add deal materials to begin.")).toBeVisible();
  await page.getByRole("button", { name: /Try demo/i }).evaluate((button: HTMLButtonElement) => button.click());

  await expect((await seedResponse).ok()).toBe(true);
  const response = await analyzeResponse;
  await expect(response.ok()).toBe(true);
  await expect(await response.text()).not.toContain('"event": "run_error"');
  await expect(page.getByText("Analysis complete", { exact: true }).first()).toBeVisible({ timeout: 90_000 });
  await expect(page.locator(".gradeBar")).toBeVisible();
  await expect(page.locator(".memoArtifact")).toBeVisible();
  await expect(page.locator(".reportV2")).toBeVisible();
});
