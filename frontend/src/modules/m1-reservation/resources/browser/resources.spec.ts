import { test, expect } from "@playwright/test";
import { login, beginRoom, save } from "./helpers";
const entry = "/src/modules/m1-reservation/resources/browser/index.html";

test("real browser creates, edits and rereads room/seat with a string BIGINT", async ({
  page,
}, info) => {
  const code = `B-${info.project.name}-CRUD`;
  await page.goto(entry);
  await login(page);
  await beginRoom(page, code);
  await save(page, "POST", "/rooms");
  await expect(page.locator(".room-choice")).toHaveCount(1);
  await page.getByRole("button", { name: "编辑教室", exact: true }).click();
  await page.locator("#room-name").fill("浏览器修改教室");
  await save(page, "PATCH", /\/rooms\/\d+$/);
  await expect(
    page.getByRole("heading", { name: "浏览器修改教室", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "新增座位", exact: true }).click();
  await page.locator("#resource-code").fill("BROWSER-01");
  await page.locator("#seat-outlet").selectOption("fixed");
  const seatResponse = page.waitForResponse(
    (value) =>
      value.request().method() === "POST" &&
      /\/rooms\/\d+\/seats$/.test(new URL(value.url()).pathname),
  );
  await page.getByRole("button", { name: "保存", exact: true }).click();
  expect((await seatResponse).status()).toBe(201);
  await expect(page.locator(".editor")).toHaveCount(0);
  await expect(page.getByText("BROWSER-01", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "编辑座位 BROWSER-01", exact: true })
    .click();
  await page.locator("#seat-outlet").selectOption("rail");
  const patchResponse = page.waitForResponse(
    (value) =>
      value.request().method() === "PATCH" &&
      /\/seats\/\d+$/.test(new URL(value.url()).pathname),
  );
  await page.getByRole("button", { name: "保存", exact: true }).click();
  expect((await patchResponse).status()).toBe(200);
  await expect(
    page.getByRole("cell", { name: "导轨插座", exact: true }),
  ).toBeVisible();
  // Full reload loses in-memory login but must keep actual persisted resources.
  await page.reload();
  await login(page);
  await page.locator("#room-search").fill(code);
  await page
    .locator(".room-panel form.filters")
    .getByRole("button", { name: "查询", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "浏览器修改教室", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "导轨插座", exact: true }),
  ).toBeVisible();
  await page.locator("#room-search").fill("B-BIG");
  await page
    .locator(".room-panel form.filters")
    .getByRole("button", { name: "查询", exact: true })
    .click();
  await expect(page.locator(".room-choice")).toHaveCount(1);
  await expect(page.locator(".seat-panel .eyebrow")).toHaveText("B-BIG");
  await page.getByRole("button", { name: "新增座位", exact: true }).click();
  await expect(page.locator(".editor")).toContainText("9007199254740993");
  await page.locator("#resource-code").fill(`BIG-${info.project.name}`);
  const bigResponse = page.waitForResponse(
    (value) =>
      value.request().method() === "POST" &&
      new URL(value.url()).pathname ===
        "/api/v1/resources/rooms/9007199254740993/seats",
  );
  await page.getByRole("button", { name: "保存", exact: true }).click();
  expect((await bigResponse).status()).toBe(201);
  await expect(page.locator(".editor")).toHaveCount(0);
  await page.screenshot({
    path: info.outputPath("resource-persisted.png"),
    fullPage: true,
  });
});

test("read-only and scoped identities keep create permission separate and logout clears the view", async ({
  page,
}, info) => {
  await page.goto(entry);
  await login(page, "b-reader");
  await expect(
    page.getByRole("button", { name: "新增教室", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "新增座位", exact: true }),
  ).toBeDisabled();
  await expect(page.locator(".room-choice")).toHaveCount(1);
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(page.locator("#b-test-password")).toHaveValue("");
  await expect(page.locator(".resource-workspace")).toHaveCount(0);
  await login(page, "b-scoped");
  await expect(
    page.getByRole("button", { name: "新增教室", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "编辑教室", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "新增座位", exact: true }).click();
  await page.locator("#resource-code").fill(`SCOPE-${info.project.name}`);
  await save(page, "POST", "/rooms/1/seats");
  await expect(
    page.getByText(`SCOPE-${info.project.name}`, { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("resource-scoped.png"),
    fullPage: true,
  });
});

test("committed response loss survives hidden view, unload cancellation and account return without a second POST", async ({
  page,
}, info) => {
  const code = `B-${info.project.name}-LOST`;
  await page.goto(entry);
  await login(page);
  let writes = 0;
  await page.route("**/api/v1/resources/rooms", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    writes++;
    let status = 0;
    try {
      status = (await route.fetch()).status();
    } catch {
      throw new Error(
        "Isolated POST could not be acknowledged before synthetic loss",
      );
    }
    expect(status).toBe(201);
    await route.abort("failed");
  });
  await beginRoom(page, code);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText(/原资源操作仍待核对/)).toContainText(code);
  await page
    .getByRole("button", { name: "关闭表单并核对列表", exact: true })
    .click();
  await page
    .getByRole("button", { name: "切到验收占位页", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "验收占位页", exact: true }),
  ).toBeVisible();
  let guarded = false;
  page.once("dialog", async (dialog) => {
    guarded = dialog.type() === "beforeunload";
    await dialog.dismiss();
  });
  await page.reload({ timeout: 3000 }).catch(() => null);
  expect(guarded).toBe(true);
  await expect(
    page.getByRole("heading", { name: "验收占位页", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "资源管理", exact: true }).click();
  await expect(page.getByText(/原资源操作仍待核对/)).toContainText(code);
  await expect(
    page.getByRole("button", { name: "新增教室", exact: true }),
  ).toBeDisabled();
  await page.locator("#room-search").fill(code);
  await page
    .locator(".room-panel form.filters")
    .getByRole("button", { name: "查询", exact: true })
    .click();
  await expect(page.locator(".room-choice")).toHaveCount(1);
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await login(page, "b-reader");
  await expect(page.getByText(/原资源操作仍待核对/)).toHaveCount(0);
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await login(page);
  await expect(page.getByText(/原资源操作仍待核对/)).toContainText(code);
  await expect(
    page.getByRole("button", { name: "新增教室", exact: true }),
  ).toBeDisabled();
  expect(writes).toBe(1);
  await page.screenshot({
    path: info.outputPath("resource-unknown-retained.png"),
    fullPage: true,
  });
});
