import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import ResourceWorkspace from "./ResourceWorkspace.vue";
import { createPrototypeResourceGateway } from "./prototype";
import { createResourceSession } from "./session";
import type { ResourceSession } from "./session";
import { ResourceMessage } from "./models";
import type { ResourceGateway, Room, Page } from "./models";
const wrappers = new Set<VueWrapper>();
afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount();
  wrappers.clear();
});
function button(wrapper: VueWrapper, text: string) {
  const target = wrapper.findAll("button").find((item) => item.text() === text);
  if (!target) throw new Error(text);
  return target;
}
function setup() {
  const actor = ref<string | null>("A"),
    allowed = ref(true),
    createAllowed = ref(true);
  const gateway: ResourceGateway = {
    ...createPrototypeResourceGateway(),
    mode: "live",
  };
  const session = createResourceSession(gateway, {
    currentActorId: () => actor.value,
    canManage: () => allowed.value,
    canCreateRooms: () => allowed.value && createAllowed.value,
  });
  return { actor, allowed, createAllowed, gateway, session };
}
async function view(gateway: ResourceGateway, session?: ResourceSession) {
  const wrapper = mount(ResourceWorkspace, {
    props: { gateway, resourceSession: session, allowManage: true },
  });
  wrappers.add(wrapper);
  await flushPromises();
  return wrapper;
}
async function begin(wrapper: VueWrapper) {
  await button(wrapper, "新增教室").trigger("click");
  await wrapper.get("#resource-code").setValue("NEW");
  await wrapper.get("#room-name").setValue("新示例");
  await wrapper.get("#room-location").setValue("示例区域");
  await wrapper.get(".editor form").trigger("submit");
  await flushPromises();
}
function remove(wrapper: VueWrapper) {
  wrapper.unmount();
  wrappers.delete(wrapper);
}
describe("B resource actual component lifecycle", () => {
  it("keeps live reads and writes closed without a trusted retained session", async () => {
    const { gateway } = setup(),
      list = vi.spyOn(gateway, "listRooms"),
      create = vi.spyOn(gateway, "createRoom"),
      wrapper = await view(gateway);
    expect(list).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
    expect(button(wrapper, "新增教室").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("尚未接入");
  });
  it("does not bind a session to a different gateway", async () => {
    const first = setup(),
      second = setup(),
      list = vi.spyOn(second.gateway, "listRooms"),
      wrapper = await view(second.gateway, first.session);
    expect(list).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("尚未接入");
  });
  it("retains an unknown operation through close, unmount and return without another POST", async () => {
    const { gateway, session } = setup(),
      original = gateway.createRoom;
    gateway.createRoom = vi
      .fn()
      .mockImplementation(async (...args: Parameters<typeof original>) => {
        await original(...args);
        throw new ResourceMessage("lost response", true);
      });
    const first = await view(gateway, session);
    await begin(first);
    await button(first, "关闭表单并核对列表").trigger("click");
    expect(button(first, "新增教室").attributes("disabled")).toBeDefined();
    expect(first.find(".editor").exists()).toBe(false);
    remove(first);
    const returned = await view(gateway, session);
    expect(returned.text()).toContain("原资源操作仍待核对");
    expect(returned.text()).toContain("NEW");
    expect(button(returned, "新增教室").attributes("disabled")).toBeDefined();
    expect(gateway.createRoom).toHaveBeenCalledTimes(1);
    expect(returned.findAll(".room-choice").length).toBeGreaterThan(0);
  });
  it("finishes a save while absent and shows the acknowledged result on return", async () => {
    const { gateway, session } = setup(),
      original = gateway.createRoom;
    let resolve!: (value: Room) => void;
    gateway.createRoom = vi.fn().mockReturnValue(
      new Promise<Room>((done) => {
        resolve = done;
      }),
    );
    const first = await view(gateway, session);
    await begin(first);
    remove(first);
    expect(session.pending).toBe(true);
    resolve(
      await original({ code: "NEW", name: "新示例", location: "示例区域" }),
    );
    await flushPromises();
    const returned = await view(gateway, session);
    expect(returned.text()).toContain("教室已保存");
    expect(returned.text()).toContain("NEW");
    expect(gateway.createRoom).toHaveBeenCalledTimes(1);
  });
  it("hides the original account draft and restores its unknown flow on return", async () => {
    const { actor, gateway, session } = setup();
    gateway.createRoom = vi
      .fn()
      .mockRejectedValue(new ResourceMessage("unknown", true));
    const wrapper = await view(gateway, session);
    await begin(wrapper);
    actor.value = "B";
    await flushPromises();
    expect(wrapper.find(".editor").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("原资源操作仍待核对");
    actor.value = "A";
    await flushPromises();
    expect(wrapper.text()).toContain("原资源操作仍待核对");
    expect(
      (wrapper.get("#resource-code").element as HTMLInputElement).value,
    ).toBe("NEW");
  });
  it("clears visible data on permission revocation and blocks old saves", async () => {
    const { allowed, gateway, session } = setup(),
      create = vi.spyOn(gateway, "createRoom");
    const wrapper = await view(gateway, session);
    await button(wrapper, "新增教室").trigger("click");
    allowed.value = false;
    await flushPromises();
    expect(wrapper.find(".editor").exists()).toBe(false);
    await session.current!.save();
    expect(create).not.toHaveBeenCalled();
    expect(button(wrapper, "新增教室").attributes("disabled")).toBeDefined();
  });
  it("keeps scoped management available but freezes a revoked create draft with an exit", async () => {
    const { createAllowed, gateway, session } = setup(),
      create = vi.spyOn(gateway, "createRoom");
    const wrapper = await view(gateway, session);
    await button(wrapper, "新增教室").trigger("click");
    await wrapper.get("#resource-code").setValue("RETAINED");
    createAllowed.value = false;
    await flushPromises();
    expect(wrapper.text()).toContain("新建教室权限已变化");
    expect(wrapper.get("#resource-code").attributes("disabled")).toBeDefined();
    await session.current!.save();
    expect(create).not.toHaveBeenCalled();
    await button(wrapper, "取消").trigger("click");
    expect(button(wrapper, "新增教室").attributes("disabled")).toBeDefined();
    expect(button(wrapper, "编辑教室").attributes("disabled")).toBeUndefined();
    expect(button(wrapper, "新增座位").attributes("disabled")).toBeUndefined();
  });
  it("ignores a delayed old-account query even after switching back", async () => {
    const { actor, gateway, session } = setup(),
      original = gateway.listRooms;
    let resolve!: (value: Page<Room>) => void;
    gateway.listRooms = vi
      .fn()
      .mockReturnValueOnce(
        new Promise<Page<Room>>((done) => {
          resolve = done;
        }),
      )
      .mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    const wrapper = await view(gateway, session);
    actor.value = "B";
    await flushPromises();
    actor.value = "A";
    await flushPromises();
    resolve(await original({}));
    await flushPromises();
    expect(wrapper.findAll(".room-choice")).toHaveLength(0);
  });
});
