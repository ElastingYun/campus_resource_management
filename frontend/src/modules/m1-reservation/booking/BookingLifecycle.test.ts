import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import SeatSearchWorkspace from "../seat-search/SeatSearchWorkspace.vue";
import { createPrototypeSeatSearchGateway } from "../seat-search/prototype";
import { createPrototypeBookingGateway } from "./prototype";
import { createBookingSession } from "./session";
import type { BookingSession } from "./session";
import { BookingError } from "./models";
import type { BookingGateway, ReservationReceipt } from "./models";
import { deferred } from "./fixtures.test-helper";
const wrappers = new Set<VueWrapper>();
afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount();
  wrappers.clear();
});
async function view(session: BookingSession) {
  const wrapper = mount(SeatSearchWorkspace, {
    props: {
      gateway: createPrototypeSeatSearchGateway(),
      bookingSession: session,
    },
  });
  wrappers.add(wrapper);
  await flushPromises();
  return wrapper;
}
function remove(wrapper: VueWrapper) {
  wrapper.unmount();
  wrappers.delete(wrapper);
}
function button(wrapper: VueWrapper, name: string) {
  const found = wrapper.findAll("button").find((node) => node.text() === name);
  if (!found) throw new Error(name);
  return found;
}
async function begin(wrapper: VueWrapper) {
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  await wrapper.get('[aria-label="预约 A101 01 号座位"]').trigger("click");
  await button(wrapper, "确认预约").trigger("click");
  await flushPromises();
}
describe("B recovery through actual view destruction", () => {
  it("does not bind a live retained session to synthetic query results", async () => {
    const gateway = createPrototypeBookingGateway();
    gateway.mode = "live";
    const create = vi.spyOn(gateway, "create");
    const session = createBookingSession(gateway);
    const wrapper = await view(session);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("预约提交待接入");
    expect(wrapper.findAll(".seat-card button:disabled")).toHaveLength(4);
    expect(create).not.toHaveBeenCalled();
  });
  it("unmounts and remounts an unknown create with exactly the same intent", async () => {
    const gateway = createPrototypeBookingGateway();
    const create = gateway.create;
    gateway.create = vi
      .fn()
      .mockImplementationOnce(
        async (...args: Parameters<BookingGateway["create"]>) => {
          await create(...args);
          throw new BookingError("unknown", true);
        },
      )
      .mockImplementation(create);
    const session = createBookingSession(gateway);
    const first = await view(session);
    await begin(first);
    expect(first.text()).toContain("预约结果待核对");
    remove(first);
    const returned = await view(session);
    expect(returned.text()).toContain("预约结果待核对");
    await button(returned, "核对原预约结果").trigger("click");
    await flushPromises();
    expect(returned.get(".receipt").text()).toContain("合成预约 #1");
    const calls = vi.mocked(gateway.create).mock.calls;
    expect(calls[1]?.[0]).toBe(calls[0]?.[0]);
  });
  it("keeps the known ID across destruction and does not create a second reservation", async () => {
    const gateway = createPrototypeBookingGateway();
    const create = vi.spyOn(gateway, "create"),
      read = gateway.read;
    gateway.read = vi
      .fn()
      .mockRejectedValueOnce(new BookingError("read failed"))
      .mockImplementation(read);
    const session = createBookingSession(gateway);
    const first = await view(session);
    await begin(first);
    remove(first);
    const returned = await view(session);
    await button(returned, "核对原预约结果").trigger("click");
    await flushPromises();
    expect(create).toHaveBeenCalledTimes(1);
    expect(gateway.read).toHaveBeenCalledTimes(2);
    expect(returned.get(".receipt").text()).toContain("待签到");
  });
  it("finishes an in-flight write while the view is absent, then shows its receipt on return", async () => {
    const gateway = createPrototypeBookingGateway();
    const create = gateway.create,
      held = deferred<ReservationReceipt>();
    gateway.create = vi.fn().mockReturnValue(held.promise);
    const session = createBookingSession(gateway);
    const first = await view(session);
    await begin(first);
    const [intent, signal] = vi.mocked(gateway.create).mock.calls[0]!;
    remove(first);
    expect(signal?.aborted).toBe(false);
    expect(session.pending).toBe(true);
    held.resolve(await create(intent));
    await flushPromises();
    const returned = await view(session);
    expect(returned.get(".receipt").text()).toContain("合成预约 #1");
    expect(gateway.create).toHaveBeenCalledTimes(1);
  });
  it("clears account-scoped query data, hides the old flow, and restores it for the original account", async () => {
    const actor = ref("prototype-student"),
      gateway = createPrototypeBookingGateway(),
      create = gateway.create;
    gateway.currentActorId = () => actor.value;
    gateway.create = vi
      .fn()
      .mockImplementationOnce(
        async (...args: Parameters<BookingGateway["create"]>) => {
          await create(...args);
          throw new BookingError("unknown", true);
        },
      )
      .mockImplementation(create);
    const session = createBookingSession(gateway);
    const wrapper = await view(session);
    await begin(wrapper);
    actor.value = "another-account";
    await flushPromises();
    expect(wrapper.find(".booking-panel").exists()).toBe(false);
    expect(wrapper.find(".search-results").exists()).toBe(false);
    actor.value = "prototype-student";
    await flushPromises();
    expect(wrapper.text()).toContain("预约结果待核对");
    await button(wrapper, "核对原预约结果").trigger("click");
    await flushPromises();
    expect(wrapper.get(".receipt").text()).toContain("合成预约 #1");
  });
  it("requires a retained session before enabling live writes", async () => {
    const query = createPrototypeSeatSearchGateway(),
      gateway = createPrototypeBookingGateway();
    query.mode = "live";
    gateway.mode = "live";
    const create = vi.spyOn(gateway, "create");
    const wrapper = mount(SeatSearchWorkspace, {
      props: { gateway: query, bookingGateway: gateway },
    });
    wrappers.add(wrapper);
    await flushPromises();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("预约提交待接入");
    expect(wrapper.findAll(".seat-card button:disabled")).toHaveLength(4);
    expect(create).not.toHaveBeenCalled();
  });
});
