import { afterEach, describe, expect, it, vi } from "vitest";
import { createCSession } from "./c-session";
import { identity, json, otherActor } from "./c-test-fixtures";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
const sessionResponse = (token = "synthetic-token") => ({
  access_token: token,
  token_type: "bearer",
  expires_at: "2030-01-01T01:10:00Z",
});
describe("C-v1 in-memory session", () => {
  it("commits identity only after me succeeds and never persists credentials", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(sessionResponse()))
      .mockResolvedValueOnce(json(identity()));
    vi.stubGlobal("fetch", fetch);
    const session = createCSession();
    await session.login("synthetic-student", "synthetic-password");
    expect(session.state.value?.identity.subject_id).toBe(
      identity().subject_id,
    );
    expect(
      new Headers(fetch.mock.calls[1]![1].headers).get("Authorization"),
    ).toBe("Bearer synthetic-token");
    expect(storage).not.toHaveBeenCalled();
  });
  it("does not keep a token when the identity response is malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(json(sessionResponse()))
        .mockResolvedValueOnce(json({ subject_id: "not-a-uuid" })),
    );
    const session = createCSession();
    await expect(
      session.login("synthetic", "synthetic-password"),
    ).rejects.toThrow("身份响应格式");
    expect(session.state.value).toBeNull();
  });
  it.each([401, 429, 503])(
    "uses a safe login error for HTTP %s",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            json(
              { error: { code: "PRIVATE", message: "secret-debug-body" } },
              status,
            ),
          ),
      );
      const session = createCSession();
      const error = await session
        .login("synthetic", "synthetic-password")
        .catch((cause) => cause);
      expect(String(error)).not.toContain("secret-debug-body");
      expect(String(error)).not.toContain("synthetic-password");
      expect(session.state.value).toBeNull();
    },
  );
  it("immediately clears local identity even if server logout fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const session = createCSession();
    session.state.value = {
      accessToken: "old-token",
      expiresAt: "2030-01-01Z",
      identity: identity(),
    };
    const logout = session.logout();
    expect(session.state.value).toBeNull();
    await logout;
    expect(session.notice.value).toContain("服务端退出未确认");
  });
  it("does not let an old 401 invalidate a newer session", () => {
    const session = createCSession();
    session.state.value = {
      accessToken: "new-token",
      expiresAt: "2030-01-01Z",
      identity: identity(otherActor),
    };
    session.invalidate("old-token");
    expect(session.state.value?.accessToken).toBe("new-token");
    session.invalidate("new-token");
    expect(session.state.value).toBeNull();
  });
});
