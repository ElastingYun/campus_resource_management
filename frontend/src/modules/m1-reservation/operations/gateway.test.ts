import { describe, expect, it, vi } from "vitest";
import { deferred } from "../booking/fixtures.test-helper";
import {
  CODE_PERMISSION,
  OPS_PERMISSION,
  createHttpOperationsGateway,
} from "./gateway";
import { businessDate } from "../seat-search/models";
const date = "2032-04-12";
const usage = () => ({
  date,
  rooms: [
    {
      room_id: 2,
      room_code: "A101",
      seat_count: 20,
      reservations: { booked: 4, checked_in: 6, cancelled: 1, no_show: 1 },
      checked_in_seat_hours: 12,
      capacity_seat_hours: 240,
      utilization: 0.05,
    },
  ],
});
const event = () => ({
  room_id: 2,
  seat_id: null,
  occurred_at: "2032-04-12T08:00:00+08:00",
  start_at: "2032-04-12T09:00:00+08:00",
  end_at: null,
  source_type: "m3_repair",
  source_id: "synthetic",
  action: "created",
  actor_id: "private-actor-not-for-frontend",
});
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function setup(permissions = [OPS_PERMISSION, CODE_PERMISSION]) {
  let session = { subjectId: "A", accessToken: "synthetic-token", permissions };
  const request = vi.fn<typeof fetch>(),
    gateway = createHttpOperationsGateway({
      getSession: () => session,
      request,
      businessTimeZone: "Asia/Shanghai",
    });
  return {
    gateway,
    request,
    setSession: (value: typeof session) => {
      session = value;
    },
  };
}
describe("B-06 actual candidate read contracts", () => {
  it("requests server metrics without recalculating or granting management access", async () => {
    const { gateway, request } = setup([OPS_PERMISSION]);
    request.mockResolvedValue(response(usage()));
    const report = await gateway.usage(date, "A");
    expect(report.rooms[0]).toMatchObject({
      id: "2",
      checkedInHours: 12,
      capacityHours: 240,
      utilization: 0.05,
    });
    expect(request.mock.calls[0]?.[0]).toBe(
      `/api/v1/m1/ops/usage?date=${date}`,
    );
    expect(request.mock.calls[0]?.[1]).toMatchObject({
      method: "GET",
      redirect: "error",
      cache: "no-store",
      credentials: "same-origin",
    });
    expect(gateway.capabilities()).toEqual({
      operations: true,
      roomCode: false,
    });
    await expect(gateway.roomCode("2", "A")).rejects.toThrow("权限");
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("does not send reads for missing permission, wrong actor or invalid query", async () => {
    const { gateway, request } = setup([]);
    await expect(gateway.usage(date, "A")).rejects.toThrow("权限");
    await expect(gateway.roomCode("2", "B")).rejects.toThrow("原账号");
    await expect(gateway.usage("2032-02-31", "A")).rejects.toThrow("日期");
    await expect(
      gateway.events({ roomId: "../2", seatId: "", limit: 50 }, "A"),
    ).rejects.toThrow();
    expect(request).not.toHaveBeenCalled();
  });
  it.each([
    { ...usage(), date: "2032-04-13" },
    { ...usage(), rooms: [{ ...usage().rooms[0], room_id: 9007199254740992 }] },
    { ...usage(), rooms: [{ ...usage().rooms[0], seat_count: -1 }] },
    { ...usage(), rooms: [{ ...usage().rooms[0], utilization: "5%" }] },
    {
      ...usage(),
      rooms: [
        {
          ...usage().rooms[0],
          reservations: { ...usage().rooms[0]!.reservations, unknown: 1 },
        },
      ],
    },
    { ...usage(), rooms: [usage().rooms[0], usage().rooms[0]] },
  ])("rejects malformed or mismatched metrics %#", async (value) => {
    const { gateway, request } = setup();
    request.mockResolvedValue(response(value));
    await expect(gateway.usage(date, "A")).rejects.toThrow("校验");
  });
  it("keeps room-wide events in a seat trail and never copies actor data", async () => {
    const { gateway, request } = setup();
    request.mockResolvedValue(response([event()]));
    const items = await gateway.events(
      { roomId: "2", seatId: "9007199254740993", limit: 50 },
      "A",
    );
    expect(request.mock.calls[0]?.[0]).toBe(
      "/api/v1/m1/ops/seat-events?room_id=2&limit=50&seat_id=9007199254740993",
    );
    expect(items[0]?.seatId).toBeNull();
    expect(JSON.stringify(items)).not.toContain("private-actor");
  });
  it.each([
    { ...event(), room_id: 3 },
    { ...event(), seat_id: 9 },
    { ...event(), start_at: "bad" },
  ])(
    "rejects an event outside requested scope or with bad time %#",
    async (value) => {
      const { gateway, request } = setup();
      request.mockResolvedValue(response([value]));
      await expect(
        gateway.events({ roomId: "2", seatId: "1", limit: 50 }, "A"),
      ).rejects.toThrow("校验");
    },
  );
  it("fetches only an explicitly requested, authorized and current room code", async () => {
    const { gateway, request } = setup([CODE_PERMISSION]);
    const currentDate = businessDate(new Date(), "Asia/Shanghai");
    request.mockResolvedValue(
      response({
        room_id: "9007199254740993",
        date: currentDate,
        code: "123456",
        valid_until: new Date(
          Date.parse(`${currentDate}T00:00:00+08:00`) + 86400000,
        ).toISOString(),
      }),
    );
    expect((await gateway.roomCode("9007199254740993", "A")).code).toBe(
      "123456",
    );
    expect(request.mock.calls[0]?.[0]).toBe(
      "/api/v1/m1/rooms/9007199254740993/checkin-code",
    );
    await expect(gateway.usage(date, "A")).rejects.toThrow("权限");
    expect(request).toHaveBeenCalledTimes(1);
  });
  it.each([
    { room_id: 3, date, code: "123456", valid_until: "2099-01-01T00:00:00Z" },
    { room_id: 2, date, code: "123456", valid_until: "2000-01-01T00:00:00Z" },
    {
      room_id: 2,
      date,
      code: "secret-body",
      valid_until: "2099-01-01T00:00:00Z",
    },
  ])("rejects mismatched or expired room codes %#", async (value) => {
    const { gateway, request } = setup();
    request.mockResolvedValue(response(value));
    await expect(gateway.roomCode("2", "A")).rejects.toThrow("校验");
  });
  it("drops an in-flight reply after permission revocation", async () => {
    const { gateway, request, setSession } = setup(),
      held = deferred<Response>();
    request.mockReturnValue(held.promise);
    const pending = gateway.usage(date, "A");
    setSession({
      subjectId: "A",
      accessToken: "synthetic-token",
      permissions: [],
    });
    held.resolve(response(usage()));
    await expect(pending).rejects.toThrow("权限已变化");
  });
  it("hides raw errors and never retries a failed read automatically", async () => {
    const { gateway, request } = setup();
    request.mockResolvedValue(response({ secret: "private-server-body" }, 503));
    await expect(gateway.usage(date, "A")).rejects.toThrow("服务暂不可用");
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("keeps code display closed when its business time zone is not configured", async () => {
    const request = vi.fn<typeof fetch>(),
      gateway = createHttpOperationsGateway({
        getSession: () => ({
          subjectId: "A",
          accessToken: "synthetic",
          permissions: [CODE_PERMISSION],
        }),
        request,
      });
    expect(gateway.capabilities().roomCode).toBe(false);
    await expect(gateway.roomCode("2", "A")).rejects.toThrow("时区");
    expect(request).not.toHaveBeenCalled();
  });
  it("aborts a timed-out read once without retry", async () => {
    vi.useFakeTimers();
    try {
      const request = vi
        .fn<typeof fetch>()
        .mockImplementation(
          (_url, options) =>
            new Promise((_resolve, reject) =>
              options?.signal?.addEventListener("abort", () =>
                reject(new Error("aborted")),
              ),
            ),
        );
      const gateway = createHttpOperationsGateway({
        getSession: () => ({
          subjectId: "A",
          accessToken: "synthetic",
          permissions: [OPS_PERMISSION],
        }),
        request,
        timeoutMs: 5,
      });
      const assertion = expect(gateway.usage(date, "A")).rejects.toThrow(
        "中断",
      );
      await vi.advanceTimersByTimeAsync(6);
      await assertion;
      expect(request).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
