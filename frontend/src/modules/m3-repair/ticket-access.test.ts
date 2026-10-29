import { afterEach, describe, expect, it, vi } from "vitest";
import { createM3TicketAccess } from "./ticket-access";
import { M3ClientError, type M3Session } from "./models";

const actorA = "11111111-1111-4111-8111-111111111111";
const actorB = "22222222-2222-4222-8222-222222222222";
const ticketId = "33333333-3333-4333-8333-333333333333";
const otherId = "44444444-4444-4444-8444-444444444444";
const roomId = "9223372036854775807";
const draft = { roomId, description: "插座损坏" };
const wire = (overrides: Record<string, unknown> = {}) => ({
  id: ticketId,
  room_id: roomId,
  description: draft.description,
  status: "REPORTED",
  created_at: "2026-10-29T10:00:00+00:00",
  ...overrides,
});
const response = (value: unknown = wire(), status = 201) =>
  new Response(JSON.stringify(value), { status });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function fixture(extra: { timeoutMs?: number; createKey?: () => string } = {}) {
  let session: M3Session | null = {
    subjectId: actorA,
    accessToken: "synthetic-token-A",
    canCreate: true,
    canReadOwn: true,
  };
  const fetcher = vi.fn<typeof globalThis.fetch>();
  const unauthorized = vi.fn();
  let keys = 0;
  const access = createM3TicketAccess({
    getSession: () => session,
    fetch: fetcher,
    createKey: () => `synthetic-key-${++keys}`,
    onUnauthorized: unauthorized,
    ...extra,
  });
  return {
    access, fetcher, unauthorized,
    setSession(value: M3Session | null) { session = value; },
    change(value: Partial<M3Session>) { session = { ...session!, ...value }; },
  };
}

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("M3 own-ticket contract consumption", () => {
  it.each([201, 200])("accepts confirmed create/replay %s and never sends caller identity", async status => {
    const f = fixture(); f.fetcher.mockResolvedValue(response(wire(), status));
    const result = await f.access.submit({ ...draft, description: `  ${draft.description}  ` });
    expect(result).toMatchObject({ id: ticketId, roomId, description: draft.description });
    expect(f.fetcher).toHaveBeenCalledTimes(1);
    const [url, init] = f.fetcher.mock.calls[0]!;
    expect(url).toBe("/api/v1/m3/tickets");
    expect(init).toMatchObject({ method: "POST", credentials: "same-origin", redirect: "error", cache: "no-store" });
    const headers = new Headers(init!.headers);
    expect(headers.get("Authorization")).toBe("Bearer synthetic-token-A");
    expect(headers.get("Idempotency-Key")).toBe("synthetic-key-1");
    expect(JSON.parse(init!.body as string)).toEqual({ room_id: roomId, description: draft.description });
    expect(f.access.getPending()).toBeNull();
    expect(f.access.hasUnresolvedReports()).toBe(false);
  });

  it("reads the own-page envelope without inventing total or action/version fields", async () => {
    const f = fixture();
    f.fetcher.mockResolvedValue(response({ items: [wire({ status: "FUTURE_STATUS" })], limit: 20, offset: 40 }, 200));
    const page = await f.access.listOwn(20, 40);
    expect(f.fetcher.mock.calls[0]![0]).toBe("/api/v1/m3/tickets?limit=20&offset=40");
    expect(page).toEqual({ items: [expect.objectContaining({ id: ticketId, status: "FUTURE_STATUS" })], limit: 20, offset: 40 });
    expect(page).not.toHaveProperty("total");
    expect(page.items[0]).not.toHaveProperty("version");
    expect(new Headers(f.fetcher.mock.calls[0]![1]!.headers).has("Idempotency-Key")).toBe(false);
  });

  it("supports empty pages and canonical UUID detail reads", async () => {
    const f = fixture();
    f.fetcher.mockResolvedValueOnce(response({ items: [], limit: 20, offset: 0 }, 200))
      .mockResolvedValueOnce(response(wire({ id: ticketId.toUpperCase() }), 200));
    expect((await f.access.listOwn()).items).toEqual([]);
    expect((await f.access.getOwn(ticketId.toUpperCase())).id).toBe(ticketId);
    expect(f.fetcher.mock.calls[1]![0]).toBe(`/api/v1/m3/tickets/${ticketId}`);
  });

  it.each(["0", "01", "-1", "9223372036854775808", "9007199254740993.0", "room-code"])(
    "rejects invalid room id %s before sending", async invalid => {
      const f = fixture();
      await expect(f.access.submit({ ...draft, roomId: invalid })).rejects.toMatchObject({ kind: "validation", mayHaveWritten: false });
      expect(f.fetcher).not.toHaveBeenCalled();
    },
  );

  it.each(["", "   ", "bad\nline", "bad\tvalue", "bad\u007fvalue", "x".repeat(2001)])(
    "rejects blank, control and over-limit descriptions", async description => {
      const f = fixture();
      await expect(f.access.submit({ roomId, description })).rejects.toMatchObject({ kind: "validation" });
      expect(f.fetcher).not.toHaveBeenCalled();
    },
  );

  it("counts supplementary Unicode characters like Python rather than UTF-16 units", async () => {
    const f = fixture(); const description = "🔧".repeat(2000);
    f.fetcher.mockResolvedValue(response(wire({ description })));
    expect((await f.access.submit({ roomId, description })).description).toBe(description);
    await expect(f.access.submit({ roomId, description: description + "🔧" })).rejects.toMatchObject({ kind: "validation" });
    expect(f.fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([[0, 0], [101, 0], [20, -1], [20, 1.5], [20, Number.MAX_SAFE_INTEGER + 1]])(
    "rejects invalid paging %s/%s before sending", async (limit, offset) => {
      const f = fixture();
      await expect(f.access.listOwn(limit, offset)).rejects.toMatchObject({ kind: "validation" });
      expect(f.fetcher).not.toHaveBeenCalled();
    },
  );

  it("rejects invalid detail identifiers and mismatched detail responses", async () => {
    const f = fixture();
    await expect(f.access.getOwn("../other-account")).rejects.toMatchObject({ kind: "validation" });
    expect(f.fetcher).not.toHaveBeenCalled();
    f.fetcher.mockResolvedValue(response(wire({ id: otherId }), 200));
    await expect(f.access.getOwn(ticketId)).rejects.toMatchObject({ kind: "invalid_response", mayHaveWritten: false });
  });

  it.each([
    { items: [wire()], limit: 19, offset: 0 },
    { items: [wire()], limit: 20, offset: 1 },
    { items: [wire(), wire()], limit: 20, offset: 0 },
    { items: [wire({ room_id: 9007199254740992 })], limit: 20, offset: 0 },
    { items: [wire({ created_at: "2026-10-29T10:00:00" })], limit: 20, offset: 0 },
  ])("rejects invalid page, duplicate ID, numeric BIGINT or naive time", async payload => {
    const f = fixture(); f.fetcher.mockResolvedValue(response(payload, 200));
    await expect(f.access.listOwn()).rejects.toMatchObject({ kind: "invalid_response", mayHaveWritten: false });
  });

  it.each([401, 403, 409, 422])("preserves definite HTTP %s and bounded code without raw messages", async status => {
    const f = fixture();
    f.fetcher.mockResolvedValue(response({ detail: { code: "ticket_rejected", message: "private-description-and-secret" } }, status));
    const error = await f.access.submit(draft).catch(cause => cause);
    expect(error).toBeInstanceOf(M3ClientError);
    expect(error).toMatchObject({ kind: "http", status, serverCode: "ticket_rejected", mayHaveWritten: false });
    expect(String(error)).not.toContain("secret");
    expect(f.access.getPending()).toBeNull();
    expect(f.unauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
  });

  it("accepts C's error wrapper and rejects unsafe server codes", async () => {
    const f = fixture();
    f.fetcher.mockResolvedValueOnce(response({ error: { code: "permission_denied", message: "private" } }, 403))
      .mockResolvedValueOnce(response({ detail: { code: "<private/html>" } }, 403));
    await expect(f.access.listOwn()).rejects.toMatchObject({ status: 403, serverCode: "permission_denied" });
    const second = await f.access.listOwn().catch(cause => cause);
    expect(second.serverCode).toBeUndefined();
    expect(String(second)).not.toContain("private");
  });
});

describe("M3 uncertain submission recovery", () => {
  it("blocks duplicate in-flight submit and confirms once", async () => {
    const f = fixture(); const network = deferred<Response>();
    f.fetcher.mockReturnValue(network.promise);
    const first = f.access.submit(draft);
    expect(f.access.getPending()?.phase).toBe("sending");
    await expect(f.access.submit(draft)).rejects.toMatchObject({ kind: "busy" });
    await expect(f.access.recover()).rejects.toMatchObject({ kind: "busy" });
    network.resolve(response()); await first;
    expect(f.fetcher).toHaveBeenCalledTimes(1);
    expect(f.access.hasUnresolvedReports()).toBe(false);
  });

  it("keeps original key/content after lost response and explicitly replays without a second record", async () => {
    const f = fixture();
    f.fetcher.mockRejectedValueOnce(new Error("lost response: private host"))
      .mockResolvedValueOnce(response(wire(), 200));
    await expect(f.access.submit(draft)).rejects.toMatchObject({ kind: "network", mayHaveWritten: true });
    expect(f.access.getPending()).toMatchObject({ subjectId: actorA, key: "synthetic-key-1", draft, phase: "unknown" });
    expect(JSON.stringify(f.access.getPending())).not.toContain("synthetic-token");
    await expect(f.access.submit({ ...draft, description: "changed" })).rejects.toMatchObject({ kind: "recovery_required" });
    const report = await f.access.recover();
    expect(report.id).toBe(ticketId);
    expect(f.fetcher).toHaveBeenCalledTimes(2);
    const first = f.fetcher.mock.calls[0]![1]!;
    const replay = f.fetcher.mock.calls[1]![1]!;
    expect(replay.body).toBe(first.body);
    expect(new Headers(replay.headers).get("Idempotency-Key")).toBe(new Headers(first.headers).get("Idempotency-Key"));
    expect(f.access.hasUnresolvedReports()).toBe(false);
  });

  it.each([408, 500, 503])("keeps HTTP %s as unknown without automatic retry", async status => {
    const f = fixture(); f.fetcher.mockResolvedValue(response({ detail: { code: "unavailable" } }, status));
    await expect(f.access.submit(draft)).rejects.toMatchObject({ kind: "http", status, mayHaveWritten: true });
    expect(f.access.getPending()?.phase).toBe("unknown");
    expect(f.fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    () => new Response("<html>proxy</html>", { status: 200 }),
    () => response(wire({ room_id: "1" })),
    () => response(wire({ description: "different ticket" })),
    () => new Response(null, { status: 204 }),
    () => response(wire({ id: "not-a-ticket" })),
  ])("does not confirm malformed successful writes", async makeResponse => {
    const f = fixture(); f.fetcher.mockResolvedValue(makeResponse());
    await expect(f.access.submit(draft)).rejects.toMatchObject({ kind: "invalid_response", mayHaveWritten: true });
    expect(f.access.getPending()?.key).toBe("synthetic-key-1");
  });

  it("keeps recovery data after a later definite error, even when retry is forbidden", async () => {
    const f = fixture();
    f.fetcher.mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(response({ detail: { code: "permission_denied" } }, 403));
    await expect(f.access.submit(draft)).rejects.toBeInstanceOf(M3ClientError);
    await expect(f.access.recover()).rejects.toMatchObject({ status: 403, mayHaveWritten: false });
    expect(f.access.getPending()).toMatchObject({ key: "synthetic-key-1", draft, phase: "unknown" });
    await expect(f.access.submit(draft)).rejects.toMatchObject({ kind: "recovery_required" });
    expect(f.fetcher).toHaveBeenCalledTimes(2);
  });

  it("times out even if a transport ignores AbortSignal, and late 401 cannot clear a session", async () => {
    vi.useFakeTimers();
    const f = fixture({ timeoutMs: 20 }); const network = deferred<Response>();
    f.fetcher.mockReturnValue(network.promise);
    const first = f.access.submit(draft);
    const assertion = expect(first).rejects.toMatchObject({ kind: "timeout", mayHaveWritten: true });
    await vi.advanceTimersByTimeAsync(21); await assertion;
    expect(f.access.getPending()?.phase).toBe("unknown");
    expect(f.fetcher.mock.calls[0]![1]!.signal!.aborted).toBe(true);
    network.resolve(response({ error: { code: "expired" } }, 401));
    await Promise.resolve(); await Promise.resolve();
    expect(f.unauthorized).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps the deadline while reading a partial body", async () => {
    vi.useFakeTimers(); const f = fixture({ timeoutMs: 20 });
    f.fetcher.mockResolvedValue(new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('{"id":')); } }), { status: 201 }));
    const pending = f.access.submit(draft);
    const assertion = expect(pending).rejects.toMatchObject({ kind: "timeout", mayHaveWritten: true });
    await vi.advanceTimersByTimeAsync(21); await assertion;
    expect(f.access.getPending()?.phase).toBe("unknown");
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("M3 same-session and host-lifetime boundaries", () => {
  it.each(["absent", "create-denied", "read-denied", "invalid-token", "invalid-capability"])(
    "sends no request when session/capability is %s", async mode => {
      const f = fixture();
      if (mode === "absent") f.setSession(null);
      if (mode === "create-denied") f.change({ canCreate: false });
      if (mode === "read-denied") f.change({ canReadOwn: false });
      if (mode === "invalid-token") f.change({ accessToken: "bad\nheader" });
      if (mode === "invalid-capability") f.change({ canCreate: "yes" as unknown as boolean });
      const action = mode === "read-denied" ? f.access.listOwn() : f.access.submit(draft);
      await expect(action).rejects.toBeInstanceOf(M3ClientError);
      expect(f.fetcher).not.toHaveBeenCalled();
    },
  );

  it.each(["subject", "token", "capability"])("discards late reads after %s changes", async change => {
    const f = fixture(); const network = deferred<Response>(); f.fetcher.mockReturnValue(network.promise);
    const read = f.access.getOwn(ticketId);
    if (change === "subject") f.change({ subjectId: actorB, accessToken: "synthetic-token-B" });
    if (change === "token") f.change({ accessToken: "renewed-token" });
    if (change === "capability") f.change({ canReadOwn: false });
    network.resolve(response(wire(), 200));
    await expect(read).rejects.toMatchObject({ kind: "session_changed", mayHaveWritten: false });
  });

  it("does not clear a newer session for a late old-token 401", async () => {
    const f = fixture(); const network = deferred<Response>(); f.fetcher.mockReturnValue(network.promise);
    const read = f.access.listOwn(); f.change({ accessToken: "renewed-token" });
    network.resolve(response({ error: { code: "expired" } }, 401));
    await expect(read).rejects.toMatchObject({ kind: "session_changed" });
    expect(f.unauthorized).not.toHaveBeenCalled();
  });

  it("keeps an old actor's uncertain write isolated and allows only that actor to recover it", async () => {
    const f = fixture(); const network = deferred<Response>(); f.fetcher.mockReturnValueOnce(network.promise);
    const write = f.access.submit(draft);
    f.change({ subjectId: actorB, accessToken: "synthetic-token-B" });
    network.resolve(response());
    await expect(write).rejects.toMatchObject({ kind: "session_changed", mayHaveWritten: true });
    expect(f.access.getPending()).toBeNull();
    expect(f.access.hasUnresolvedReports()).toBe(true);
    await expect(f.access.recover()).rejects.toMatchObject({ kind: "validation" });
    expect(f.fetcher).toHaveBeenCalledTimes(1);
    f.change({ subjectId: actorA, accessToken: "renewed-token-A" });
    f.fetcher.mockResolvedValueOnce(response(wire(), 200));
    await f.access.recover();
    expect(new Headers(f.fetcher.mock.calls[1]![1]!.headers).get("Authorization")).toBe("Bearer renewed-token-A");
    expect(new Headers(f.fetcher.mock.calls[1]![1]!.headers).get("Idempotency-Key")).toBe("synthetic-key-1");
    expect(f.access.hasUnresolvedReports()).toBe(false);
  });

  it("guards session changes made by the key factory before sending", async () => {
    let change!: () => void;
    const f = fixture({ createKey: () => { change(); return "key"; } });
    change = () => f.change({ subjectId: actorB, accessToken: "synthetic-token-B" });
    await expect(f.access.submit(draft)).rejects.toMatchObject({ kind: "session_changed", mayHaveWritten: false });
    expect(f.fetcher).not.toHaveBeenCalled();
    expect(f.access.hasUnresolvedReports()).toBe(false);
  });

  it("exposes an immutable token-free recovery snapshot without storage writes", async () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    const f = fixture(); f.fetcher.mockRejectedValueOnce(new Error("offline"));
    await expect(f.access.submit(draft)).rejects.toBeInstanceOf(M3ClientError);
    const copy = f.access.getPending()!;
    expect(Object.isFrozen(copy)).toBe(true);
    expect(Object.isFrozen(copy.draft)).toBe(true);
    expect(() => Object.assign(copy.draft, { description: "changed through view" })).toThrow(TypeError);
    f.fetcher.mockResolvedValueOnce(response(wire(), 200));
    await f.access.recover();
    expect(JSON.parse(f.fetcher.mock.calls[1]![1]!.body as string)).toEqual({ room_id: roomId, description: draft.description });
    expect(local).not.toHaveBeenCalled();
    expect(JSON.stringify(copy)).not.toContain("synthetic-token-A");
  });

  it.each(["", "bad key", "x".repeat(129)])("rejects bad idempotency keys without retaining a record", async key => {
    const f = fixture({ createKey: () => key });
    await expect(f.access.submit(draft)).rejects.toMatchObject({ kind: "configuration", mayHaveWritten: false });
    expect(f.fetcher).not.toHaveBeenCalled();
    expect(f.access.hasUnresolvedReports()).toBe(false);
  });
});
