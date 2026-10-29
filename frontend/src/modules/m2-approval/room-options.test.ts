import { afterEach, describe, expect, it, vi } from "vitest";
import { createCGateway } from "./c-gateway";
import { createCSession } from "./c-session";
import { parseRoomOptions, roomQuery } from "./room-options";
import {
  application,
  identity,
  json,
  otherActor,
  room,
} from "./c-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
const item = () => ({ ...room, code: "TEST-ROOM" });
const page = (changes: Record<string, unknown> = {}) => ({
  items: [item()],
  total: 121,
  limit: 20,
  offset: 0,
  ...changes,
});
function session() {
  const value = createCSession();
  value.state.value = {
    accessToken: "synthetic-directory-token",
    expiresAt: "2030-01-01Z",
    identity: identity(),
  };
  return value;
}
const draft = () => ({
  roomId: room.id,
  purpose: "目录选择",
  startsAt: "2030-01-02T09:00",
  endsAt: "2030-01-02T10:00",
});
describe("ordinary room options boundary", () => {
  it("keeps BIGINT strings and server totals beyond one hundred without retaining management fields", () => {
    const value = parseRoomOptions(
      page({
        items: [{ ...item(), department_id: "private", revision: "private" }],
      }),
      roomQuery(),
    );
    expect(value.total).toBe(121);
    expect(value.items[0]?.id).toBe("9007199254740993");
    expect(value.items[0]).not.toHaveProperty("department_id");
    expect(value.items[0]).not.toHaveProperty("revision");
  });
  it.each([
    { total: -1 },
    { total: "1" },
    { limit: 100 },
    { offset: 20 },
    { items: [{ ...item(), id: 9007199254740992 }] },
    { items: [{ ...item(), id: "01" }] },
    { items: [{ ...item(), id: "9223372036854775808" }] },
    { items: [item(), item()] },
    { items: [{ ...item(), code: null }] },
    { items: [{ ...item(), name: "" }] },
    { items: [{ ...item(), location: null }] },
    { total: 0 },
    { items: new Array(21).fill(item()) },
  ])("rejects malformed or mismatched directory pages %j", (changes) => {
    expect(() => parseRoomOptions(page(changes), roomQuery())).toThrow(
      "响应异常",
    );
  });
  it.each([
    { q: "x".repeat(101) },
    { offset: -1 },
    { limit: 0 },
    { limit: 101 },
    { offset: 0.5 },
  ])("rejects invalid query before fetch %j", async (query) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(createCGateway(session()).roomOptions!(query)).rejects.toThrow(
      "搜索最多",
    );
    expect(fetch).not.toHaveBeenCalled();
  });
  it("accepts an empty page without inventing missing choices", () => {
    expect(
      parseRoomOptions(page({ items: [], total: 0 }), roomQuery()).items,
    ).toEqual([]);
  });
  it("sends only the confirmed ordinary path and literal search/page parameters", async () => {
    const fetch = vi.fn().mockResolvedValue(json(page({ offset: 100 })));
    vi.stubGlobal("fetch", fetch);
    await createCGateway(session()).roomOptions!({ q: "A %_&", offset: 100 });
    const [path, init] = fetch.mock.calls[0]!;
    const url = new URL(path, "https://same.invalid");
    expect(url.pathname).toBe("/api/v1/resources/room-options");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      q: "A %_&",
      limit: "20",
      offset: "100",
    });
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer synthetic-directory-token",
    );
    expect(init.cache).toBe("no-store");
  });
  it.each([
    [
      403,
      { detail: { code: "forbidden", message: "private error" } },
      "没有选择教室",
    ],
    [
      503,
      { detail: { code: "identity_unconfigured", message: "private error" } },
      "尚未配置",
    ],
    [
      503,
      {
        error: {
          code: "RESOURCE_IDENTITY_UNAVAILABLE",
          message: "private error",
        },
      },
      "无法核对",
    ],
  ])(
    "handles C/B errors without a management or prototype fallback (%i)",
    async (status, data, message) => {
      const fetch = vi.fn().mockResolvedValue(json(data, status));
      vi.stubGlobal("fetch", fetch);
      await expect(createCGateway(session()).roomOptions!()).rejects.toThrow(
        String(message),
      );
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch.mock.calls[0]![0]).toContain("/room-options?");
    },
  );
  it("invalidates the matching session when directory authentication expires", async () => {
    const value = session();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(json({ error: { code: "INVALID_SESSION" } }, 401)),
    );
    await expect(createCGateway(value).roomOptions!()).rejects.toThrow(
      "会话已失效",
    );
    expect(value.state.value).toBeNull();
  });
  it("does not authorize a previous account's cached selection or a late response", async () => {
    const value = session();
    let resolve!: (response: Response) => void;
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(page()))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((done) => {
            resolve = done;
          }),
      );
    vi.stubGlobal("fetch", fetch);
    const gateway = createCGateway(value);
    await gateway.roomOptions!();
    const late = gateway.roomOptions!();
    value.state.value = {
      ...value.state.value!,
      accessToken: "synthetic-other-token",
      identity: identity(otherActor),
    };
    resolve(json(page()));
    await expect(late).rejects.toThrow("登录状态已变化");
    await expect(gateway.submit(draft())).rejects.toThrow("不能提交");
    expect(fetch.mock.calls.every((call) => call[1]?.method === "GET")).toBe(
      true,
    );
  });
  it("does not let an older search replace the latest authorized page", async () => {
    let resolve!: (response: Response) => void;
    const fetch = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((done) => {
            resolve = done;
          }),
      )
      .mockResolvedValueOnce(json(page({ items: [{ ...item(), id: "2" }] })));
    vi.stubGlobal("fetch", fetch);
    const gateway = createCGateway(session());
    const old = gateway.roomOptions!({ q: "old" });
    await gateway.roomOptions!({ q: "new" });
    resolve(json(page()));
    await expect(old).rejects.toThrow("查询或登录状态已变化");
    await expect(gateway.submit(draft())).rejects.toThrow("不能提交");
  });
  it("sends the selected BIGINT string only after a current directory read; a failed refresh clears it", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(page()))
      .mockResolvedValueOnce(json(application(), 201))
      .mockResolvedValueOnce(json(application()))
      .mockResolvedValueOnce(json({}, 503));
    vi.stubGlobal("fetch", fetch);
    const gateway = createCGateway(session());
    await expect(gateway.submit(draft())).rejects.toThrow("不能提交");
    await gateway.roomOptions!();
    await gateway.submit(draft());
    expect(JSON.parse(fetch.mock.calls[1]![1].body).room_id).toBe(
      "9007199254740993",
    );
    await expect(gateway.roomOptions!()).rejects.toThrow();
    await expect(gateway.submit(draft())).rejects.toThrow("不能提交");
    expect(
      fetch.mock.calls.filter((call) => call[1]?.method === "POST"),
    ).toHaveLength(1);
  });
});
