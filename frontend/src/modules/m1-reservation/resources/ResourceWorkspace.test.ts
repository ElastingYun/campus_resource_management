import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import ResourceWorkspace from "./ResourceWorkspace.vue";
import { createPrototypeResourceGateway } from "./prototype";
import { createUnconfiguredResourceGateway } from "./gateway";
import { ResourceMessage } from "./models";
import type { Page, ResourceGateway, Seat } from "./models";

const wrappers: VueWrapper[] = [];
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount());
  wrappers.length = 0;
});
async function setup(
  gateway: ResourceGateway = createPrototypeResourceGateway(),
) {
  const wrapper = mount(ResourceWorkspace, { props: { gateway } });
  wrappers.push(wrapper);
  await flushPromises();
  return { wrapper, gateway };
}
function button(wrapper: VueWrapper, text: string) {
  const target = wrapper.findAll("button").find((item) => item.text() === text);
  if (!target) throw new Error(`Missing button: ${text}`);
  return target;
}
async function fillRoom(wrapper: VueWrapper, code = "NEW-101") {
  await wrapper.get("#resource-code").setValue(code);
  await wrapper.get("#room-name").setValue("新增示例教室");
  await wrapper.get("#room-location").setValue("示例三层");
}

describe("B resource workspace", () => {
  it("loads synthetic rooms and seats with an explicit demo boundary", async () => {
    const { wrapper } = await setup();
    expect(wrapper.text()).toContain("合成数据演示");
    expect(wrapper.text()).toContain("示例自习室 A101");
    expect(wrapper.findAll("tbody tr")).toHaveLength(2);
    expect(wrapper.text()).toContain("固定插座");
    expect(wrapper.text()).toContain("不代表某个时段可以预约");
  });
  it("creates a room then reads its result through the gateway", async () => {
    const { wrapper, gateway } = await setup();
    const create = vi.spyOn(gateway, "createRoom");
    await button(wrapper, "新增教室").trigger("click");
    await fillRoom(wrapper);
    await wrapper.get(".editor form").trigger("submit");
    await flushPromises();
    expect(create).toHaveBeenCalledWith({
      code: "NEW-101",
      name: "新增示例教室",
      location: "示例三层",
    });
    expect(wrapper.text()).toContain("示例教室已保存");
    expect(wrapper.get("#seat-list-title").text()).toBe("新增示例教室");
    expect((await gateway.listRooms({ q: "NEW-101" })).total).toBe(1);
  });
  it("edits room metadata using the original revision", async () => {
    const { wrapper, gateway } = await setup();
    const original = (await gateway.listRooms({})).items[0]!;
    const update = vi.spyOn(gateway, "updateRoom");
    await button(wrapper, "编辑教室").trigger("click");
    await wrapper.get("#room-name").setValue("修改后的名称");
    await wrapper.get(".editor form").trigger("submit");
    await flushPromises();
    expect(update.mock.calls[0]?.[2]).toBe(original.revision);
    expect(wrapper.get("#seat-list-title").text()).toBe("修改后的名称");
  });
  it("creates and edits a seat and filters by outlet", async () => {
    const { wrapper } = await setup();
    await button(wrapper, "新增座位").trigger("click");
    await wrapper.get("#resource-code").setValue("03");
    await wrapper.get("#seat-outlet").setValue("rail");
    await wrapper.get(".editor form").trigger("submit");
    await flushPromises();
    expect(wrapper.findAll("tbody tr")).toHaveLength(3);
    await wrapper.get('[aria-label="编辑座位 03"]').trigger("click");
    await wrapper.get("#resource-code").setValue("03-NEW");
    await wrapper.get(".editor form").trigger("submit");
    await flushPromises();
    await wrapper.get("#outlet-filter").setValue("rail");
    await wrapper.get(".seat-filters").trigger("submit");
    await flushPromises();
    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
    expect(wrapper.find("tbody").text()).toContain("03-NEW");
  });
  it("validates blank fields without sending writes", async () => {
    const { wrapper, gateway } = await setup();
    const create = vi.spyOn(gateway, "createRoom");
    await button(wrapper, "新增教室").trigger("click");
    await fillRoom(wrapper, "   ");
    await wrapper.get(".editor form").trigger("submit");
    expect(wrapper.get('[role="alert"]').text()).toContain("填写完整资料");
    expect(create).not.toHaveBeenCalled();
  });
  it("keeps the room context fixed while editing a seat", async () => {
    const { wrapper } = await setup();
    await button(wrapper, "新增座位").trigger("click");
    expect(wrapper.get("#room-search").attributes("disabled")).toBeDefined();
    expect(wrapper.get("#seat-search").attributes("disabled")).toBeDefined();
    expect(wrapper.get("#outlet-filter").attributes("disabled")).toBeDefined();
    expect(
      wrapper
        .findAll(".room-choice")
        .every((item) => item.attributes("disabled") !== undefined),
    ).toBe(true);
  });
  it("keeps correctable input after a rejected write", async () => {
    const { wrapper, gateway } = await setup();
    vi.spyOn(gateway, "createRoom").mockRejectedValue(
      new ResourceMessage("编号重复", false, 409),
    );
    await button(wrapper, "新增教室").trigger("click");
    await fillRoom(wrapper);
    await wrapper.get(".editor form").trigger("submit");
    await flushPromises();
    expect(
      (wrapper.get("#resource-code").element as HTMLInputElement).value,
    ).toBe("NEW-101");
    expect(wrapper.get('[role="alert"]').text()).toBe("编号重复");
    expect(wrapper.find(".notice").exists()).toBe(false);
  });
  it("blocks repeat writes when delivery is uncertain", async () => {
    const { wrapper, gateway } = await setup();
    const create = vi
      .spyOn(gateway, "createRoom")
      .mockRejectedValue(new ResourceMessage("请先核对保存结果", true));
    await button(wrapper, "新增教室").trigger("click");
    await fillRoom(wrapper);
    await wrapper.get(".editor form").trigger("submit");
    await flushPromises();
    expect(
      wrapper.get('.editor [type="submit"]').attributes("disabled"),
    ).toBeDefined();
    await wrapper.get(".editor form").trigger("submit");
    expect(create).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("关闭表单并核对列表");
  });
  it("does not double-submit an in-flight save", async () => {
    const { wrapper, gateway } = await setup();
    const create = vi
      .spyOn(gateway, "createRoom")
      .mockImplementation(() => new Promise(() => {}));
    await button(wrapper, "新增教室").trigger("click");
    await fillRoom(wrapper);
    await wrapper.get(".editor form").trigger("submit");
    await wrapper.get(".editor form").trigger("submit");
    expect(create).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("正在保存");
  });
  it("does not overwrite a new room's seats with a late old response", async () => {
    const gateway = createPrototypeResourceGateway();
    const realList = gateway.listSeats.bind(gateway);
    let finishOld!: (value: Page<Seat>) => void;
    vi.spyOn(gateway, "listSeats").mockImplementation((id, query) =>
      id === "1"
        ? new Promise((resolve) => {
            finishOld = resolve;
          })
        : realList(id, query),
    );
    const { wrapper } = await setup(gateway);
    const second = wrapper
      .findAll(".room-choice")
      .find((item) => item.text().includes("B201"))!;
    await second.trigger("click");
    await flushPromises();
    expect(wrapper.get("#seat-list-title").text()).toContain("B201");
    finishOld({
      items: [
        {
          id: "9",
          room_id: "1",
          code: "LATE-WRONG",
          outlet_type: "none",
          enabled: true,
          revision: "0".repeat(64),
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    });
    await flushPromises();
    expect(wrapper.text()).not.toContain("LATE-WRONG");
  });
  it("shows empty search results", async () => {
    const { wrapper } = await setup();
    await wrapper.get("#room-search").setValue("MISSING");
    await wrapper.get(".room-panel form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("没有符合条件的教室");
    expect(wrapper.findAll("tbody tr")).toHaveLength(0);
  });
  it("keeps unconfigured mode empty and unwritable", async () => {
    const { wrapper, gateway } = await setup(
      createUnconfiguredResourceGateway(),
    );
    const create = vi.spyOn(gateway, "createRoom");
    expect(wrapper.text()).toContain("真实资源服务尚未接入");
    expect(wrapper.text()).not.toContain("DEMO-A101");
    expect(button(wrapper, "新增教室").attributes("disabled")).toBeDefined();
    expect(create).not.toHaveBeenCalled();
  });
  it("sanitizes unexpected errors instead of displaying private details", async () => {
    const gateway = createPrototypeResourceGateway();
    vi.spyOn(gateway, "listRooms").mockRejectedValue(
      new Error("postgres://private-secret"),
    );
    const { wrapper } = await setup(gateway);
    expect(wrapper.text()).not.toContain("private-secret");
    expect(wrapper.text()).toContain("操作未完成");
  });
});
