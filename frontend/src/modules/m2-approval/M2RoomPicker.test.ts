import { afterEach, describe, expect, it, vi } from "vitest";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import M2RoomPicker from "./M2RoomPicker.vue";
import M2Workspace from "./M2Workspace.vue";
import type { RoomOptionsPage } from "./models";
import { GatewayMessage } from "./models";
enableAutoUnmount(afterEach);
const item = {
  id: "9007199254740993",
  code: "SYN-ROOM",
  name: "合成教室",
  location: "示例楼",
};
const page = (offset = 0): RoomOptionsPage => ({
  items: [item],
  total: 121,
  limit: 20,
  offset,
});
const select = async (wrapper: ReturnType<typeof mount>) => {
  await wrapper.get("#m2-room").setValue(item.id);
};
describe("paged authorized room picker", () => {
  it("loads, selects a string ID, then clears it before paging", async () => {
    const loadPage = vi
      .fn()
      .mockResolvedValueOnce(page())
      .mockResolvedValue(page(20));
    const wrapper = mount(M2RoomPicker, {
      props: { loadPage, disabled: false },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("符合范围 121 间");
    await select(wrapper);
    expect(wrapper.emitted("select")?.at(-1)).toEqual([item]);
    await wrapper
      .findAll("button")
      .find((button) => button.text() === "下一页教室")!
      .trigger("click");
    await flushPromises();
    expect(loadPage).toHaveBeenLastCalledWith({ q: "", limit: 20, offset: 20 });
    expect(wrapper.emitted("select")?.at(-1)).toEqual([undefined]);
    expect((wrapper.get("#m2-room").element as HTMLSelectElement).value).toBe(
      "",
    );
  });
  it("resets search offset to zero and uses the applied search when paging", async () => {
    const loadPage = vi.fn().mockResolvedValue(page());
    const wrapper = mount(M2RoomPicker, {
      props: { loadPage, disabled: false },
    });
    await flushPromises();
    await wrapper.get("#m2-room-query").setValue("OWN");
    await wrapper.findAll("button")[0]!.trigger("click");
    await flushPromises();
    expect(loadPage).toHaveBeenLastCalledWith({
      q: "OWN",
      limit: 20,
      offset: 0,
    });
    await wrapper.get("#m2-room-query").setValue("not applied");
    await wrapper.findAll("button").at(-1)!.trigger("click");
    expect(loadPage).toHaveBeenLastCalledWith({
      q: "OWN",
      limit: 20,
      offset: 20,
    });
  });
  it("shows an explicit retryable error and never retains a prior selection", async () => {
    const loadPage = vi
      .fn()
      .mockResolvedValueOnce(page())
      .mockRejectedValue(new GatewayMessage("当前账号没有选择教室的权限。"));
    const wrapper = mount(M2RoomPicker, {
      props: { loadPage, disabled: false },
    });
    await flushPromises();
    await select(wrapper);
    await wrapper.findAll("button")[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("没有选择教室");
    expect(wrapper.emitted("select")?.at(-1)).toEqual([undefined]);
    expect(wrapper.findAll("option")).toHaveLength(1);
    expect(
      (wrapper.get("#m2-room").element as HTMLSelectElement).disabled,
    ).toBe(true);
  });
  it("ignores late results from an older search", async () => {
    let resolve!: (page: RoomOptionsPage) => void;
    const loadPage = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<RoomOptionsPage>((done) => {
            resolve = done;
          }),
      )
      .mockResolvedValue({ ...page(), items: [{ ...item, name: "最新教室" }] });
    const wrapper = mount(M2RoomPicker, {
      props: { loadPage, disabled: false },
    });
    await wrapper.get("#m2-room-query").setValue("new");
    await wrapper.findAll("button")[0]!.trigger("click");
    await flushPromises();
    resolve({ ...page(), items: [{ ...item, name: "旧教室" }] });
    await flushPromises();
    expect(wrapper.text()).toContain("最新教室");
    expect(wrapper.text()).not.toContain("旧教室");
  });
  it("allows searching again after an empty result", async () => {
    const loadPage = vi
      .fn()
      .mockResolvedValueOnce({ ...page(), items: [], total: 0 })
      .mockResolvedValue(page());
    const wrapper = mount(M2RoomPicker, {
      props: { loadPage, disabled: false },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("没有符合条件");
    await wrapper.findAll("button")[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("合成教室");
  });
  it("keeps application form drafts while searches clear the selected room and block submission", async () => {
    const submit = vi.fn(),
      roomOptions = vi.fn().mockResolvedValue(page());
    const wrapper = mount(M2Workspace, {
      props: {
        gateway: {
          mode: "live",
          load: async () => ({ rooms: [], applications: [], canSubmit: true }),
          submit,
          roomOptions,
        },
      },
    });
    await flushPromises();
    const newButton = wrapper
      .findAll("nav button")
      .find((button) => button.text() === "新建申请")!;
    await newButton.trigger("click");
    await flushPromises();
    await wrapper.get("#m2-purpose").setValue("保留的用途");
    await select(wrapper);
    expect(
      (wrapper.get('button[type="submit"]').element as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    await wrapper
      .findAll("button")
      .find((button) => button.text() === "查询教室")!
      .trigger("click");
    await flushPromises();
    expect(
      (wrapper.get('button[type="submit"]').element as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (wrapper.get("#m2-purpose").element as HTMLTextAreaElement).value,
    ).toBe("保留的用途");
    expect(submit).not.toHaveBeenCalled();
  });
});
