import { describe, expect, it, vi } from "vitest";
import { createHttpBookingGateway } from "./gateway";
import { createBookingFlow } from "./flow";
import { intent, selection, wireReceipt } from "./fixtures.test-helper";

function setup(data: unknown = wireReceipt(), status = 201) {
  const request = vi
    .fn<typeof fetch>()
    .mockResolvedValue(Response.json(data, { status }));
  const gateway = createHttpBookingGateway({
    getSession: () => ({
      subjectId: "subject-a",
      accessToken: "synthetic-session",
    }),
    request,
  });
  return { request, gateway };
}
describe("B booking HTTP adapter", () => {
  it("recovers through the real adapter using identical POST bytes, then GET", async () => {
    const { gateway, request } = setup();
    request
      .mockReset()
      .mockRejectedValueOnce(new TypeError("response lost"))
      .mockResolvedValueOnce(Response.json(wireReceipt(), { status: 200 }))
      .mockResolvedValueOnce(Response.json(wireReceipt()));
    const flow = createBookingFlow(gateway, () => "original-wire-key");
    flow.open(selection());
    await flow.confirm();
    expect(flow.state.phase).toBe("unknown");
    await flow.recover();
    expect(flow.state.phase).toBe("resolved");
    expect(request.mock.calls.map((call) => call[1]?.method)).toEqual([
      "POST",
      "POST",
      "GET",
    ]);
    expect(request.mock.calls[1]?.[1]?.body).toBe(
      request.mock.calls[0]?.[1]?.body,
    );
    expect(request.mock.calls[1]?.[1]?.headers).toEqual(
      request.mock.calls[0]?.[1]?.headers,
    );
  });
  it("retains a known ID and never POSTs again when the following GET fails", async () => {
    const { gateway, request } = setup();
    request
      .mockReset()
      .mockResolvedValueOnce(Response.json(wireReceipt(), { status: 201 }))
      .mockResolvedValueOnce(
        Response.json({ error: { code: "unavailable" } }, { status: 503 }),
      )
      .mockResolvedValueOnce(Response.json(wireReceipt()));
    const flow = createBookingFlow(gateway, () => "original-wire-key");
    flow.open(selection());
    await flow.confirm();
    expect(flow.state.phase).toBe("unknown");
    await flow.recover();
    expect(flow.state.phase).toBe("resolved");
    expect(request.mock.calls.map((call) => call[1]?.method)).toEqual([
      "POST",
      "GET",
      "GET",
    ]);
  });
  it.each([undefined, "bad\r\ntoken"])(
    "refuses malformed session token %j before sending",
    async (token) => {
      const request = vi.fn<typeof fetch>();
      const gateway = createHttpBookingGateway({
        getSession: () => ({
          subjectId: "subject-a",
          accessToken: token as unknown as string,
        }),
        request,
      });
      await expect(gateway.create(intent())).rejects.toMatchObject({
        uncertain: false,
      });
      expect(request).not.toHaveBeenCalled();
    },
  );
  it("does not submit an already cancelled read/write signal", async () => {
    const { gateway, request } = setup();
    const controller = new AbortController();
    controller.abort();
    await expect(
      gateway.create(intent(), controller.signal),
    ).rejects.toMatchObject({ uncertain: false });
    expect(request).not.toHaveBeenCalled();
  });
  it.each([200, 201])(
    "accepts validated %i create/replay with exact slot, key and external session",
    async (status) => {
      const { request, gateway } = setup(wireReceipt(), status);
      const result = await gateway.create(intent());
      expect(result).toMatchObject({
        id: "7",
        seatId: "1",
        roomId: "2",
        status: "booked",
      });
      expect(request.mock.calls[0]?.[0]).toBe("/api/v1/m1/reservations");
      const options = request.mock.calls[0]?.[1];
      expect(options).toMatchObject({
        method: "POST",
        credentials: "same-origin",
        mode: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: {
          Authorization: "Bearer synthetic-session",
          "Idempotency-Key": "b04-synthetic-key",
        },
      });
      expect(JSON.parse(String(options?.body))).toEqual({
        seat_id: 1,
        start_at: intent().startAt,
        hours: 2,
      });
      expect(request).toHaveBeenCalledTimes(1);
    },
  );
  it("uses GET with no write body or idempotency header for a known ID", async () => {
    const { request, gateway } = setup(wireReceipt(), 200);
    await gateway.read("7", intent());
    expect(request.mock.calls[0]?.[0]).toBe("/api/v1/m1/reservations/7");
    expect(request.mock.calls[0]?.[1]?.method).toBe("GET");
    expect(request.mock.calls[0]?.[1]?.body).toBeUndefined();
    expect(request.mock.calls[0]?.[1]?.headers).not.toHaveProperty(
      "Idempotency-Key",
    );
  });
  it("blocks unsafe numeric request identifiers before sending", async () => {
    const { request, gateway } = setup();
    const original = intent();
    original.seat.id = "9007199254740993";
    await expect(gateway.create(original)).rejects.toMatchObject({
      uncertain: false,
    });
    expect(request).not.toHaveBeenCalled();
  });
  it("can read a lossless decimal-string reservation ID", async () => {
    const { request, gateway } = setup(
      { ...wireReceipt(), id: "9007199254740993" },
      200,
    );
    const result = await gateway.read("9007199254740993", intent());
    expect(result.id).toBe("9007199254740993");
    expect(request.mock.calls[0]?.[0]).toContain("/9007199254740993");
  });
  it.each([
    { seat_id: 99 },
    { room_id: 99 },
    { id: Number.MAX_SAFE_INTEGER + 1 },
    { start_at: "2032-04-12T09:00:00Z" },
    { end_at: "2032-04-12T12:00:00+08:00" },
    { status: "future_status" },
    { checked_in_at: "2032-04-12T09:00:00+08:00" },
    { start_at: "2032-04-12T09:00:00" },
    { created_at: "not-a-date" },
  ])(
    "keeps malformed or unrelated write success uncertain: %j",
    async (changes) => {
      const { request, gateway } = setup({ ...wireReceipt(), ...changes });
      await expect(gateway.create(intent())).rejects.toMatchObject({
        uncertain: true,
      });
      expect(request).toHaveBeenCalledTimes(1);
    },
  );
  it("reads a terminal replay as its actual state without claiming an active booking", async () => {
    const { gateway } = setup(
      {
        ...wireReceipt(),
        status: "cancelled",
        cancelled_at: "2032-04-12T01:00:00Z",
        cancel_reason: "restricted",
      },
      200,
    );
    expect((await gateway.create(intent())).status).toBe("cancelled");
  });
  it.each([
    [409, "seat_conflict", "已被预约"],
    [409, "user_overlap", "已有有效预约"],
    [403, "department_restricted", "准入条件"],
    [401, "unauthenticated", "重新登录"],
    [422, "start_not_in_future", "已经开始"],
  ])(
    "recognizes explicit rejection %i/%s and hides server diagnostics",
    async (status, code, message) => {
      const { request, gateway } = setup(
        { error: { code, message: "private-server-diagnostic" } },
        Number(status),
      );
      const result = gateway.create(intent());
      await expect(result).rejects.toMatchObject({ uncertain: false });
      await expect(result).rejects.toThrow(String(message));
      expect(request).toHaveBeenCalledTimes(1);
    },
  );
  it.each([408, 503, 409])(
    "does not mistake unrecognized HTTP %i for a definite rejected write",
    async (status) => {
      const { gateway } = setup(
        { error: { code: "unrecognized", message: "private" } },
        status,
      );
      await expect(gateway.create(intent())).rejects.toMatchObject({
        uncertain: true,
      });
    },
  );
  it("treats a network failure or timeout as unknown without retry", async () => {
    const { request, gateway } = setup();
    request.mockRejectedValue(new TypeError("private-network-diagnostic"));
    await expect(gateway.create(intent())).rejects.toMatchObject({
      uncertain: true,
    });
    expect(request).toHaveBeenCalledTimes(1);
    const timeoutRequest = vi.fn<typeof fetch>(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          options?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("abort", "AbortError")),
            { once: true },
          );
        }),
    );
    const timed = createHttpBookingGateway({
      getSession: () => ({
        subjectId: "subject-a",
        accessToken: "synthetic-session",
      }),
      request: timeoutRequest,
      timeoutMs: 10,
    });
    await expect(timed.create(intent())).rejects.toMatchObject({
      uncertain: true,
    });
    expect(timeoutRequest).toHaveBeenCalledTimes(1);
  });
  it("does not send or expose a request for the wrong or missing current actor", async () => {
    let subjectId: string | null = "subject-b";
    const request = vi.fn<typeof fetch>();
    const gateway = createHttpBookingGateway({
      getSession: () =>
        subjectId ? { subjectId, accessToken: "synthetic-session" } : null,
      request,
    });
    await expect(gateway.create(intent())).rejects.toMatchObject({
      uncertain: false,
    });
    subjectId = null;
    await expect(gateway.create(intent())).rejects.toMatchObject({
      uncertain: false,
    });
    expect(request).not.toHaveBeenCalled();
  });
  it("does not present a response after a different actor signs in", async () => {
    let actor = "subject-a";
    const request = vi.fn<typeof fetch>().mockImplementation(async () => {
      actor = "subject-b";
      return Response.json(wireReceipt());
    });
    const gateway = createHttpBookingGateway({
      getSession: () => ({
        subjectId: actor,
        accessToken: "synthetic-session",
      }),
      request,
    });
    await expect(gateway.create(intent())).rejects.toMatchObject({
      uncertain: true,
    });
  });
  it("rejects a GET response with the wrong reservation ID", async () => {
    const { gateway } = setup({ ...wireReceipt(), id: 8 }, 200);
    await expect(gateway.read("7", intent())).rejects.toThrow("不匹配");
  });
});
