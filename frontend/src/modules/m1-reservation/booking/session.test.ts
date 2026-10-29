import { describe, expect, it, vi } from "vitest";
import { createBookingSession, protectBookingSession } from "./session";
import { BookingError } from "./models";
import type { BookingGateway, ReservationReceipt } from "./models";
import { deferred, receipt, selection } from "./fixtures.test-helper";

function setup() {
  let actor: string | null = "subject-a";
  const gateway: BookingGateway = {
    mode: "live",
    currentActorId: () => actor,
    create: vi.fn().mockResolvedValue(receipt()),
    read: vi.fn().mockResolvedValue(receipt()),
  };
  const key = vi.fn(() => crypto.randomUUID());
  const session = createBookingSession(gateway, key);
  return {
    gateway,
    key,
    session,
    actor: (value: string | null) => {
      actor = value;
    },
  };
}
describe("application-owned booking recovery", () => {
  it("returns the same unknown intent and original key when a view acquires it again", async () => {
    const { gateway, key, session } = setup();
    gateway.create = vi
      .fn()
      .mockRejectedValueOnce(new BookingError("unknown", true))
      .mockResolvedValueOnce(receipt());
    const first = session.current!;
    first.open(selection());
    await first.confirm();
    const returned = session.current!;
    expect(returned).toBe(first);
    expect(session.pending).toBe(true);
    await returned.recover();
    expect(vi.mocked(gateway.create).mock.calls[1]?.[0]).toBe(
      vi.mocked(gateway.create).mock.calls[0]?.[0],
    );
    expect(key).toHaveBeenCalledTimes(1);
    expect(session.pending).toBe(false);
  });
  it("retains the known ID across view acquisition and only GETs during recovery", async () => {
    const { gateway, session } = setup();
    gateway.read = vi
      .fn()
      .mockRejectedValueOnce(new BookingError("unavailable"))
      .mockResolvedValueOnce(receipt());
    session.current!.open(selection());
    await session.current!.confirm();
    await session.current!.recover();
    expect(gateway.create).toHaveBeenCalledTimes(1);
    expect(gateway.read).toHaveBeenCalledTimes(2);
  });
  it("separates actors and never lets a new actor open or replay the old flow", async () => {
    const { gateway, session, actor } = setup();
    gateway.create = vi
      .fn()
      .mockRejectedValueOnce(new BookingError("unknown", true))
      .mockResolvedValue(receipt());
    const first = session.current!;
    first.open(selection());
    await first.confirm();
    actor("subject-b");
    const second = session.current!;
    expect(second).not.toBe(first);
    expect(second.state.phase).toBe("idle");
    expect(first.visibleReceipt).toBeNull();
    await first.recover();
    expect(gateway.create).toHaveBeenCalledTimes(1);
    second.open(selection());
    await second.confirm();
    expect(vi.mocked(gateway.create).mock.calls[1]?.[0].actorId).toBe(
      "subject-b",
    );
    actor("subject-a");
    expect(session.current).toBe(first);
    await session.current!.recover();
    expect(vi.mocked(gateway.create).mock.calls[2]?.[0]).toBe(
      vi.mocked(gateway.create).mock.calls[0]?.[0],
    );
  });
  it("does not bind a stale unopened flow to a different account", () => {
    const { session, actor, gateway } = setup();
    const first = session.current!;
    actor("subject-b");
    expect(first.open(selection())).toBe(false);
    expect(gateway.create).not.toHaveBeenCalled();
  });
  it("retains outstanding work while clearing only settled accounts", async () => {
    const { gateway, session, actor } = setup();
    gateway.create = vi
      .fn()
      .mockRejectedValueOnce(new BookingError("unknown", true))
      .mockResolvedValue(receipt());
    const first = session.current!;
    first.open(selection());
    await first.confirm();
    actor("subject-b");
    const second = session.current!;
    second.open(selection());
    await second.confirm();
    session.clearSettled();
    expect(session.pending).toBe(true);
    expect(session.current).not.toBe(second);
    actor(null);
    expect(session.current).toBeNull();
    expect(session.pending).toBe(true);
    actor("subject-a");
    expect(session.current).toBe(first);
  });
  it("can interrupt an in-flight request without discarding its intent", async () => {
    const { session, gateway, key } = setup();
    const held = deferred<ReservationReceipt>();
    gateway.create = vi
      .fn()
      .mockReturnValueOnce(held.promise)
      .mockResolvedValueOnce(receipt());
    const first = session.current!;
    first.open(selection());
    const request = first.confirm();
    session.interruptPending();
    expect(first.state.phase).toBe("unknown");
    expect(vi.mocked(gateway.create).mock.calls[0]?.[1]?.aborted).toBe(true);
    held.resolve(receipt());
    await request;
    await session.current!.recover();
    expect(key).toHaveBeenCalledTimes(1);
    expect(first.state.phase).toBe("resolved");
  });
  it("protects full-page unload even when no booking view is mounted", async () => {
    const { session, gateway } = setup();
    gateway.create = vi
      .fn()
      .mockRejectedValueOnce(new BookingError("unknown", true))
      .mockResolvedValueOnce(receipt());
    const cleanup = protectBookingSession(session);
    try {
      session.current!.open(selection());
      await session.current!.confirm();
      const pending = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(pending);
      expect(pending.defaultPrevented).toBe(true);
      await session.current!.recover();
      const settled = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(settled);
      expect(settled.defaultPrevented).toBe(false);
    } finally {
      cleanup();
    }
  });
});
