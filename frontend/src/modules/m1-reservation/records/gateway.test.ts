import { describe, expect, it, vi } from "vitest";
import { wireReceipt, deferred } from "../booking/fixtures.test-helper";
import { createHttpRecordsGateway } from "./gateway";
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const query = { status: "" as const, limit: 20, offset: 0 };
function setup() {
  let session: { subjectId: string; accessToken: string } | null = {
    subjectId: "A",
    accessToken: "synthetic-token",
  };
  const request = vi.fn<typeof fetch>();
  const gateway = createHttpRecordsGateway({
    getSession: () => session,
    request,
  });
  return {
    gateway,
    request,
    setSession: (value: typeof session) => {
      session = value;
    },
  };
}
describe("B-05 candidate A HTTP contracts", () => {
  it("uses only own list with status and offset, no invented total", async () => {
    const { gateway, request } = setup();
    request.mockResolvedValue(
      response({ items: [wireReceipt()], limit: 20, offset: 40 }),
    );
    const result = await gateway.list(
      { ...query, status: "booked", offset: 40 },
      "A",
    );
    expect(result.items[0]?.id).toBe("7");
    expect(result).not.toHaveProperty("total");
    expect(request.mock.calls[0]?.[0]).toBe(
      "/api/v1/m1/reservations/me?limit=20&offset=40&status=booked",
    );
    const options = request.mock.calls[0]?.[1];
    expect(options).toMatchObject({
      method: "GET",
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
    });
    expect(options?.headers).toEqual({
      Accept: "application/json",
      Authorization: "Bearer synthetic-token",
    });
  });
  it.each([
    { items: [wireReceipt()], limit: 19, offset: 0 },
    { items: [wireReceipt(), wireReceipt()], limit: 20, offset: 0 },
    {
      items: [{ ...wireReceipt(), id: 9007199254740992 }],
      limit: 20,
      offset: 0,
    },
    {
      items: [{ ...wireReceipt(), status: "future_status" }],
      limit: 20,
      offset: 0,
    },
    {
      items: [{ ...wireReceipt(), start_at: "2032-02-31T09:00:00Z" }],
      limit: 20,
      offset: 0,
    },
    {
      items: [{ ...wireReceipt(), end_at: wireReceipt().start_at }],
      limit: 20,
      offset: 0,
    },
  ])("rejects a malformed page %#", async (payload) => {
    const { gateway, request } = setup();
    request.mockResolvedValue(response(payload));
    await expect(gateway.list(query, "A")).rejects.toThrow("未通过校验");
  });
  it("rejects responses contradicting a status filter", async () => {
    const { gateway, request } = setup();
    request.mockResolvedValue(
      response({ items: [wireReceipt()], limit: 20, offset: 0 }),
    );
    await expect(
      gateway.list({ ...query, status: "checked_in" }, "A"),
    ).rejects.toThrow("校验");
  });
  it("preserves decimal string IDs and validates the requested detail", async () => {
    const { gateway, request } = setup();
    request.mockImplementation(async () =>
      response({ ...wireReceipt(), id: "9007199254740993" }),
    );
    expect((await gateway.read("9007199254740993", "A")).id).toBe(
      "9007199254740993",
    );
    await expect(gateway.read("8", "A")).rejects.toThrow("校验");
  });
  it("submits only the entered code to the original reservation, with no admin-code fetch or replay key", async () => {
    const { gateway, request } = setup();
    request.mockResolvedValue(
      response({
        ...wireReceipt(),
        status: "checked_in",
        checked_in_at: "2032-04-12T01:00:00Z",
      }),
    );
    await gateway.checkIn("7", " 123456 ", "A");
    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0]?.[0]).toBe(
      "/api/v1/m1/reservations/7/check-in",
    );
    expect(request.mock.calls[0]?.[1]?.body).toBe('{"code":"123456"}');
    expect(request.mock.calls[0]?.[1]?.headers).not.toHaveProperty(
      "Idempotency-Key",
    );
  });
  it.each([
    [422, "invalid_checkin_code"],
    [409, "checkin_not_open"],
    [409, "checkin_closed"],
    [401, "INVALID_SESSION"],
  ])("treats known rejection %s/%s as definite", async (status, code) => {
    const { gateway, request } = setup();
    request.mockResolvedValue(response({ error: { code } }, Number(status)));
    await expect(gateway.checkIn("7", "123", "A")).rejects.toMatchObject({
      uncertain: false,
    });
    expect(request).toHaveBeenCalledTimes(1);
  });
  it.each([
    response({}, 503),
    response({ error: { code: "already_checked_in" } }, 409),
    response({}),
    response({ ...wireReceipt(), id: 8 }),
  ])("keeps unconfirmed writes uncertain %#", async (result) => {
    const { gateway, request } = setup();
    request.mockResolvedValue(result);
    await expect(gateway.checkIn("7", "123", "A")).rejects.toMatchObject({
      uncertain: true,
    });
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("does not send invalid IDs, codes, queries or a different actor", async () => {
    const { gateway, request, setSession } = setup();
    await expect(gateway.checkIn("../7", "123", "A")).rejects.toThrow();
    await expect(gateway.checkIn("7", " ", "A")).rejects.toThrow();
    await expect(gateway.list({ ...query, offset: -1 }, "A")).rejects.toThrow();
    setSession({ subjectId: "B", accessToken: "synthetic-token" });
    await expect(gateway.read("7", "A")).rejects.toThrow("原账号");
    setSession(null);
    await expect(gateway.violations("A")).rejects.toThrow();
    expect(request).not.toHaveBeenCalled();
  });
  it("discards an old account response and leaves an in-flight write uncertain", async () => {
    const { gateway, request, setSession } = setup(),
      held = deferred<Response>();
    request.mockReturnValue(held.promise);
    const pending = gateway.checkIn("7", "123", "A");
    setSession({ subjectId: "B", accessToken: "synthetic-token-b" });
    held.resolve(response(wireReceipt()));
    await expect(pending).rejects.toMatchObject({ uncertain: true });
  });
  it("aborts a timed-out write once without retry", async () => {
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
      const gateway = createHttpRecordsGateway({
        getSession: () => ({ subjectId: "A", accessToken: "synthetic" }),
        request,
        timeoutMs: 5,
      });
      const assertion = expect(
        gateway.checkIn("7", "123", "A"),
      ).rejects.toMatchObject({ uncertain: true });
      await vi.advanceTimersByTimeAsync(6);
      await assertion;
      expect(request).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
  it("reads only own violations, preserving server records without penalties", async () => {
    const { gateway, request } = setup();
    request.mockResolvedValue(
      response([
        {
          id: "9",
          reservation_id: 7,
          reason: "no_show",
          occurred_at: "2032-04-12T01:15:00Z",
        },
      ]),
    );
    expect(await gateway.violations("A")).toEqual([
      {
        id: "9",
        reservationId: "7",
        reason: "no_show",
        occurredAt: "2032-04-12T01:15:00Z",
      },
    ]);
    expect(request.mock.calls[0]?.[0]).toBe("/api/v1/m1/violations/me");
    request.mockResolvedValue(
      response([
        { id: 1, reservation_id: 7, reason: "no_show", occurred_at: "bad" },
      ]),
    );
    await expect(gateway.violations("A")).rejects.toThrow("校验");
  });
});
