import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { deferred, receipt } from "../booking/fixtures.test-helper";
import type { ReservationReceipt } from "../booking/models";
import { createCheckinSession, protectCheckinSession } from "./checkin";
import { RecordsError } from "./models";
import type { RecordsGateway } from "./models";
const checked = (): ReservationReceipt => ({
  ...receipt(),
  status: "checked_in",
  checkedInAt: "2032-04-12T01:00:00Z",
});
function setup() {
  const actor = ref<string | null>("A");
  const gateway: RecordsGateway = {
    mode: "live",
    currentActorId: () => actor.value,
    list: vi.fn(),
    violations: vi.fn(),
    read: vi.fn().mockResolvedValue(checked()),
    checkIn: vi.fn().mockResolvedValue(checked()),
  };
  const session = createCheckinSession(gateway),
    flow = session.current!;
  flow.open(receipt());
  return { actor, gateway, session, flow };
}
describe("B-05 retained check-in outcome", () => {
  it("confirms a successful write by reading the original reservation", async () => {
    const { gateway, flow, session } = setup();
    await flow.submit(" code ");
    expect(gateway.checkIn).toHaveBeenCalledWith("7", "code", "A");
    expect(gateway.read).toHaveBeenCalledWith("7", "A");
    expect(flow.state.phase).toBe("resolved");
    expect(session.pending).toBe(false);
    expect(JSON.stringify(flow.state)).not.toContain('"code"');
  });
  it("blocks duplicate writes while pending", async () => {
    const { gateway, flow } = setup(),
      held = deferred<ReservationReceipt>();
    vi.mocked(gateway.checkIn).mockReturnValue(held.promise);
    const pending = flow.submit("first");
    await flow.submit("second");
    expect(flow.close()).toBe(false);
    expect(gateway.checkIn).toHaveBeenCalledTimes(1);
    held.resolve(checked());
    await pending;
  });
  it("keeps a booked GET uncertain and recovers using GET only", async () => {
    const { gateway, flow, session } = setup();
    vi.mocked(gateway.checkIn).mockRejectedValue(
      new RecordsError("unknown", true),
    );
    vi.mocked(gateway.read)
      .mockResolvedValueOnce(receipt())
      .mockResolvedValueOnce(checked());
    await flow.submit("secret");
    expect(flow.state.phase).toBe("unknown");
    expect(flow.close()).toBe(false);
    session.clearSettled();
    expect(session.current).toBe(flow);
    await flow.submit("secret");
    await flow.recover();
    expect(gateway.checkIn).toHaveBeenCalledTimes(1);
    expect(gateway.read).toHaveBeenCalledTimes(2);
    expect(flow.state.phase).toBe("resolved");
    expect(flow.visibleReceipt?.status).toBe("checked_in");
  });
  it("keeps failed state queries uncertain and rejects mismatched receipts", async () => {
    const { gateway, flow } = setup();
    vi.mocked(gateway.read)
      .mockRejectedValueOnce(new RecordsError("missing"))
      .mockResolvedValueOnce({ ...checked(), seatId: "999" })
      .mockResolvedValueOnce(checked());
    await flow.submit("secret");
    expect(flow.state.phase).toBe("unknown");
    await flow.recover();
    expect(flow.state.phase).toBe("unknown");
    await flow.recover();
    expect(flow.state.phase).toBe("resolved");
    expect(gateway.checkIn).toHaveBeenCalledTimes(1);
  });
  it("allows correcting a definite rejection but not an unknown outcome", async () => {
    const { gateway, flow } = setup();
    vi.mocked(gateway.checkIn).mockRejectedValueOnce(
      new RecordsError("wrong code"),
    );
    await flow.submit("bad");
    expect(flow.state.phase).toBe("rejected");
    expect(gateway.read).not.toHaveBeenCalled();
    await flow.submit("good");
    expect(flow.state.phase).toBe("resolved");
    expect(gateway.checkIn).toHaveBeenCalledTimes(2);
  });
  it("does not report a cancelled or no-show reservation as checked in", async () => {
    const { gateway, flow } = setup();
    vi.mocked(gateway.read).mockResolvedValue({
      ...receipt(),
      status: "no_show",
      cancelledAt: "2032-04-12T01:15:00Z",
    });
    await flow.submit("secret");
    expect(flow.state.phase).toBe("resolved");
    expect(flow.state.message).toContain("未确认签到成功");
  });
  it("isolates actors, refuses old references and restores the original flow", async () => {
    const { actor, gateway, flow, session } = setup(),
      held = deferred<ReservationReceipt>();
    vi.mocked(gateway.checkIn).mockReturnValue(held.promise);
    const pending = flow.submit("secret");
    actor.value = "B";
    expect(flow.visibleReceipt).toBeNull();
    expect(session.current).not.toBe(flow);
    held.resolve(checked());
    await pending;
    expect(flow.state.phase).toBe("unknown");
    expect(gateway.read).not.toHaveBeenCalled();
    await flow.recover();
    expect(gateway.read).not.toHaveBeenCalled();
    actor.value = "A";
    expect(session.current).toBe(flow);
    await flow.recover();
    expect(flow.state.phase).toBe("resolved");
  });
  it("guards full-page unload with no view mounted and removes the listener", async () => {
    const { gateway, flow, session } = setup();
    vi.mocked(gateway.read).mockRejectedValue(new Error("offline"));
    await flow.submit("secret");
    const dispose = protectCheckinSession(session);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    dispose();
    const after = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });
});
