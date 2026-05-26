import { expect, test } from "@playwright/test";

const NO_API_KEY = "DEEPSEEK_API_KEY is not configured. Add it to backend/.env.";

test("demo analysis reports a missing API key clearly", async ({ page }) => {
  const seedResponse = page.waitForResponse((response) => response.url().endsWith("/deals/demo") && response.request().method() === "POST");
  const analyzeResponse = page.waitForResponse((response) => response.url().includes("/analyze-stream") && response.request().method() === "POST");
  await page.goto("/");

  await expect(page.getByText("Add deal materials to begin.")).toBeVisible();
  await page.getByRole("button", { name: /Try demo/i }).click();

  await expect((await seedResponse).ok()).toBe(true);
  const response = await analyzeResponse;
  await expect(response.ok()).toBe(true);
  await expect(await response.text()).toContain(NO_API_KEY);
  await expect(page.getByText(NO_API_KEY).first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Analysis complete", { exact: true })).toHaveCount(0);
});
