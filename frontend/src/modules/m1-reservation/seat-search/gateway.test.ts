import { describe, expect, it, vi } from "vitest";
import { createHttpSeatSearchGateway } from "./gateway";
import type { SeatQuery } from "./models";

const query: SeatQuery = {
  date: "2032-04-12",
  hour: 9,
  hours: 2,
  outlet: "",
  roomId: "",
  onlyAvailable: false,
};
const payload = () => ({
  start_at: "2032-04-12T09:00:00+08:00",
  end_at: "2032-04-12T11:00:00+08:00",
  hours: 2,
  seats: [
    {
      seat_id: 1,
      seat_code: "01",
      room_id: 2,
      room_code: "A101",
      room_name: "示例教室",
      outlet_type: "fixed",
      available: true,
      reasons: [] as { code: string }[],
    },
  ],
});
async function setup(data: unknown = payload()) {
  const request = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(
      Response.json({ max_hours: 6, booking_horizon_days: 8 }),
    )
    .mockResolvedValueOnce(Response.json(data));
  const gateway = createHttpSeatSearchGateway({
    businessTimeZone: "Asia/Shanghai",
    getAccessToken: () => "synthetic-session-token",
    request,
  });
  await gateway.loadSettings();
  return { gateway, request };
}

describe("B seat search HTTP adapter", () => {
  it("reads server limits and sends only the agreed query parameters with no identity fabrication", async () => {
    const { gateway, request } = await setup();
    const result = await gateway.search({
      ...query,
      roomId: "2",
      outlet: "fixed",
      onlyAvailable: true,
    });
    const url = new URL(String(request.mock.calls[1]?.[0]), "http://localhost");
    expect(url.pathname).toBe("/api/v1/m1/seats/availability");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      start_at: "2032-04-12T09:00:00",
      hours: "2",
      room_id: "2",
      outlet_type: "fixed",
      only_available: "true",
    });
    expect(result.seats[0]).toMatchObject({
      id: "1",
      roomId: "2",
      status: "available",
    });
    for (const [, options] of request.mock.calls) {
      expect(options).toMatchObject({
        method: "GET",
        credentials: "same-origin",
        mode: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer synthetic-session-token",
        },
      });
      expect(options?.body).toBeUndefined();
    }
  });
  it("uses configured limits rather than assuming four hours", async () => {
    const data = {
      ...payload(),
      hours: 6,
      end_at: "2032-04-12T15:00:00+08:00",
    };
    const { gateway } = await setup(data);
    await expect(gateway.search({ ...query, hours: 6 })).resolves.toMatchObject(
      { hours: 6 },
    );
  });
  it("retains decimal-string BIGINTs without converting them to JavaScript numbers", async () => {
    const data = payload();
    const seat = { ...data.seats[0], seat_id: "9007199254740993" };
    const { gateway } = await setup({ ...data, seats: [seat] });
    expect((await gateway.search(query)).seats[0]?.id).toBe("9007199254740993");
  });
  it.each([
    { seat_id: Number.MAX_SAFE_INTEGER + 1 },
    { available: "true" },
    { reasons: null },
    { outlet_type: "wireless" },
    { outlet_type: ["fixed"] },
    { room_id: 0 },
  ])("rejects malformed or unsafe seat fields: %j", async (changes) => {
    const data = payload();
    Object.assign(data.seats[0]!, changes);
    const { gateway } = await setup(data);
    await expect(gateway.search(query)).rejects.toThrow("数据不完整");
  });
  it.each([
    { available: true, reasons: [{ code: "m3_repair" }] },
    { available: false, reasons: [] },
    { available: true, reasons: [{ code: "future_status" }] },
    { available: false, reasons: [{ code: "constructor" }] },
  ])(
    "marks contradictory or unknown availability as unknown: %j",
    async (changes) => {
      const data = payload();
      Object.assign(data.seats[0]!, changes);
      const { gateway } = await setup(data);
      expect((await gateway.search(query)).seats[0]?.status).toBe("unknown");
    },
  );
  it("retains all known simultaneous reasons without exposing source IDs", async () => {
    const data = payload();
    Object.assign(data.seats[0]!, {
      available: false,
      reasons: [
        { code: "m2_approval", source_id: "private" },
        { code: "m3_repair" },
      ],
    });
    const { gateway } = await setup(data);
    const seat = (await gateway.search(query)).seats[0];
    expect(seat).toMatchObject({
      status: "unavailable",
      reasons: ["m2_approval", "m3_repair"],
    });
    expect(JSON.stringify(seat)).not.toContain("private");
  });
  it.each([
    { start_at: "2032-04-12T09:00:00" },
    { end_at: "2032-04-12T12:00:00+08:00" },
    { hours: 1 },
    { start_at: "2032-04-12T09:00:00Z", end_at: "2032-04-12T11:00:00Z" },
  ])(
    "rejects response time that cannot be tied to the requested slot: %j",
    async (changes) => {
      const { gateway } = await setup({ ...payload(), ...changes });
      await expect(gateway.search(query)).rejects.toThrow("数据不完整");
    },
  );
  it("rejects duplicate seat identifiers", async () => {
    const data = payload();
    data.seats.push({ ...data.seats[0]! });
    const { gateway } = await setup(data);
    await expect(gateway.search(query)).rejects.toThrow("数据不完整");
  });
  it("rejects results for another room or outlet", async () => {
    const { gateway } = await setup();
    await expect(gateway.search({ ...query, roomId: "3" })).rejects.toThrow(
      "数据不完整",
    );
    const second = await setup();
    await expect(
      second.gateway.search({ ...query, outlet: "none" }),
    ).rejects.toThrow("数据不完整");
  });
  it.each(["2032-02-30", "not-a-date"])(
    "rejects invalid calendar date %s without a search request",
    async (date) => {
      const { gateway, request } = await setup();
      await expect(gateway.search({ ...query, date })).rejects.toThrow("有效");
      expect(request).toHaveBeenCalledTimes(1);
    },
  );
  it.each([
    [401, "请先登录"],
    [403, "没有查询权限"],
    [422, "查询条件"],
    [503, "暂时不可用"],
  ])("handles HTTP %i safely with no fallback", async (status, message) => {
    const { gateway, request } = await setup();
    request
      .mockReset()
      .mockResolvedValue(
        new Response("private SQL trace", { status: Number(status) }),
      );
    await expect(gateway.search(query)).rejects.toThrow(String(message));
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("does not query when server rules are missing or invalid", async () => {
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ max_hours: 0 }));
    const gateway = createHttpSeatSearchGateway({
      businessTimeZone: "Asia/Shanghai",
      getAccessToken: () => "synthetic-session-token",
      request,
    });
    await expect(gateway.loadSettings()).rejects.toThrow("数据不完整");
    await expect(gateway.search(query)).rejects.toThrow("先读取预约规则");
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("does not reuse stale rules after a failed refresh", async () => {
    const { gateway, request } = await setup();
    request.mockReset().mockResolvedValue(Response.json({ max_hours: 0 }));
    await expect(gateway.loadSettings()).rejects.toThrow("数据不完整");
    await expect(gateway.search(query)).rejects.toThrow("先读取预约规则");
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("reads the current external session for each request and stops after logout", async () => {
    let token: string | null = "synthetic-first-session";
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json({ max_hours: 4, booking_horizon_days: 7 }),
      )
      .mockResolvedValueOnce(Response.json(payload()));
    const gateway = createHttpSeatSearchGateway({
      businessTimeZone: "Asia/Shanghai",
      request,
      getAccessToken: () => token,
    });
    await gateway.loadSettings();
    token = "synthetic-second-session";
    await gateway.search(query);
    expect(request.mock.calls[1]?.[1]?.headers).toMatchObject({
      Authorization: "Bearer synthetic-second-session",
    });
    token = null;
    await expect(gateway.search(query)).rejects.toThrow("请先登录");
    expect(request).toHaveBeenCalledTimes(2);
  });
  it.each([null, "bad\r\ntoken"])(
    "does not transmit missing or malformed session %j",
    async (token) => {
      const request = vi.fn<typeof fetch>();
      const gateway = createHttpSeatSearchGateway({
        businessTimeZone: "Asia/Shanghai",
        request,
        getAccessToken: () => token,
      });
      await expect(gateway.loadSettings()).rejects.toThrow(
        token ? "会话信息无效" : "请先登录",
      );
      expect(request).not.toHaveBeenCalled();
    },
  );
  it("aborts a timed out read without automatically retrying", async () => {
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json({ max_hours: 4, booking_horizon_days: 7 }),
      );
    request.mockImplementationOnce(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          options?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    const gateway = createHttpSeatSearchGateway({
      businessTimeZone: "Asia/Shanghai",
      getAccessToken: () => "synthetic-session-token",
      request,
      timeoutMs: 10,
    });
    await gateway.loadSettings();
    await expect(gateway.search(query)).rejects.toThrow("取消或超时");
    expect(request).toHaveBeenCalledTimes(2);
  });
});
