import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import App from "./App.vue";

const pending = vi.hoisted(() => ({ hasAnyPending: vi.fn(() => false) }));
vi.mock("./modules/m2-approval/c-gateway", () => ({
  createCGateway: () => ({
    mode: "live",
    hasAnyPending: pending.hasAnyPending,
  }),
}));
enableAutoUnmount(afterEach);
afterEach(() => {
  pending.hasAnyPending.mockReturnValue(false);
  window.history.replaceState(null, "", "/");
});
const stubs = {
  M2SessionWorkspace: {
    name: "M2SessionWorkspace",
    props: ["session", "gateway"],
    template: "<div>M2 login</div>",
  },
  M2Workspace: {
    name: "M2Workspace",
    props: ["gateway"],
    template: "<div>M2 prototype</div>",
  },
  SeatSearchWorkspace: {
    name: "SeatSearchWorkspace",
    props: ["gateway"],
    template: "<div>Seat search</div>",
  },
  ResourceWorkspace: {
    name: "ResourceWorkspace",
    props: ["gateway"],
    template: "<div>Resources</div>",
  },
};
async function navigate(hash: string) {
  window.history.replaceState(null, "", `/${hash}`);
  window.dispatchEvent(new Event("hashchange"));
  await nextTick();
}

describe("shared entry integration", () => {
  it("retains B seat search routes and keeps real mode unconfigured", async () => {
    await navigate("#seat-search-prototype");
    const wrapper = mount(App, { global: { stubs } });
    expect(
      wrapper.findComponent({ name: "SeatSearchWorkspace" }).props("gateway")
        .mode,
    ).toBe("prototype");
    await navigate("#seat-search");
    expect(
      wrapper.findComponent({ name: "SeatSearchWorkspace" }).props("gateway")
        .mode,
    ).toBe("unconfigured");
    expect(wrapper.findComponent({ name: "M2SessionWorkspace" }).exists()).toBe(
      false,
    );
  });

  it("retains the same M2 session and gateway after visiting B routes", async () => {
    await navigate("#m2");
    const wrapper = mount(App, { global: { stubs } });
    const original = wrapper
      .findComponent({ name: "M2SessionWorkspace" })
      .props();
    await navigate("#seat-search-prototype");
    await navigate("#m2");
    const restored = wrapper
      .findComponent({ name: "M2SessionWorkspace" })
      .props();
    expect(restored.session).toBe(original.session);
    expect(restored.gateway).toBe(original.gateway);
    await navigate("#m2-prototype");
    expect(
      wrapper.findComponent({ name: "M2Workspace" }).props("gateway").mode,
    ).toBe("prototype");
    expect(wrapper.findComponent({ name: "M2SessionWorkspace" }).exists()).toBe(
      false,
    );
  });

  it("retains B resource routes without a synthetic fallback in real mode", async () => {
    await navigate("#resources-prototype");
    const wrapper = mount(App, { global: { stubs } });
    expect(
      wrapper.findComponent({ name: "ResourceWorkspace" }).props("gateway")
        .mode,
    ).toBe("prototype");
    await navigate("#resources");
    expect(
      wrapper.findComponent({ name: "ResourceWorkspace" }).props("gateway")
        .mode,
    ).toBe("unconfigured");
  });

  it("keeps pending-write exit protection on B routes and removes it on unmount", async () => {
    await navigate("#m2");
    const wrapper = mount(App, { global: { stubs } });
    const safeExit = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(safeExit);
    expect(safeExit.defaultPrevented).toBe(false);
    pending.hasAnyPending.mockReturnValue(true);
    await navigate("#seat-search-prototype");
    const pendingExit = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(pendingExit);
    expect(pendingExit.defaultPrevented).toBe(true);
    wrapper.unmount();
    const cleanExit = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanExit);
    expect(cleanExit.defaultPrevented).toBe(false);
  });
});
