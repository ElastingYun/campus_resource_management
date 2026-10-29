import { afterEach, describe, expect, it, vi } from "vitest";
import { createCGateway, parseApplication } from "./c-gateway";
import { createCSession } from "./c-session";
import {
  application,
  applicationId,
  identity,
  json,
  otherActor,
  room,
} from "./c-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
function setup() {
  const session = createCSession();
  session.state.value = {
    accessToken: "synthetic-token",
    expiresAt: "2030-01-01Z",
    identity: identity(),
  };
  return session;
}
const draft = () => ({
  roomId: room.id,
  purpose: "原内容",
  startsAt: "2030-01-02T09:00",
  endsAt: "2030-01-02T11:00",
});
describe("C-v1 gateway contract", () => {
  it("keeps applications visible and creation disabled when resource permission is unavailable", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        json([
          application({
            review_status: "PASSED",
            integration_status: "APPLY_PENDING",
          }),
        ]),
      )
      .mockResolvedValueOnce(json({}, 403));
    vi.stubGlobal("fetch", fetch);
    const gateway = createCGateway(setup());
    const data = await gateway.load();
    expect(data.applications[0]?.effective).toBe(false);
    expect(data.applications[0]?.reviewLabel).toBe("审批已通过");
    expect(data.applications[0]?.integrationLabel).toBe("正在确认占用");
    expect(data.canSubmit).toBe(true); // Can open the form; a directory selection is still required.
    expect(data.rooms).toEqual([]);
    await expect(gateway.roomOptions!()).rejects.toThrow("没有选择教室的权限");
    await expect(gateway.submit(draft())).rejects.toThrow("不能提交");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("preserves a decimal string room ID and sends only the four C submission fields", async () => {
    const fetch = vi.fn(async (_path, options) =>
      options?.method === "POST"
        ? json(application(), 201)
        : String(_path).includes("?")
          ? json([])
          : json(application()),
    );
    vi.stubGlobal("fetch", fetch);
    const gateway = createCGateway(setup(), {
      loadRooms: async () => [room],
      key: () => "m2:test-original-key",
    });
    await gateway.load();
    await gateway.submit(draft());
    const write = fetch.mock.calls.find((call) => call[1]?.method === "POST")!;
    expect(JSON.parse(write[1].body)).toEqual({
      room_id: "9007199254740993",
      purpose: "原内容",
      starts_at: new Date(draft().startsAt).toISOString(),
      ends_at: new Date(draft().endsAt).toISOString(),
    });
    expect(new Headers(write[1].headers).get("Idempotency-Key")).toBe(
      "m2:test-original-key",
    );
    expect(gateway.pending?.()).toBeUndefined();
  });
  it("recovers with the identical key/body and blocks new writes while outcome is unknown", async () => {
    let writes = 0;
    const captured: { body: string; key: string | null }[] = [];
    const fetch = vi.fn(async (path, options) => {
      if (options?.method === "POST") {
        captured.push({
          body: options.body,
          key: new Headers(options.headers).get("Idempotency-Key"),
        });
        if (++writes === 1) throw new Error("lost-response");
        return json(application(), 201);
      }
      return String(path).includes("?") ? json([]) : json(application());
    });
    vi.stubGlobal("fetch", fetch);
    const key = vi.fn(() => "m2:same-key");
    const gateway = createCGateway(setup(), {
      loadRooms: async () => [room],
      key,
    });
    await gateway.load();
    const original = draft();
    await expect(gateway.submit(original)).rejects.toThrow("结果尚未确认");
    original.purpose = "后来修改";
    await expect(gateway.submit(original)).rejects.toThrow("先恢复结果");
    expect(writes).toBe(1);
    await gateway.recover!();
    expect(writes).toBe(2);
    expect(captured[1]).toEqual(captured[0]);
    expect(key).toHaveBeenCalledTimes(1);
    expect(gateway.pending?.()).toBeUndefined();
  });
  it("queries a known ID after a read failure instead of repeating the write", async () => {
    let gets = 0;
    const fetch = vi.fn(async (path, options) => {
      if (options?.method === "POST") return json(application(), 201);
      if (String(path).includes("?")) return json([]);
      if (++gets === 1) throw new Error("lost-read");
      return json(application());
    });
    vi.stubGlobal("fetch", fetch);
    const gateway = createCGateway(setup(), { loadRooms: async () => [room] });
    await gateway.load();
    await expect(gateway.submit(draft())).rejects.toThrow();
    await gateway.recover!();
    expect(
      fetch.mock.calls.filter((call) => call[1]?.method === "POST"),
    ).toHaveLength(1);
  });
  it("isolates pending requests by authenticated subject", async () => {
    const session = setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path, options) => {
        if (options?.method === "POST") throw new Error("lost");
        return json([]);
      }),
    );
    const gateway = createCGateway(session, { loadRooms: async () => [room] });
    await gateway.load();
    await expect(gateway.submit(draft())).rejects.toThrow();
    session.state.value = {
      accessToken: "second-user-token",
      expiresAt: "2030-01-01Z",
      identity: identity(otherActor),
    };
    expect(gateway.pending?.()).toBeUndefined();
    await expect(gateway.recover!()).rejects.toThrow("没有待恢复操作");
    expect(gateway.hasAnyPending()).toBe(true);
  });
  it("rejects mixed detail/actions versions instead of rendering stale action permissions", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path) =>
        String(path).endsWith("/actions")
          ? json({
              application_id: applicationId,
              version: 2,
              allowed_actions: ["APPROVE"],
            })
          : String(path).endsWith("/history")
            ? json([])
            : json(application()),
      ),
    );
    await expect(
      createCGateway(setup()).detail!(applicationId),
    ).rejects.toThrow("不符合 C-v1");
  });
  it("uses server-provided actions and expected_version for decisions", async () => {
    const fetch = vi.fn(async (path, options) =>
      options?.method === "POST"
        ? json(application({ version: 2 }))
        : String(path).endsWith("/actions")
          ? json({
              application_id: applicationId,
              version: 1,
              allowed_actions: ["REJECT"],
            })
          : String(path).endsWith("/history")
            ? json([])
            : json(application()),
    );
    vi.stubGlobal("fetch", fetch);
    const gateway = createCGateway(setup());
    const detail = await gateway.detail!(applicationId);
    expect(detail.allowedActions).toEqual(["REJECT"]);
    await gateway.decide!(applicationId, "REJECT", "补充说明", detail.version);
    const write = fetch.mock.calls.find((call) => call[1]?.method === "POST")!;
    expect(String(write[0])).toBe(
      `/api/v1/m2/applications/${applicationId}/decisions`,
    );
    expect(JSON.parse(write[1].body)).toEqual({
      decision: "REJECT",
      comment: "补充说明",
      expected_version: 1,
    });
  });
  it("does not render effective occupancy for an inconsistent response", () => {
    expect(() =>
      parseApplication(
        application({
          review_status: "PASSED",
          integration_status: "APPLY_PENDING",
          effective: true,
        }),
      ),
    ).toThrow("生效状态不一致");
    expect(
      parseApplication(
        application({
          review_status: "PASSED",
          integration_status: "APPLIED",
          effective: true,
        }),
      ).effective,
    ).toBe(true);
  });
  it("clears the active session on 401 without falling back to prototype data", async () => {
    const session = setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({}, 401)));
    await expect(createCGateway(session).load()).rejects.toThrow("会话已失效");
    expect(session.state.value).toBeNull();
  });
  it("retains pagination as arrays without inventing total or client-side identity filters", async () => {
    const fetch = vi.fn().mockResolvedValue(json([application()]));
    vi.stubGlobal("fetch", fetch);
    const result = await createCGateway(setup(), {
      loadRooms: async () => [room],
    }).load({ review: true, offset: 20, limit: 1 });
    expect(fetch.mock.calls[0]![0]).toBe(
      "/api/v1/m2/review-tasks?limit=1&offset=20",
    );
    expect(result.pagination).toEqual({ offset: 20, limit: 1, hasNext: true });
  });
});
