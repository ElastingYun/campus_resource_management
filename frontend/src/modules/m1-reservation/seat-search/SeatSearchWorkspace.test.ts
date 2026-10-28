import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import SeatSearchWorkspace from "./SeatSearchWorkspace.vue";
import { createPrototypeSeatSearchGateway } from "./prototype";
import { createUnconfiguredSeatSearchGateway } from "./gateway";
import { businessDate, SearchError } from "./models";
import type { SearchResult, SeatSearchGateway } from "./models";

const wrappers: VueWrapper[] = [];
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount());
  wrappers.length = 0;
});
async function setup(
  gateway: SeatSearchGateway = createPrototypeSeatSearchGateway(),
) {
  const wrapper = mount(SeatSearchWorkspace, { props: { gateway } });
  wrappers.push(wrapper);
  await flushPromises();
  return { wrapper, gateway };
}
async function submit(wrapper: VueWrapper) {
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("B student seat search", () => {
  it("shows explicit synthetic scope, all restriction reasons and an unknown state", async () => {
    const { wrapper } = await setup();
    await submit(wrapper);
    expect(wrapper.text()).toContain("合成数据演示");
    expect(wrapper.findAll(".seat-card")).toHaveLength(4);
    expect(wrapper.findAll('[data-status="available"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("整教室审批占用");
    expect(wrapper.text()).toContain("教室维修中");
    expect(wrapper.text()).toContain("状态未知");
    expect(wrapper.text()).toContain("预约提交待接入");
    expect(wrapper.text()).not.toContain("future_status");
  });
  it("passes the chosen whole-hour slot and outlet without inventing policy", async () => {
    const { wrapper, gateway } = await setup();
    const search = vi.spyOn(gateway, "search");
    await wrapper.get("#search-date").setValue("2032-04-12");
    await wrapper.get("#search-hour").setValue("14");
    await wrapper.get("#search-hours").setValue(3);
    await wrapper.get("#search-outlet").setValue("fixed");
    await submit(wrapper);
    expect(search.mock.calls[0]?.[0]).toEqual({
      date: "2032-04-12",
      hour: 14,
      hours: 3,
      outlet: "fixed",
      roomId: "",
      onlyAvailable: false,
    });
    expect(wrapper.findAll(".seat-card")).toHaveLength(2);
    expect(wrapper.get(".result-heading").text()).toContain("14:00");
  });
  it("builds room filters only after a query and filters within returned rooms", async () => {
    const { wrapper, gateway } = await setup();
    expect(wrapper.findAll("#search-room option")).toHaveLength(1);
    await submit(wrapper);
    expect(wrapper.findAll("#search-room option")).toHaveLength(3);
    const search = vi.spyOn(gateway, "search");
    await wrapper.get("#search-room").setValue("2");
    await submit(wrapper);
    expect(search.mock.calls[0]?.[0].roomId).toBe("2");
    expect(wrapper.findAll(".seat-card")).toHaveLength(2);
  });
  it("clears the previous snapshot as soon as conditions change", async () => {
    const { wrapper } = await setup();
    await submit(wrapper);
    expect(wrapper.find(".search-results").exists()).toBe(true);
    await wrapper.get("#search-hours").setValue(2);
    expect(wrapper.find(".search-results").exists()).toBe(false);
  });
  it("filters only available seats and distinguishes a successful empty result", async () => {
    const { wrapper } = await setup();
    await wrapper.get('input[type="checkbox"]').setValue(true);
    await submit(wrapper);
    expect(wrapper.findAll(".seat-card")).toHaveLength(1);
    await wrapper.get("#search-outlet").setValue("rail");
    await submit(wrapper);
    expect(wrapper.findAll(".seat-card")).toHaveLength(0);
    expect(wrapper.text()).toContain("没有符合条件的座位");
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  });
  it("validates hours against the loaded limit before sending a query", async () => {
    const gateway = createPrototypeSeatSearchGateway();
    gateway.loadSettings = async () => ({ maxHours: 2, bookingHorizonDays: 5 });
    const search = vi.spyOn(gateway, "search");
    const { wrapper } = await setup(gateway);
    await wrapper.get("#search-hours").setValue(3);
    await submit(wrapper);
    expect(wrapper.get('[role="alert"]').text()).toContain("1–2 小时");
    expect(search).not.toHaveBeenCalled();
  });
  it("leaves the unconfigured page disabled with no synthetic data or service request", async () => {
    const gateway = createUnconfiguredSeatSearchGateway();
    const load = vi.spyOn(gateway, "loadSettings");
    const { wrapper } = await setup(gateway);
    await submit(wrapper);
    expect(wrapper.text()).toContain("座位查询尚未接入");
    expect(
      (wrapper.get('button[type="submit"]').element as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(wrapper.findAll(".seat-card")).toHaveLength(0);
    expect(load).not.toHaveBeenCalled();
  });
  it("retries a failed rules read before enabling search", async () => {
    const gateway = createPrototypeSeatSearchGateway();
    const original = gateway.loadSettings;
    gateway.loadSettings = vi
      .fn()
      .mockRejectedValueOnce(new SearchError("请先登录"))
      .mockImplementation(original);
    const { wrapper } = await setup(gateway);
    expect(wrapper.get('[role="alert"]').text()).toContain("请先登录");
    expect(
      (wrapper.get("fieldset").element as HTMLFieldSetElement).disabled,
    ).toBe(true);
    await wrapper.get('[role="alert"] button').trigger("click");
    await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(
      (wrapper.get("fieldset").element as HTMLFieldSetElement).disabled,
    ).toBe(false);
  });
  it("shows query failures with no stale or fabricated results", async () => {
    const { wrapper, gateway } = await setup();
    await submit(wrapper);
    gateway.search = async () => {
      throw new Error("secret database diagnostic");
    };
    await submit(wrapper);
    expect(wrapper.get('[role="alert"]').text()).toContain("暂时不可用");
    expect(wrapper.text()).not.toContain("secret database diagnostic");
    expect(wrapper.find(".search-results").exists()).toBe(false);
    expect(wrapper.findAll("#search-room option")).toHaveLength(1);
  });
  it("ignores an old response even if the transport does not honour abort", async () => {
    const gateway = createPrototypeSeatSearchGateway();
    const first = deferred<SearchResult>(),
      second = deferred<SearchResult>();
    const result = await gateway.search({
      date: "2032-04-12",
      hour: 9,
      hours: 1,
      outlet: "",
      roomId: "",
      onlyAvailable: false,
    });
    const search = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    gateway.search = search;
    const { wrapper } = await setup(gateway);
    await submit(wrapper);
    await submit(wrapper);
    expect(search).toHaveBeenCalledTimes(1);
    await wrapper.get("#search-hour").setValue("10");
    expect((search.mock.calls[0]?.[1] as AbortSignal).aborted).toBe(true);
    await submit(wrapper);
    second.resolve({ ...result, seats: [] });
    await flushPromises();
    expect(wrapper.text()).toContain("没有符合条件的座位");
    first.resolve(result);
    await flushPromises();
    expect(wrapper.findAll(".seat-card")).toHaveLength(0);
    expect(wrapper.text()).toContain("没有符合条件的座位");
  });
  it("formats the initial date in the configured business timezone", () => {
    expect(
      businessDate(new Date("2032-04-12T18:30:00Z"), "Asia/Shanghai"),
    ).toBe("2032-04-13");
    expect(
      businessDate(new Date("2032-04-12T18:30:00Z"), "America/Los_Angeles"),
    ).toBe("2032-04-12");
  });
});
