import { describe, expect, it, vi } from "vitest";
import { createBookingFlow } from "./flow";
import { BookingError } from "./models";
import type { BookingGateway, ReservationReceipt } from "./models";
import { deferred, receipt, selection } from "./fixtures.test-helper";
import { createPrototypeBookingGateway } from "./prototype";

function setup() {
  let actor: string | null = "subject-a";
  const gateway: BookingGateway = {
    mode: "live",
    currentActorId: () => actor,
    create: vi.fn().mockResolvedValue(receipt()),
    read: vi.fn().mockResolvedValue(receipt()),
  };
  const key = vi.fn(() => "b04-original-key");
  const flow = createBookingFlow(gateway, key);
  return {
    gateway,
    key,
    flow,
    actor: (value: string | null) => {
      actor = value;
    },
  };
}
describe("B booking intent and recovery", () => {
  it("does not open an intent without a current actor", () => {
    const { flow, gateway, actor } = setup();
    actor(null);
    expect(flow.open(selection())).toBe(false);
    expect(flow.state.phase).toBe("idle");
    expect(gateway.create).not.toHaveBeenCalled();
  });
  it("freezes the selected slot and confirms the current server state with GET", async () => {
    const { flow, gateway } = setup();
    const original = selection();
    flow.open(original);
    original.seat.id = "99";
    original.startAt = "2033-01-01T00:00:00Z";
    await flow.confirm();
    expect(flow.state.phase).toBe("resolved");
    expect(gateway.create).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "b04-original-key",
        seat: expect.objectContaining({ id: "1" }),
        startAt: selection().startAt,
      }),
      expect.any(AbortSignal),
    );
    expect(gateway.read).toHaveBeenCalledWith(
      "7",
      expect.anything(),
      expect.any(AbortSignal),
    );
    expect(flow.visibleReceipt?.id).toBe("7");
  });
  it("blocks duplicate clicks, closing and a second selection while submitting", async () => {
    const { flow, gateway, key } = setup();
    const pending = deferred<ReservationReceipt>();
    gateway.create = vi.fn().mockReturnValue(pending.promise);
    flow.open(selection());
    const first = flow.confirm();
    await flow.confirm();
    expect(flow.busy).toBe(true);
    expect(flow.close()).toBe(false);
    expect(flow.open(selection())).toBe(false);
    expect(gateway.create).toHaveBeenCalledTimes(1);
    expect(key).toHaveBeenCalledTimes(1);
    pending.resolve(receipt());
    await first;
    expect(flow.state.phase).toBe("resolved");
  });
  it("recovers a lost create response with the identical key and payload", async () => {
    const { flow, gateway, key } = setup();
    gateway.create = vi
      .fn()
      .mockRejectedValueOnce(new BookingError("结果未知", true))
      .mockResolvedValueOnce(receipt());
    flow.open(selection());
    await flow.confirm();
    expect(flow.state.phase).toBe("unknown");
    expect(flow.close()).toBe(false);
    expect(flow.open(selection())).toBe(false);
    await flow.recover();
    const create = vi.mocked(gateway.create);
    expect(create.mock.calls[1]?.[0]).toBe(create.mock.calls[0]?.[0]);
    expect(create.mock.calls[1]?.[0].key).toBe("b04-original-key");
    expect(key).toHaveBeenCalledTimes(1);
    expect(flow.state.phase).toBe("resolved");
  });
  it("uses GET only when creation returned a known ID but verification failed", async () => {
    const { flow, gateway } = setup();
    gateway.read = vi
      .fn()
      .mockRejectedValueOnce(new BookingError("读取失败"))
      .mockResolvedValueOnce(receipt());
    flow.open(selection());
    await flow.confirm();
    expect(flow.state.phase).toBe("unknown");
    await flow.recover();
    expect(gateway.create).toHaveBeenCalledTimes(1);
    expect(gateway.read).toHaveBeenCalledTimes(2);
    expect(flow.state.phase).toBe("resolved");
  });
  it("keeps the original uncertainty even when a recovery attempt is rejected", async () => {
    const { flow, gateway, key } = setup();
    gateway.create = vi
      .fn()
      .mockRejectedValueOnce(new BookingError("未知", true))
      .mockRejectedValueOnce(new BookingError("重新登录"));
    flow.open(selection());
    await flow.confirm();
    await flow.recover();
    expect(flow.state.phase).toBe("unknown");
    expect(flow.close()).toBe(false);
    expect(key).toHaveBeenCalledTimes(1);
  });
  it("allows returning to a fresh query after a definite first rejection", async () => {
    const { flow, gateway } = setup();
    gateway.create = vi
      .fn()
      .mockRejectedValue(new BookingError("座位已被预约"));
    flow.open(selection());
    await flow.confirm();
    expect(flow.state.phase).toBe("rejected");
    expect(flow.close()).toBe(true);
    expect(flow.state.phase).toBe("idle");
    expect(gateway.read).not.toHaveBeenCalled();
  });
  it("binds recovery to the original actor and resumes GET after that actor returns", async () => {
    const { flow, gateway, actor } = setup();
    const pending = deferred<ReservationReceipt>();
    gateway.create = vi.fn().mockReturnValue(pending.promise);
    flow.open(selection());
    const request = flow.confirm();
    actor("subject-b");
    pending.resolve(receipt());
    await request;
    expect(flow.state.phase).toBe("unknown");
    expect(flow.visibleReceipt).toBeNull();
    await flow.recover();
    expect(gateway.read).not.toHaveBeenCalled();
    expect(gateway.create).toHaveBeenCalledTimes(1);
    actor("subject-a");
    await flow.recover();
    expect(gateway.create).toHaveBeenCalledTimes(1);
    expect(gateway.read).toHaveBeenCalledTimes(1);
    expect(flow.visibleReceipt?.id).toBe("7");
  });
  it("rejects a confirmation if the actor changed before any submission", async () => {
    const { flow, gateway, actor, key } = setup();
    flow.open(selection());
    actor("subject-b");
    await flow.confirm();
    expect(flow.state.phase).toBe("rejected");
    expect(gateway.create).not.toHaveBeenCalled();
    expect(key).not.toHaveBeenCalled();
  });
  it("does not show another actor the resolved receipt", async () => {
    const { flow, actor } = setup();
    flow.open(selection());
    await flow.confirm();
    actor("subject-b");
    expect(flow.visibleReceipt).toBeNull();
    expect(flow.actorMatches).toBe(false);
  });
  it("ignores a response arriving after disposal and retains the original intent", async () => {
    const { flow, gateway, key } = setup();
    const pending = deferred<ReservationReceipt>();
    gateway.create = vi
      .fn()
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(receipt());
    flow.open(selection());
    const first = flow.confirm();
    flow.dispose();
    expect(flow.state.phase).toBe("unknown");
    expect(vi.mocked(gateway.create).mock.calls[0]?.[1]?.aborted).toBe(true);
    pending.resolve(receipt());
    await first;
    expect(flow.state.phase).toBe("unknown");
    await flow.recover();
    expect(flow.state.phase).toBe("resolved");
    expect(key).toHaveBeenCalledTimes(1);
  });
  it.each(["unavailable", "unknown"] as const)(
    "does not offer %s seats",
    (status) => {
      const { flow, gateway } = setup();
      const value = selection();
      value.seat.status = status;
      expect(() => flow.open(value)).toThrow("尚未确认");
      expect(gateway.create).not.toHaveBeenCalled();
    },
  );
  it("does not display internal exceptions as messages or fabricate success", async () => {
    const { flow, gateway } = setup();
    gateway.create = vi.fn().mockRejectedValue(new Error("private diagnostic"));
    flow.open(selection());
    await flow.confirm();
    expect(flow.state.phase).toBe("unknown");
    expect(flow.state.message).not.toContain("private diagnostic");
    expect(flow.visibleReceipt).toBeNull();
  });
  it("keeps synthetic replay idempotent and rejects another request for the same seat/slot", async () => {
    const gateway = createPrototypeBookingGateway();
    const original = {
      ...selection(),
      actorId: "prototype-student",
      key: "demo-key",
    };
    const first = await gateway.create(original),
      replay = await gateway.create(original);
    expect(replay.id).toBe(first.id);
    expect((await gateway.read(first.id, original)).status).toBe("booked");
    await expect(
      gateway.create({ ...original, key: "new-demo-key" }),
    ).rejects.toThrow("已被预约");
  });
});
