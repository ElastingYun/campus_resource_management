import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import SeatSearchWorkspace from "../seat-search/SeatSearchWorkspace.vue";
import { createPrototypeSeatSearchGateway } from "../seat-search/prototype";
import { createPrototypeBookingGateway } from "./prototype";
import { BookingError } from "./models";
import type { BookingGateway } from "./models";
const wrappers: VueWrapper[] = [];
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount());
  wrappers.length = 0;
});
async function setup(bookingGateway?: BookingGateway) {
  const wrapper = mount(SeatSearchWorkspace, {
    props: {
      gateway: createPrototypeSeatSearchGateway(),
      ...(bookingGateway ? { bookingGateway } : {}),
    },
  });
  wrappers.push(wrapper);
  await flushPromises();
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  return wrapper;
}
function button(wrapper: VueWrapper, text: string) {
  const target = wrapper.findAll("button").find((item) => item.text() === text);
  if (!target) throw new Error("missing button: " + text);
  return target;
}
describe("B search to booking workspace", () => {
  it("keeps booking closed when a live query gateway has no booking configuration", async () => {
    const query = createPrototypeSeatSearchGateway();
    query.mode = "live"; // Synthetic read fixture representing a configured query boundary.
    const wrapper = mount(SeatSearchWorkspace, { props: { gateway: query } });
    wrappers.push(wrapper);
    await flushPromises();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("预约提交待接入");
    expect(wrapper.findAll(".seat-card button:disabled")).toHaveLength(4);
    expect(wrapper.find(".booking-panel").exists()).toBe(false);
  });
  it("confirms a selected synthetic seat then shows the verified receipt", async () => {
    const wrapper = await setup();
    expect(wrapper.findAll(".seat-card button:disabled")).toHaveLength(3);
    await wrapper.get('[aria-label="预约 A101 01 号座位"]').trigger("click");
    expect(wrapper.get(".booking-panel").text()).toContain("确认预约");
    expect(
      (wrapper.get("fieldset").element as HTMLFieldSetElement).disabled,
    ).toBe(true);
    await button(wrapper, "确认预约").trigger("click");
    await flushPromises();
    expect(wrapper.get(".receipt").text()).toContain("合成预约 #1 · 待签到");
    expect(wrapper.text()).toContain("数据仅保存在页面内存");
    await button(wrapper, "返回查询").trigger("click");
    expect(wrapper.find(".search-results").exists()).toBe(false);
    expect(
      (wrapper.get("fieldset").element as HTMLFieldSetElement).disabled,
    ).toBe(false);
  });
  it("protects an uncertain submission and recovers a write whose response was lost", async () => {
    const gateway = createPrototypeBookingGateway();
    const actual = gateway.create;
    gateway.create = vi
      .fn()
      .mockImplementationOnce(
        async (...args: Parameters<BookingGateway["create"]>) => {
          await actual(...args);
          throw new BookingError("提交结果尚未确认", true);
        },
      )
      .mockImplementation(actual);
    const wrapper = await setup(gateway);
    await wrapper.get('[aria-label="预约 A101 01 号座位"]').trigger("click");
    await button(wrapper, "确认预约").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("预约结果待核对");
    expect(wrapper.emitted("bookingPending")?.at(-1)).toEqual([true]);
    expect(
      (button(wrapper, "返回查询").element as HTMLButtonElement).disabled,
    ).toBe(true);
    const leave = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(true);
    await wrapper.get('a[href="#"]').trigger("click");
    expect(wrapper.text()).toContain("请先核对原预约结果，再离开");
    await button(wrapper, "核对原预约结果").trigger("click");
    await flushPromises();
    expect(wrapper.get(".receipt").text()).toContain("合成预约 #1");
    expect(wrapper.emitted("bookingPending")?.at(-1)).toEqual([false]);
    const calls = vi.mocked(gateway.create).mock.calls;
    expect(calls[0]?.[0]).toBe(calls[1]?.[0]);
  });
  it("never sends a real write using synthetic search results", async () => {
    const gateway = createPrototypeBookingGateway();
    gateway.mode = "live";
    const create = vi.spyOn(gateway, "create");
    const wrapper = await setup(gateway);
    expect(wrapper.text()).toContain("预约提交待接入");
    expect(wrapper.findAll(".seat-card button:disabled")).toHaveLength(4);
    await wrapper.get('[aria-label="预约 A101 01 号座位"]').trigger("click");
    expect(create).not.toHaveBeenCalled();
    expect(wrapper.find(".booking-panel").exists()).toBe(false);
  });
  it("shows the current cancelled state instead of claiming an active booking", async () => {
    const gateway = createPrototypeBookingGateway();
    const read = gateway.read;
    gateway.read = async (...args) => ({
      ...(await read(...args)),
      status: "cancelled",
      cancelledAt: new Date().toISOString(),
      cancelReason: "restricted",
    });
    const wrapper = await setup(gateway);
    await wrapper.get('[aria-label="预约 A101 01 号座位"]').trigger("click");
    await button(wrapper, "确认预约").trigger("click");
    await flushPromises();
    expect(wrapper.get(".receipt").text()).toContain("已取消");
    expect(wrapper.get(".receipt").text()).toContain("请以当前状态为准");
    expect(wrapper.get(".receipt").text()).not.toContain("待签到");
  });
  it("hides pending booking details if the current account changes", async () => {
    const actor = ref("prototype-student");
    const gateway = createPrototypeBookingGateway();
    gateway.currentActorId = () => actor.value;
    gateway.create = vi
      .fn()
      .mockRejectedValue(new BookingError("结果未知", true));
    const wrapper = await setup(gateway);
    await wrapper.get('[aria-label="预约 A101 01 号座位"]').trigger("click");
    await button(wrapper, "确认预约").trigger("click");
    await flushPromises();
    actor.value = "another-account";
    await flushPromises();
    expect(wrapper.get(".booking-panel").text()).toContain("原预约信息已隐藏");
    expect(wrapper.get(".booking-panel").text()).not.toContain("A101");
    expect(
      (button(wrapper, "核对原预约结果").element as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
