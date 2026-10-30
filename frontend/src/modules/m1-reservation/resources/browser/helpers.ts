import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";
export const syntheticPassword = "synthetic-b-resource-password";
export async function login(page: Page, account = "b-manager") {
  await page.getByLabel("账号", { exact: true }).fill(account);
  await page.getByLabel("密码", { exact: true }).fill(syntheticPassword);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "教室与座位管理", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".room-choice").first()).toBeVisible();
}
export async function beginRoom(page: Page, code: string) {
  await page.getByRole("button", { name: "新增教室", exact: true }).click();
  await page.locator("#resource-code").fill(code);
  await page.locator("#room-name").fill("浏览器合成教室");
  await page.locator("#room-location").fill("隔离验收区");
}
export async function save(
  page: Page,
  method: "POST" | "PATCH",
  suffix: string | RegExp,
) {
  const response = page.waitForResponse(
    (value) =>
      value.request().method() === method &&
      (typeof suffix === "string"
        ? new URL(value.url()).pathname.endsWith(suffix)
        : suffix.test(new URL(value.url()).pathname)),
  );
  await page.getByRole("button", { name: "保存", exact: true }).click();
  expect((await response).status()).toBe(method === "POST" ? 201 : 200);
  await expect(page.locator(".editor")).toHaveCount(0);
}
