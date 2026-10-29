import { test, expect } from "@playwright/test";
const origin = process.env.CAMPUS_M2_LIVE_ORIGIN;
test.skip(
  !origin,
  "Requires the real isolated C+B/PostgreSQL acceptance services",
);

test("ordinary applicant searches, pages beyond 100 choices and submits a BIGINT room", async ({
  page,
}, info) => {
  const password = process.env.CAMPUS_BOOTSTRAP_PASSWORD;
  if (!password)
    throw new Error("Explicit synthetic account password required");
  const managementReads: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/resources/rooms")
      managementReads.push(request.url());
  });
  await page.goto("/#m2");
  await page.getByLabel("账号", { exact: true }).fill("m2-browser-student");
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "可访问的教室申请" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "新建申请", exact: true }).click();
  const pagination = page.getByRole("navigation", { name: "教室目录分页" });
  await expect(pagination).toContainText("符合范围 121 间");
  await expect(
    page.getByRole("button", { name: "提交申请", exact: true }),
  ).toBeDisabled();
  for (let index = 2; index <= 7; index++) {
    await page.getByRole("button", { name: "下一页教室", exact: true }).click();
    await expect(pagination).toContainText(`第 ${index} 页`);
  }
  await expect(page.locator("#m2-room option")).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "下一页教室", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("选择教室", { exact: true })
    .selectOption("9007199254740993");
  await page.screenshot({
    path: `test-results/${info.project.name}-m2-real-room-picker.png`,
    fullPage: true,
  });
  await page.getByLabel("搜索教室", { exact: true }).fill("OTHER");
  await page.getByRole("button", { name: "查询教室", exact: true }).click();
  await expect(
    page.getByText("没有符合条件的授权教室，请调整搜索条件。", { exact: true }),
  ).toBeVisible();
  await expect(pagination).toContainText("符合范围 0 间");
  await expect(
    page.getByRole("button", { name: "提交申请", exact: true }),
  ).toBeDisabled();
  await expect(page.getByLabel("选择教室", { exact: true })).toHaveValue("");
  await page.getByLabel("搜索教室", { exact: true }).fill("OWN");
  await page.getByRole("button", { name: "查询教室", exact: true }).click();
  await expect(pagination).toContainText("第 1 页");
  await expect(pagination).toContainText("符合范围 1 间");
  await page
    .getByLabel("选择教室", { exact: true })
    .selectOption("9007199254740993");
  const purpose = `Synthetic browser ${info.project.name} ${Date.now()}`;
  await page.getByLabel("申请用途", { exact: true }).fill(purpose);
  const date = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  await page.getByLabel("开始时间", { exact: true }).fill(`${date}T09:00`);
  await page.getByLabel("结束时间", { exact: true }).fill(`${date}T10:00`);
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/m2/applications",
  );
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/v1/m2/applications",
  );
  await page.getByRole("button", { name: "提交申请", exact: true }).click();
  const request = await requestPromise;
  expect(request.postDataJSON().room_id).toBe("9007199254740993");
  expect((await responsePromise).status()).toBe(201);
  const detail = page.getByRole("region", { name: "申请详情" });
  await expect(detail).toContainText(purpose);
  await expect(detail).toContainText("尚未确认生效");
  await expect(
    page.getByRole("region", { name: "占用处理进度" }),
  ).toContainText("尚未产生占用或释放操作");
  expect(managementReads).toEqual([]);
  await expect(page.locator("body")).not.toContainText("合成数据");
  await page.screenshot({
    path: `test-results/${info.project.name}-m2-real-room-options.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "登录申请工作台" }),
  ).toBeVisible();
  await expect(page.locator("#m2-password")).toHaveValue("");
});
