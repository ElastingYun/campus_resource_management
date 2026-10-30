import { afterEach, describe, expect, it, vi } from "vitest";
import { createCSession } from "../../m2-approval/c-session";
import type { CSessionState } from "../../m2-approval/c-session";
import { createCResourceAccess, parseResourcePermissions } from "./host";

const mapping = {
  read: "synthetic.read",
  manage: "synthetic.manage",
  create_rooms: "synthetic.create",
};
const identity = (token: string): CSessionState => ({
  accessToken: token,
  expiresAt: "2099-01-01T00:00:00Z",
  identity: {
    subject_id: "00000000-0000-4000-8000-000000000001",
    department_id: "synthetic",
    roles: [],
    permissions: Object.values(mapping),
    data_scopes: { all_rooms: false, room_ids: ["9007199254740993"] },
  },
});
afterEach(() => vi.unstubAllGlobals());
describe("C resource host", () => {
  it.each([
    undefined,
    "",
    "invalid",
    "null",
    "[]",
    "{}",
    JSON.stringify({ ...mapping, extra: "grant" }),
    JSON.stringify({ ...mapping, manage: "invalid permission" }),
    JSON.stringify({ ...mapping, create_rooms: 1 }),
  ])("closes invalid public configuration %s", (value) => {
    expect(parseResourcePermissions(value)).toBeNull();
  });
  it("maps explicit server permission names and the same current C identity without narrowing BIGINT", async () => {
    const c = createCSession();
    c.state.value = identity("synthetic-current-token");
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        Response.json({ items: [], total: 0, limit: 20, offset: 0 }),
      );
    const access = createCResourceAccess(
      c,
      parseResourcePermissions(JSON.stringify(mapping))!,
      request,
    );
    expect(access.session.currentActorId).toBe(
      c.state.value.identity.subject_id,
    );
    expect(access.session.canManage).toBe(true);
    expect(access.session.canCreateRooms).toBe(false);
    await access.gateway.listSeats("9007199254740993", {});
    expect(String(request.mock.calls[0]![0])).toContain(
      "/rooms/9007199254740993/seats",
    );
    expect(
      new Headers(request.mock.calls[0]![1]?.headers).get("Authorization"),
    ).toBe("Bearer synthetic-current-token");
    c.state.value = null;
    expect(access.session.currentActorId).toBeNull();
    await expect(access.gateway.listRooms({})).rejects.toMatchObject({
      uncertain: false,
    });
    expect(request).toHaveBeenCalledTimes(1);
  });
  it.each([false, true])(
    "resource 401 invalidates only its captured token (replaced: %s)",
    async (replace) => {
      const c = createCSession();
      c.state.value = identity("synthetic-original-token");
      let resolve!: (response: Response) => void;
      const request = vi.fn<typeof fetch>().mockReturnValue(
        new Promise<Response>((done) => {
          resolve = done;
        }),
      );
      const access = createCResourceAccess(
        c,
        parseResourcePermissions(JSON.stringify(mapping))!,
        request,
      );
      const pending = access.gateway.listRooms({});
      if (replace) c.state.value = identity("synthetic-new-token");
      resolve(
        Response.json({ detail: { code: "unauthenticated" } }, { status: 401 }),
      );
      await expect(pending).rejects.toBeDefined();
      expect(c.state.value?.accessToken ?? null).toBe(
        replace ? "synthetic-new-token" : null,
      );
    },
  );
});
