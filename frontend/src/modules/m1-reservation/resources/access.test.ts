import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { mount, flushPromises } from "@vue/test-utils";
import ResourceWorkspace from "./ResourceWorkspace.vue";
import { createAuthenticatedResourceAccess } from "./access";
import type { TrustedResourceSession } from "./access";
import { createPrototypeResourceGateway } from "./prototype";
import { createResourceSession } from "./session";

const permissions = {
  read: "synthetic.read",
  manage: "synthetic.manage",
  createRooms: "synthetic.create",
};
const trusted = (): TrustedResourceSession => ({
  subjectId: "A",
  accessToken: "synthetic-token-A",
  permissions: Object.values(permissions),
  dataScopes: { allRooms: true, roomIds: [] },
});
const draft = { code: "NEW", name: "新教室", location: "示例区" };
async function setup() {
  const actor = ref<TrustedResourceSession | null>(trusted());
  const room = (await createPrototypeResourceGateway().listRooms({})).items[0]!;
  const request = vi
    .fn<typeof fetch>()
    .mockImplementation(async (url, init) =>
      Response.json(
        init?.method === "GET"
          ? {
              items: String(url).includes("/seats") ? [] : [room],
              total: String(url).includes("/seats") ? 0 : 1,
              limit: 20,
              offset: 0,
            }
          : { ...room, ...draft },
      ),
    );
  const access = createAuthenticatedResourceAccess({
    getSession: () => actor.value,
    permissions,
    request,
  });
  return { ...access, actor, request, room };
}
describe("trusted B resource access", () => {
  it("pairs the retained session and fixed same-origin transport with C's identity", async () => {
    const { gateway, session, request } = await setup();
    expect(session.gateway).toBe(gateway);
    expect(session.currentActorId).toBe("A");
    expect(session.canCreateRooms).toBe(true);
    await gateway.listRooms({});
    const [url, init] = request.mock.calls[0]!;
    expect(url).toBe("/api/v1/resources/rooms?");
    expect(new Headers(init?.headers).get("Authorization")).toBe(
      "Bearer synthetic-token-A",
    );
    expect(init).toMatchObject({
      credentials: "same-origin",
      mode: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
  });
  it.each(["read", "manage", "createRooms"] as const)(
    "requires explicit valid %s permission configuration",
    (key) => {
      expect(() =>
        createAuthenticatedResourceAccess({
          getSession: () => null,
          permissions: { ...permissions, [key]: "" },
        }),
      ).toThrow("显式配置");
    },
  );
  it.each([
    null,
    { ...trusted(), accessToken: "invalid\nheader" },
    { ...trusted(), dataScopes: undefined },
    {
      ...trusted(),
      dataScopes: { allRooms: true, roomIds: [9007199254740993] },
    },
    { ...trusted(), permissions: ["invalid permission"] },
  ])(
    "closes invalid or missing sessions before any HTTP request",
    async (value) => {
      const { actor, gateway, session, request } = await setup();
      actor.value = value as TrustedResourceSession | null;
      expect(session.currentActorId).toBeNull();
      expect(session.canManage).toBe(false);
      await expect(gateway.listRooms({})).rejects.toMatchObject({
        uncertain: false,
      });
      await expect(gateway.createRoom(draft)).rejects.toMatchObject({
        uncertain: false,
      });
      expect(request).not.toHaveBeenCalled();
    },
  );
  it("allows readers to query but rejects writes before sending", async () => {
    const { actor, gateway, session, request } = await setup();
    actor.value!.permissions = [permissions.read];
    await gateway.listRooms({});
    expect(session.canManage).toBe(false);
    await expect(
      gateway.createSeat("1", { code: "01", outlet_type: "none" }),
    ).rejects.toMatchObject({ uncertain: false });
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("requires create permission and explicit all-room scope independently of management", async () => {
    const { actor, gateway, session, request, room } = await setup();
    actor.value!.dataScopes = { allRooms: false, roomIds: ["1"] };
    expect(session.canManage).toBe(true);
    expect(session.canCreateRooms).toBe(false);
    await expect(gateway.createRoom(draft)).rejects.toMatchObject({
      uncertain: false,
    });
    await gateway.updateRoom("1", draft, room.revision);
    actor.value!.dataScopes.allRooms = true;
    actor.value!.permissions = [permissions.read, permissions.manage];
    await expect(gateway.createRoom(draft)).rejects.toMatchObject({
      uncertain: false,
    });
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("uses the captured token for each parallel request and rejects an old-session read", async () => {
    const { actor, gateway, request, room } = await setup();
    let finish!: (value: Response) => void;
    request.mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          finish = done;
        }),
    );
    const old = gateway.listRooms({});
    actor.value = {
      ...trusted(),
      subjectId: "B",
      accessToken: "synthetic-token-B",
    };
    await gateway.listRooms({});
    finish(Response.json({ items: [room], total: 1, limit: 20, offset: 0 }));
    await expect(old).rejects.toMatchObject({ uncertain: false });
    expect(
      new Headers(request.mock.calls[0]?.[1]?.headers).get("Authorization"),
    ).toBe("Bearer synthetic-token-A");
    expect(
      new Headers(request.mock.calls[1]?.[1]?.headers).get("Authorization"),
    ).toBe("Bearer synthetic-token-B");
  });
  it.each(["token", "scope", "permission"])(
    "rejects a stale same-subject response after %s replacement",
    async (change) => {
      const { actor, gateway, session, request, room } = await setup();
      let finish!: (value: Response) => void;
      request.mockImplementationOnce(
        () =>
          new Promise<Response>((done) => {
            finish = done;
          }),
      );
      const before = session.contextVersion,
        pending = gateway.listRooms({});
      if (change === "token") actor.value!.accessToken = "synthetic-token-new";
      if (change === "scope")
        actor.value!.dataScopes.roomIds = ["9007199254740993"];
      if (change === "permission")
        actor.value!.permissions = [permissions.read];
      expect(session.contextVersion).not.toBe(before);
      finish(Response.json({ items: [room], total: 1, limit: 20, offset: 0 }));
      await expect(pending).rejects.toMatchObject({ uncertain: false });
    },
  );
  it("keeps a dispatched write unknown when its session changes", async () => {
    const { actor, gateway, request, room } = await setup();
    let finish!: (value: Response) => void;
    request.mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          finish = done;
        }),
    );
    const pending = gateway.createRoom(draft);
    actor.value = null;
    finish(Response.json({ ...room, ...draft }));
    await expect(pending).rejects.toMatchObject({ uncertain: true });
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("does not retry definite server rejection or a response lost after dispatch", async () => {
    const { gateway, request } = await setup();
    request.mockResolvedValueOnce(
      new Response("private details", { status: 403 }),
    );
    await expect(gateway.createRoom(draft)).rejects.toMatchObject({
      uncertain: false,
      status: 403,
    });
    request.mockRejectedValueOnce(new TypeError("private transport details"));
    await expect(gateway.createRoom(draft)).rejects.toMatchObject({
      uncertain: true,
    });
    expect(request).toHaveBeenCalledTimes(2);
  });
  it("clears visible results for same-subject token replacement and rejects its delayed old query", async () => {
    const { actor, gateway, session, request, room } = await setup();
    const wrapper = mount(ResourceWorkspace, {
      props: { gateway, resourceSession: session },
    });
    try {
      await flushPromises();
      expect(wrapper.findAll(".room-choice")).toHaveLength(1);
      let finish!: (value: Response) => void;
      request.mockImplementationOnce(
        () =>
          new Promise<Response>((done) => {
            finish = done;
          }),
      );
      await wrapper.get(".room-panel form.filters").trigger("submit");
      request.mockResolvedValue(
        Response.json({ items: [], total: 0, limit: 20, offset: 0 }),
      );
      actor.value!.accessToken = "synthetic-new-token";
      await flushPromises();
      expect(wrapper.findAll(".room-choice")).toHaveLength(0);
      finish(Response.json({ items: [room], total: 1, limit: 20, offset: 0 }));
      await flushPromises();
      expect(wrapper.findAll(".room-choice")).toHaveLength(0);
    } finally {
      wrapper.unmount();
    }
  });
  it("requires explicit live create capability in legacy manually paired sessions", async () => {
    const { gateway, room } = await setup();
    const session = createResourceSession(gateway, {
      currentActorId: () => "A",
      canManage: () => true,
    });
    expect(session.canCreateRooms).toBe(false);
    expect(session.current!.open("room")).toBe(false);
    expect(session.current!.open("room", room)).toBe(true);
  });
  it("rechecks create capability after a draft opens without losing the draft", async () => {
    const { actor, session, request } = await setup(),
      flow = session.current!;
    expect(flow.open("room")).toBe(true);
    Object.assign(flow.state.draft, draft);
    actor.value!.dataScopes.allRooms = false;
    await flow.save();
    expect(request).not.toHaveBeenCalled();
    expect(flow.state.draft.code).toBe("NEW");
    expect(flow.state.uncertain).toBe(false);
  });
});
