import { test, expect } from "@playwright/test";
import { login, beginRoom, save } from "./helpers";

test("shared App persists room and seat edits and shares one C login with M2", async ({
  page,
}, info) => {
  let logins = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/auth/sessions"
    )
      logins++;
  });
  await page.goto("/#resources");
  await login(page);
  const code = `B-HOST-${info.project.name}-CRUD`;
  await beginRoom(page, code);
  await save(page, "POST", "/rooms");
  await page.getByRole("button", { name: "编辑教室", exact: true }).click();
  await page.locator("#room-name").fill("共享入口持久教室");
  await save(page, "PATCH", /\/rooms\/\d+$/);
  await page.getByRole("button", { name: "新增座位", exact: true }).click();
  await page.locator("#resource-code").fill("HOST-01");
  await save(page, "POST", /\/rooms\/\d+\/seats$/);
  await page
    .getByRole("button", { name: "编辑座位 HOST-01", exact: true })
    .click();
  await page.locator("#seat-outlet").selectOption("rail");
  await save(page, "PATCH", /\/seats\/\d+$/);
  const navigation = page.getByRole("navigation", { name: "业务导航" });
  await navigation
    .getByRole("link", { name: "整教室申请与审批", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "退出登录", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("密码", { exact: true })).toHaveCount(0);
  await navigation.getByRole("link", { name: "资源管理", exact: true }).click();
  await expect(page.locator(".room-choice").first()).toBeVisible();
  expect(logins).toBe(1);
  await page.reload();
  await login(page);
  await page.locator("#room-search").fill(code);
  await page
    .locator(".room-panel form.filters")
    .getByRole("button", { name: "查询", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "共享入口持久教室", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "导轨插座", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("host-persisted.png"),
    fullPage: true,
  });
});

test("shared App keeps reader and scoped manager capabilities separate and preserves BIGINT", async ({
  page,
}, info) => {
  await page.goto("/#resources");
  await login(page, "b-reader");
  await expect(
    page.getByRole("button", { name: "新增教室", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "新增座位", exact: true }),
  ).toBeDisabled();
  await expect(page.locator(".room-choice")).toHaveCount(1);
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(page.getByLabel("密码", { exact: true })).toHaveValue("");
  await expect(page.locator(".resource-workspace")).toHaveCount(0);
  await login(page, "b-scoped");
  await expect(
    page.getByRole("button", { name: "新增教室", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "编辑教室", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "新增座位", exact: true }).click();
  await page.locator("#resource-code").fill(`HOST-SCOPE-${info.project.name}`);
  await save(page, "POST", "/rooms/1/seats");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await login(page);
  await page.locator("#room-search").fill("B-BIG");
  await page
    .locator(".room-panel form.filters")
    .getByRole("button", { name: "查询", exact: true })
    .click();
  await expect(page.locator(".seat-panel .eyebrow")).toHaveText("B-BIG");
  await page.getByRole("button", { name: "新增座位", exact: true }).click();
  await expect(page.locator(".editor")).toContainText("9007199254740993");
  await page.locator("#resource-code").fill(`HOST-BIG-${info.project.name}`);
  await save(page, "POST", "/rooms/9007199254740993/seats");
  await page.screenshot({
    path: info.outputPath("host-scoped.png"),
    fullPage: true,
  });
});

test("shared App response loss survives home navigation, unload cancellation and account return", async ({
  page,
}, info) => {
  await page.goto("/#resources");
  await login(page);
  let writes = 0;
  await page.route("**/api/v1/resources/rooms", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    writes++;
    const response = await route.fetch().catch(() => {
      throw new Error(
        "Real resource POST could not be confirmed before synthetic response loss",
      );
    });
    expect(response.status()).toBe(201);
    await route.abort("failed");
  });
  const code = `B-HOST-${info.project.name}-LOST`;
  await beginRoom(page, code);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText(/原资源操作仍待核对/)).toContainText(code);
  await page
    .getByRole("button", { name: "关闭表单并核对列表", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "业务导航" })
    .getByRole("link", { name: "平台首页", exact: true })
    .click();
  await expect(page.locator(".resource-workspace")).toHaveCount(0);
  let guarded = false;
  page.once("dialog", async (dialog) => {
    guarded = dialog.type() === "beforeunload";
    await dialog.dismiss();
  });
  await page.reload({ timeout: 3000 }).catch(() => null);
  expect(guarded).toBe(true);
  await page.getByRole("link", { name: "打开资源管理", exact: true }).click();
  await expect(page.getByText(/原资源操作仍待核对/)).toContainText(code);
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
    path: info.outputPath("host-unknown.png"),
    fullPage: true,
  });
});

test("server logout makes a resource 401 clear the shared session in both workspaces", async ({
  page,
}) => {
  let authorization = "";
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/resources/rooms")
      authorization = request.headers()["authorization"] ?? "";
  });
  await page.goto("/#resources");
  await login(page);
  // The real token stays only in this test's memory, never in a trace or artifact.
  if (!authorization.startsWith("Bearer "))
    throw new Error("No real resource authorization observed");
  const revoked = await page.request
    .delete("/api/v1/auth/sessions/current", {
      headers: { Authorization: authorization },
    })
    .catch(() => {
      throw new Error("Real session revocation request could not be completed");
    });
  expect(revoked.ok()).toBe(true);
  await page
    .locator(".room-panel form.filters")
    .getByRole("button", { name: "查询", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "登录资源管理", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("会话已失效，请重新登录。", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "业务导航" })
    .getByRole("link", { name: "整教室申请与审批", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "登录申请工作台", exact: true }),
  ).toBeVisible();
});
