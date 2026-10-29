import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import ResourceWorkspace from "./ResourceWorkspace.vue";
import { createAuthenticatedResourceAccess } from "./access";
import type { TrustedResourceSession } from "./access";

// Only the opt-in launcher supplies this loopback origin and synthetic accounts.
// Standard unit CI explicitly skips this suite; it is not evidence of HTTP acceptance.
const origin = import.meta.env.VITE_B_RESOURCE_ACCEPTANCE_ORIGIN as
  | string
  | undefined;
if (origin && !/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))
  throw new Error(
    "B HTTP acceptance only permits the disposable loopback launcher",
  );
const network = globalThis.fetch.bind(globalThis);
const permissions = {
  read: "synthetic.resource.read",
  manage: "synthetic.resource.manage",
  createRooms: "synthetic.resource.create",
};
const wrappers = new Set<VueWrapper>();
afterEach(() => {
  for (const view of wrappers) view.unmount();
  wrappers.clear();
});
function button(view: VueWrapper, text: string) {
  const result = view.findAll("button").find((item) => item.text() === text);
  if (!result) throw new Error(`Missing UI action: ${text}`);
  return result;
}
async function login(username: string): Promise<TrustedResourceSession> {
  const response = await network(origin + "/api/v1/auth/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      password: "synthetic-b-resource-password",
    }),
  });
  if (response.status !== 200)
    throw new Error(`Synthetic C login failed: ${response.status}`);
  const auth = await response.json();
  const identityResponse = await network(origin + "/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${auth.access_token}` },
  });
  if (identityResponse.status !== 200)
    throw new Error("Synthetic C identity read failed");
  const identity = await identityResponse.json();
  return {
    subjectId: identity.subject_id,
    accessToken: auth.access_token,
    permissions: identity.permissions,
    dataScopes: {
      allRooms: identity.data_scopes.all_rooms,
      roomIds: identity.data_scopes.room_ids,
    },
  };
}
function access(snapshot: TrustedResourceSession) {
  const current = ref<TrustedResourceSession | null>(snapshot);
  let posts = 0,
    loseNext = false;
  // Await an actual committed HTTP response before simulating its loss at the client.
  const request: typeof fetch = async (input, init) => {
    const path = String(input);
    if (!path.startsWith("/api/v1/resources/"))
      throw new Error("Unexpected B request target");
    if (init?.method === "POST") posts++;
    const result = await network(origin + path, init);
    if (loseNext && init?.method === "POST" && result.ok) {
      loseNext = false;
      await result.arrayBuffer();
      throw new TypeError("synthetic response loss after server commit");
    }
    return result;
  };
  const result = createAuthenticatedResourceAccess({
    getSession: () => current.value,
    permissions,
    request,
  });
  return {
    ...result,
    current,
    get posts() {
      return posts;
    },
    loseNextResponse: () => {
      loseNext = true;
    },
  };
}
async function view(client: ReturnType<typeof access>) {
  const result = mount(ResourceWorkspace, {
    props: { gateway: client.gateway, resourceSession: client.session },
  });
  wrappers.add(result);
  await vi.waitFor(() =>
    expect(result.findAll(".room-choice").length).toBeGreaterThan(0),
  );
  await vi.waitFor(() =>
    expect(button(result, "新增座位").attributes("disabled")).toBeUndefined(),
  );
  return result;
}
async function createRoom(view: VueWrapper, code: string) {
  await button(view, "新增教室").trigger("click");
  await view.get("#resource-code").setValue(code);
  await view.get("#room-name").setValue("HTTP 合成教室");
  await view.get("#room-location").setValue("隔离验收区");
  await view.get(".editor form").trigger("submit");
}
const roomDraft = { code: "B-SCOPE-DENIED", name: "合成", location: "隔离区" };

describe.skipIf(!origin)(
  "B opt-in component/client -> actual C/B HTTP -> PostgreSQL",
  () => {
    it("creates and edits rooms and seats through the actual component, then rereads persisted values", async () => {
      const client = access(await login("b-manager")),
        page = await view(client);
      await createRoom(page, "B-HTTP-CREATE");
      await vi.waitFor(() => expect(page.text()).toContain("教室已保存"));
      await vi.waitFor(() =>
        expect(page.findAll(".room-choice")).toHaveLength(1),
      );
      const room = (await client.gateway.listRooms({ q: "B-HTTP-CREATE" }))
        .items[0]!;
      await button(page, "编辑教室").trigger("click");
      await page.get("#room-name").setValue("HTTP 修改教室");
      await page.get(".editor form").trigger("submit");
      await vi.waitFor(() => expect(page.find(".editor").exists()).toBe(false));
      await vi.waitFor(() =>
        expect(button(page, "新增座位").attributes("disabled")).toBeUndefined(),
      );
      await button(page, "新增座位").trigger("click");
      await page.get("#resource-code").setValue("HTTP-01");
      await page.get("#seat-outlet").setValue("fixed");
      await page.get(".editor form").trigger("submit");
      await vi.waitFor(() => expect(page.text()).toContain("HTTP-01"));
      await vi.waitFor(() => expect(page.find(".editor").exists()).toBe(false));
      await button(page, "编辑").trigger("click");
      await page.get("#seat-outlet").setValue("rail");
      await page.get(".editor form").trigger("submit");
      await vi.waitFor(() => expect(page.find(".editor").exists()).toBe(false));
      const freshRoom = (await client.gateway.listRooms({ q: room.code }))
        .items[0]!;
      expect(freshRoom.name).toBe("HTTP 修改教室");
      expect(freshRoom.revision).not.toBe(room.revision);
      const seats = await client.gateway.listSeats(room.id, {});
      expect(
        seats.items.map((seat) => [seat.code, seat.outlet_type, seat.room_id]),
      ).toEqual([["HTTP-01", "rail", room.id]]);
    });
    it("preserves a real BIGINT identifier as a string over HTTP", async () => {
      const client = access(await login("b-manager"));
      const room = (await client.gateway.listRooms({ q: "B-BIG" })).items[0]!;
      expect(room.id).toBe("9007199254740993");
      const seat = await client.gateway.createSeat(room.id, {
        code: "BIG-01",
        outlet_type: "none",
      });
      expect(seat.room_id).toBe(room.id);
      expect(
        (await client.gateway.listSeats(room.id, {})).items[0]?.room_id,
      ).toBe(room.id);
    });
    it("keeps read-only users closed for writes before transport", async () => {
      const client = access(await login("b-reader"));
      expect(
        (await client.gateway.listRooms({})).items.map((room) => room.id),
      ).toEqual(["1"]);
      await expect(client.gateway.createRoom(roomDraft)).rejects.toMatchObject({
        uncertain: false,
      });
      expect(client.posts).toBe(0);
      const page = mount(ResourceWorkspace, {
        props: { gateway: client.gateway, resourceSession: client.session },
      });
      wrappers.add(page);
      await vi.waitFor(() =>
        expect(page.findAll(".room-choice")).toHaveLength(1),
      );
      expect(button(page, "新增教室").attributes("disabled")).toBeDefined();
      expect(button(page, "新增座位").attributes("disabled")).toBeDefined();
    });
    it("allows scoped management, blocks creation and enforces scope again in the actual backend", async () => {
      const identity = await login("b-scoped"),
        client = access(identity);
      expect(client.session.canManage).toBe(true);
      expect(client.session.canCreateRooms).toBe(false);
      await expect(client.gateway.createRoom(roomDraft)).rejects.toMatchObject({
        uncertain: false,
      });
      expect(client.posts).toBe(0);
      const seat = await client.gateway.createSeat("1", {
        code: "SCOPED-01",
        outlet_type: "fixed",
      });
      expect(seat.room_id).toBe("1");
      await expect(
        client.gateway.listSeats("9007199254740993", {}),
      ).rejects.toMatchObject({ status: 404 });
      // Even a forged frontend capability cannot grant C/B authorization.
      const forged = access({
        ...identity,
        dataScopes: { allRooms: true, roomIds: [] },
      });
      await expect(forged.gateway.createRoom(roomDraft)).rejects.toMatchObject({
        uncertain: false,
        status: 403,
      });
      expect(forged.posts).toBe(1);
    });
    it("rejects a server-revoked C session without fabricating success", async () => {
      const identity = await login("b-manager"),
        client = access(identity);
      const response = await network(origin + "/api/v1/auth/sessions/current", {
        method: "DELETE",
        headers: { Authorization: `Bearer ${identity.accessToken}` },
      });
      expect(response.status).toBe(204);
      await expect(client.gateway.createRoom(roomDraft)).rejects.toMatchObject({
        uncertain: false,
        status: 401,
      });
      client.current.value = null;
      expect(client.session.currentActorId).toBeNull();
      expect(client.session.canManage).toBe(false);
    });
    it("retains a committed write with a lost response across unmount, blocks another POST and permits read-only reconciliation", async () => {
      const client = access(await login("b-manager")),
        first = await view(client);
      client.loseNextResponse();
      await createRoom(first, "B-HTTP-LOST");
      await vi.waitFor(() =>
        expect(first.text()).toContain("原资源操作仍待核对"),
      );
      await button(first, "关闭表单并核对列表").trigger("click");
      first.unmount();
      wrappers.delete(first);
      const returned = mount(ResourceWorkspace, {
        props: { gateway: client.gateway, resourceSession: client.session },
      });
      wrappers.add(returned);
      await vi.waitFor(() =>
        expect(returned.findAll(".room-choice").length).toBeGreaterThan(0),
      );
      expect(returned.text()).toContain("B-HTTP-LOST");
      expect(button(returned, "新增教室").attributes("disabled")).toBeDefined();
      expect(client.session.current!.open("room")).toBe(false);
      await client.session.current!.save();
      expect(client.posts).toBe(1);
      const result = await client.gateway.listRooms({ q: "B-HTTP-LOST" });
      expect(result.total).toBe(1);
      expect(result.items[0]?.code).toBe("B-HTTP-LOST");
      expect(client.session.pending).toBe(true);
    });
  },
);
