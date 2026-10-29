import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import { deferred, receipt } from "../booking/fixtures.test-helper";
import type { ReservationReceipt } from "../booking/models";
import { createPrototypeBookingGateway } from "../booking/prototype";
import { createPrototypeSeatSearchGateway } from "../seat-search/prototype";
import SeatSearchWorkspace from "../seat-search/SeatSearchWorkspace.vue";
import MyReservations from "./MyReservations.vue";
import { createCheckinSession } from "./checkin";
import { createPrototypeRecordsGateway } from "./prototype";
import { createUnconfiguredRecordsGateway } from "./gateway";
import { RecordsError } from "./models";
import type { RecordsGateway, ReservationPage } from "./models";

const wrappers = new Set<VueWrapper>();
afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount();
  wrappers.clear();
});
function button(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll("button").find((node) => node.text() === label);
  if (!found) throw new Error(label);
  return found;
}
function records() {
  return new Map([["7", receipt()]]);
}
async function view(
  gateway: RecordsGateway,
  session = createCheckinSession(gateway),
) {
  const wrapper = mount(MyReservations, {
    props: {
      gateway,
      checkinSession: session,
      businessTimeZone: "Asia/Shanghai",
    },
  });
  wrappers.add(wrapper);
  await flushPromises();
  return wrapper;
}
describe("B-05 observable records and check-in views", () => {
  it("hides a retained flow belonging to another configured identity source", async () => {
    const sessionGateway = createPrototypeRecordsGateway(records());
    const session = createCheckinSession(sessionGateway);
    session.current!.open(receipt());
    const gateway = createPrototypeRecordsGateway(records());
    gateway.currentActorId = () => "different-subject";
    gateway.list = vi
      .fn()
      .mockResolvedValue({ items: [], limit: 20, offset: 0 });
    gateway.violations = vi.fn().mockResolvedValue([]);
    const wrapper = await view(gateway, session);
    expect(wrapper.find(".checkin").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("预约 #7");
  });
  it("lists own synthetic records, submits a code and refreshes the checked-in state", async () => {
    const gateway = createPrototypeRecordsGateway(records()),
      check = vi.spyOn(gateway, "checkIn"),
      wrapper = await view(gateway);
    expect(wrapper.text()).toContain("示例教室");
    expect(wrapper.text()).toContain("待签到");
    await wrapper.get('[aria-label="签到预约 7"]').trigger("click");
    await wrapper.get('[name="checkin-code"]').setValue("DEMO");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(check).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("已核实签到成功");
    expect(wrapper.get(".record").text()).toContain("已签到");
    expect(wrapper.find('[name="checkin-code"]').exists()).toBe(false);
  });
  it("clears the entered code after a rejected attempt and allows correcting it", async () => {
    const wrapper = await view(createPrototypeRecordsGateway(records()));
    await wrapper.get('[aria-label="签到预约 7"]').trigger("click");
    await wrapper.get("input").setValue("incorrect");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("演示码为 DEMO");
    expect((wrapper.get("input").element as HTMLInputElement).value).toBe("");
    await wrapper.get("input").setValue("DEMO");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("已核实签到成功");
  });
  it("uses actual pages, filters from offset zero and does not invent a total", async () => {
    const values = new Map(
      Array.from({ length: 21 }, (_, index) => [
        String(index + 1),
        { ...receipt(), id: String(index + 1) },
      ]),
    );
    const gateway = createPrototypeRecordsGateway(values),
      list = vi.spyOn(gateway, "list"),
      wrapper = await view(gateway);
    expect(wrapper.findAll(".record")).toHaveLength(20);
    await button(wrapper, "下一页").trigger("click");
    await flushPromises();
    expect(wrapper.findAll(".record")).toHaveLength(1);
    expect(wrapper.text()).toContain("第 2 页");
    expect(button(wrapper, "下一页").attributes("disabled")).toBeDefined();
    await wrapper.get("select").setValue("checked_in");
    await flushPromises();
    expect(list.mock.calls.at(-1)?.[0]).toEqual({
      status: "checked_in",
      offset: 0,
      limit: 20,
    });
    expect(wrapper.text()).toContain("本页没有");
    expect(wrapper.text()).not.toContain("共 21");
  });
  it("shows safe failure messages and reloads without falling back to demo records", async () => {
    const gateway = createPrototypeRecordsGateway(records());
    gateway.mode = "live";
    gateway.list = vi
      .fn()
      .mockRejectedValueOnce(new RecordsError("无权读取"))
      .mockResolvedValue({ items: [], limit: 20, offset: 0 });
    const wrapper = await view(gateway);
    expect(wrapper.get('[role="alert"]').text()).toBe("无权读取");
    expect(wrapper.findAll(".record")).toHaveLength(0);
    await button(wrapper, "刷新预约").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("本页没有");
  });
  it("disables live check-in without an application-owned session", async () => {
    const gateway = createPrototypeRecordsGateway(records());
    gateway.mode = "live";
    const wrapper = mount(MyReservations, {
      props: { gateway, businessTimeZone: "Asia/Shanghai" },
    });
    wrappers.add(wrapper);
    await flushPromises();
    expect(
      wrapper.get('[aria-label="签到预约 7"]').attributes("disabled"),
    ).toBeDefined();
    const closed = await view(createUnconfiguredRecordsGateway());
    expect(closed.text()).toContain("预约记录尚未接入");
    expect(closed.findAll(".record")).toHaveLength(0);
  });
  it("clears old account data and code, ignoring a delayed old query", async () => {
    const actor = ref<string | null>("A"),
      gateway = createPrototypeRecordsGateway(records()),
      held = deferred<ReservationPage>();
    gateway.currentActorId = () => actor.value;
    gateway.violations = vi.fn().mockResolvedValue([]);
    gateway.list = vi
      .fn()
      .mockResolvedValueOnce({ items: [receipt()], limit: 20, offset: 0 })
      .mockReturnValueOnce(held.promise)
      .mockResolvedValue({ items: [], limit: 20, offset: 0 });
    const wrapper = await view(gateway);
    await wrapper.get('[aria-label="签到预约 7"]').trigger("click");
    await wrapper.get("input").setValue("private-code");
    await button(wrapper, "刷新预约").trigger("click");
    actor.value = "B";
    await flushPromises();
    expect(wrapper.find(".checkin").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("示例教室");
    held.resolve({ items: [receipt()], limit: 20, offset: 0 });
    await flushPromises();
    expect(wrapper.findAll(".record")).toHaveLength(0);
    actor.value = "A";
    await flushPromises();
    expect((wrapper.get("input").element as HTMLInputElement).value).toBe("");
  });
  it("preserves an unknown write through actual unmount and return, recovering by GET only", async () => {
    const gateway = createPrototypeRecordsGateway(records()),
      check = gateway.checkIn;
    gateway.checkIn = vi
      .fn()
      .mockImplementation(
        async (...args: Parameters<RecordsGateway["checkIn"]>) => {
          await check(...args);
          throw new RecordsError("lost response", true);
        },
      );
    const read = gateway.read;
    gateway.read = vi
      .fn()
      .mockRejectedValueOnce(new RecordsError("offline"))
      .mockImplementation(read);
    const session = createCheckinSession(gateway),
      first = await view(gateway, session);
    await first.get('[aria-label="签到预约 7"]').trigger("click");
    await first.get("input").setValue("DEMO");
    await first.get("form").trigger("submit");
    await flushPromises();
    expect(first.text()).toContain("暂时无法核实签到");
    first.unmount();
    wrappers.delete(first);
    const returned = await view(gateway, session);
    expect(returned.text()).toContain("暂时无法核实签到");
    await button(returned, "查询原预约签到结果").trigger("click");
    await flushPromises();
    expect(returned.text()).toContain("已核实签到成功");
    expect(gateway.checkIn).toHaveBeenCalledTimes(1);
    expect(gateway.read).toHaveBeenCalledTimes(2);
  });
  it("continues an in-flight check-in while its component is absent", async () => {
    const gateway = createPrototypeRecordsGateway(records()),
      check = gateway.checkIn,
      held = deferred<ReservationReceipt>();
    gateway.checkIn = vi.fn().mockReturnValue(held.promise);
    const session = createCheckinSession(gateway),
      first = await view(gateway, session);
    await first.get('[aria-label="签到预约 7"]').trigger("click");
    await first.get("input").setValue("DEMO");
    await first.get("form").trigger("submit");
    first.unmount();
    wrappers.delete(first);
    expect(session.pending).toBe(true);
    held.resolve(await check("7", "DEMO", "prototype-student"));
    await flushPromises();
    const returned = await view(gateway, session);
    expect(returned.text()).toContain("已核实签到成功");
  });
  it("shows only server violation records with no invented score or penalty", async () => {
    const gateway = createPrototypeRecordsGateway();
    gateway.violations = vi.fn().mockResolvedValue([
      {
        id: "1",
        reservationId: "7",
        reason: "no_show",
        occurredAt: "2032-04-12T01:15:00Z",
      },
    ]);
    const wrapper = await view(gateway);
    expect(wrapper.get(".violations").text()).toContain("预约 #7 · 未签到记录");
    expect(wrapper.text()).not.toContain("扣分");
    expect(wrapper.text()).not.toContain("封禁");
  });
  it("shares default demo bookings with the new history tab without changing App.vue", async () => {
    const wrapper = mount(SeatSearchWorkspace, {
      props: { gateway: createPrototypeSeatSearchGateway() },
    });
    wrappers.add(wrapper);
    await flushPromises();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    await wrapper.get('[aria-label="预约 A101 01 号座位"]').trigger("click");
    await button(wrapper, "确认预约").trigger("click");
    await flushPromises();
    await button(wrapper, "我的预约与签到").trigger("click");
    await flushPromises();
    expect(wrapper.get(".record").text()).toContain("预约 #1");
    await wrapper.get('[aria-label="签到预约 1"]').trigger("click");
    await wrapper.get('[name="checkin-code"]').setValue("DEMO");
    await wrapper.get(".checkin form").trigger("submit");
    await flushPromises();
    expect(wrapper.get(".record").text()).toContain("已签到");
  });
  it("does not silently combine an injected demo booking source with unrelated history", async () => {
    const wrapper = mount(SeatSearchWorkspace, {
      props: {
        gateway: createPrototypeSeatSearchGateway(),
        bookingGateway: createPrototypeBookingGateway(),
      },
    });
    wrappers.add(wrapper);
    await flushPromises();
    await button(wrapper, "我的预约与签到").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("预约记录尚未接入");
  });
});
