import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import App from "../../../App.vue";
import { createPrototypeResourceGateway } from "./prototype";

const mapping = {
  read: "synthetic.read",
  manage: "synthetic.manage",
  create_rooms: "synthetic.create",
};
let wrapper: VueWrapper | undefined;
afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  window.location.hash = "";
});
async function navigate(hash: string) {
  window.location.hash = hash;
  window.dispatchEvent(new Event("hashchange"));
  await flushPromises();
}
async function setup(configured = true) {
  vi.stubEnv(
    "VITE_RESOURCE_PERMISSIONS",
    configured ? JSON.stringify(mapping) : "",
  );
  window.location.hash = "#resources";
  const room = (await createPrototypeResourceGateway().listRooms({})).items[0]!;
  let account = "manager";
  const request = vi
    .fn<typeof fetch>()
    .mockImplementation(async (input, init) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/health/ready") return Response.json({ status: "ready" });
      if (path === "/api/v1/auth/sessions" && init?.method === "POST") {
        account = JSON.parse(String(init.body)).username;
        return Response.json({
          access_token: `synthetic-${account}`,
          token_type: "bearer",
          expires_at: "2099-01-01T00:00:00Z",
        });
      }
      if (path === "/api/v1/auth/me")
        return Response.json({
          subject_id: `00000000-0000-4000-8000-00000000000${account === "manager" ? "1" : "2"}`,
          department_id: "synthetic",
          roles: [],
          permissions:
            account === "manager" ? Object.values(mapping) : [mapping.read],
          data_scopes: { all_rooms: account === "manager", room_ids: ["1"] },
        });
      if (path === "/api/v1/auth/sessions/current")
        return new Response(null, { status: 204 });
      if (init?.method === "POST")
        throw new TypeError("synthetic lost response");
      const seats = path.endsWith("/seats");
      return Response.json({
        items: seats ? [] : [room],
        total: seats ? 0 : 1,
        limit: 20,
        offset: 0,
      });
    });
  vi.stubGlobal("fetch", request);
  wrapper = mount(App, {
    global: {
      stubs: { M2Workspace: { template: "<div data-m2-workspace />" } },
    },
  });
  await flushPromises();
  async function login(account = "manager") {
    await wrapper!.get("#m2-username").setValue(account);
    await wrapper!.get("#m2-password").setValue("synthetic-form-password");
    await wrapper!.get("form").trigger("submit");
    await flushPromises();
  }
  return { request, login };
}
describe("shared App resource wiring", () => {
  it("keeps missing permission configuration closed without auth or resource requests", async () => {
    const { request } = await setup(false);
    expect(wrapper!.text()).toContain("尚未");
    expect(request).not.toHaveBeenCalled();
    expect(wrapper!.find("#m2-password").exists()).toBe(false);
  });
  it("uses one login and identity across the actual M2 and resource routes", async () => {
    const { request, login } = await setup();
    await login();
    expect(wrapper!.find(".room-choice").exists()).toBe(true);
    await navigate("#m2");
    expect(wrapper!.find("[data-m2-workspace]").exists()).toBe(true);
    expect(wrapper!.find("#m2-password").exists()).toBe(false);
    await navigate("#resources");
    expect(wrapper!.find(".room-choice").exists()).toBe(true);
    expect(
      request.mock.calls.filter(
        ([url, init]) =>
          url === "/api/v1/auth/sessions" && init?.method === "POST",
      ),
    ).toHaveLength(1);
  });
  it("retains unknown writes outside the resource route, isolates accounts and removes its global guard on unmount", async () => {
    const { request, login } = await setup();
    await login();
    const buttons = () => wrapper!.findAll("button");
    await buttons()
      .find((button) => button.text() === "新增教室")!
      .trigger("click");
    await wrapper!.get("#resource-code").setValue("SHARED-UNKNOWN");
    await wrapper!.get("#room-name").setValue("合成未知教室");
    await wrapper!.get("#room-location").setValue("合成测试区");
    await wrapper!.get(".editor form").trigger("submit");
    await flushPromises();
    expect(wrapper!.text()).toContain("SHARED-UNKNOWN");
    await navigate("");
    expect(wrapper!.find(".resource-workspace").exists()).toBe(false);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    await navigate("#resources");
    expect(wrapper!.text()).toContain("SHARED-UNKNOWN");
    await buttons()
      .find((button) => button.text() === "退出登录")!
      .trigger("click");
    await flushPromises();
    await login("reader");
    expect(wrapper!.text()).not.toContain("SHARED-UNKNOWN");
    await buttons()
      .find((button) => button.text() === "退出登录")!
      .trigger("click");
    await flushPromises();
    await login();
    expect(wrapper!.text()).toContain("SHARED-UNKNOWN");
    expect(
      request.mock.calls.filter(
        ([url, init]) =>
          String(url).includes("/resources/") && init?.method === "POST",
      ),
    ).toHaveLength(1);
    wrapper!.unmount();
    wrapper = undefined;
    const cleaned = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleaned);
    expect(cleaned.defaultPrevented).toBe(false);
  });
});
