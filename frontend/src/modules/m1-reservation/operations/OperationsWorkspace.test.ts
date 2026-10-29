import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import { deferred } from "../booking/fixtures.test-helper";
import { createPrototypeOperationsGateway } from "./prototype";
import { createUnconfiguredOperationsGateway } from "./gateway";
import OperationsWorkspace from "./OperationsWorkspace.vue";
import type { OperationsGateway, UsageReport } from "./models";
const wrappers = new Set<VueWrapper>();
afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount();
  wrappers.clear();
  vi.useRealTimers();
});
function button(wrapper: VueWrapper, name: string) {
  const item = wrapper.findAll("button").find((node) => node.text() === name);
  if (!item) throw new Error(name);
  return item;
}
async function view(gateway: OperationsGateway) {
  const wrapper = mount(OperationsWorkspace, {
    props: { gateway, businessTimeZone: "Asia/Shanghai" },
  });
  wrappers.add(wrapper);
  await flushPromises();
  return wrapper;
}
describe("B-06 operations behavior and room-code privacy", () => {
  it("does not request data automatically; displays only returned metrics and source scope", async () => {
    const gateway = createPrototypeOperationsGateway(),
      usage = vi.spyOn(gateway, "usage"),
      code = vi.spyOn(gateway, "roomCode"),
      wrapper = await view(gateway);
    expect(usage).not.toHaveBeenCalled();
    expect(code).not.toHaveBeenCalled();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get("table").text()).toContain("5.00%");
    await wrapper.get('[inputmode="numeric"]').setValue("2");
    await button(wrapper, "查询来源轨迹").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("物业报修");
    expect(wrapper.text()).toContain("整室范围");
    expect(code).not.toHaveBeenCalled();
  });
  it("separates code permission from operations permission without issuing forbidden reads", async () => {
    const gateway = createPrototypeOperationsGateway();
    gateway.capabilities = () => ({ operations: false, roomCode: true });
    const usage = vi.spyOn(gateway, "usage"),
      wrapper = await view(gateway);
    expect(button(wrapper, "查询汇总").attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit");
    expect(usage).not.toHaveBeenCalled();
    await wrapper.get('[inputmode="numeric"]').setValue("2");
    await button(wrapper, "获取当前教室码").trigger("click");
    await flushPromises();
    expect(wrapper.get(".code-display").text()).toContain("123456");
  });
  it("hides the code on expiry and does not refresh it automatically", async () => {
    vi.useFakeTimers();
    const gateway = createPrototypeOperationsGateway(),
      read = vi.spyOn(gateway, "roomCode"),
      wrapper = await view(gateway);
    await wrapper.get('[inputmode="numeric"]').setValue("2");
    await button(wrapper, "获取当前教室码").trigger("click");
    await flushPromises();
    expect(wrapper.find(".code-display").exists()).toBe(true);
    await vi.advanceTimersByTimeAsync(60001);
    expect(wrapper.find(".code-display").exists()).toBe(false);
    expect(wrapper.text()).toContain("已过期");
    expect(read).toHaveBeenCalledTimes(1);
  });
  it("clears the code on account or permission changes", async () => {
    const actor = ref("A"),
      allowed = ref(true),
      gateway = createPrototypeOperationsGateway();
    gateway.currentActorId = () => actor.value;
    gateway.capabilities = () => ({
      operations: true,
      roomCode: allowed.value,
    });
    const wrapper = await view(gateway);
    await wrapper.get('[inputmode="numeric"]').setValue("2");
    await button(wrapper, "获取当前教室码").trigger("click");
    await flushPromises();
    actor.value = "B";
    await flushPromises();
    expect(wrapper.find(".code-display").exists()).toBe(false);
    await button(wrapper, "获取当前教室码").trigger("click");
    await flushPromises();
    allowed.value = false;
    await flushPromises();
    expect(wrapper.find(".code-display").exists()).toBe(false);
    expect(
      button(wrapper, "获取当前教室码").attributes("disabled"),
    ).toBeDefined();
  });
  it("cancels stale queries on input change and discards their responses", async () => {
    const gateway = createPrototypeOperationsGateway(),
      held = deferred<UsageReport>();
    gateway.usage = vi.fn().mockReturnValue(held.promise);
    const wrapper = await view(gateway);
    await wrapper.get("form").trigger("submit");
    const signal = vi.mocked(gateway.usage).mock.calls[0]?.[2];
    await wrapper.get('input[type="date"]').setValue("2032-04-13");
    expect(signal?.aborted).toBe(true);
    held.resolve({ date: "2032-04-12", rooms: [] });
    await flushPromises();
    expect(wrapper.find(".table-scroll").exists()).toBe(false);
  });
  it("clears code through actual unmount and return", async () => {
    const gateway = createPrototypeOperationsGateway(),
      read = vi.spyOn(gateway, "roomCode"),
      first = await view(gateway);
    await first.get('[inputmode="numeric"]').setValue("2");
    await button(first, "获取当前教室码").trigger("click");
    await flushPromises();
    first.unmount();
    wrappers.delete(first);
    const returned = await view(gateway);
    expect(returned.find(".code-display").exists()).toBe(false);
    expect(read).toHaveBeenCalledTimes(1);
  });
  it("stays closed without configuration and presents no synthetic fallback", async () => {
    const gateway = createUnconfiguredOperationsGateway(),
      read = vi.spyOn(gateway, "usage"),
      wrapper = await view(gateway);
    expect(wrapper.text()).toContain("尚未接入");
    await wrapper.get("form").trigger("submit");
    expect(read).not.toHaveBeenCalled();
    expect(wrapper.find("table").exists()).toBe(false);
  });
});
