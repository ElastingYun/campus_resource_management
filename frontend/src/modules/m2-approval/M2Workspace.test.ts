import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import M2Workspace from "./M2Workspace.vue";
import { createPrototypeGateway, createUnconfiguredGateway } from "./gateways";
import { GatewayMessage } from "./models";
import type { ApplicationView, M2Gateway, WorkspaceData } from "./models";

enableAutoUnmount(afterEach);
afterEach(() => vi.unstubAllGlobals());

async function openForm(wrapper: ReturnType<typeof mount>) {
  const button = wrapper
    .findAll("nav button")
    .find((item) => item.text() === "新建申请")!;
  await button.trigger("click");
}
async function fillForm(wrapper: ReturnType<typeof mount>) {
  await wrapper.get("#m2-room").setValue("DEMO-ROOM-01");
  await wrapper.get("#m2-purpose").setValue("  测试用途  ");
  await wrapper.get("#m2-start").setValue("2026-10-29T09:00");
  await wrapper.get("#m2-end").setValue("2026-10-29T11:00");
}

describe("M2 workspace observable behavior", () => {
  it("labels synthetic data, loads applications and opens a selected detail", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const wrapper = mount(M2Workspace, {
      props: { gateway: createPrototypeGateway() },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("交互原型 · 合成数据");
    expect(wrapper.findAll(".record-card")).toHaveLength(3);
    await wrapper.findAll(".record-card")[1]!.trigger("click");
    expect(wrapper.get('[aria-label="申请详情"]').text()).toContain("DEMO-002");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows an empty result and removes unrelated details after filtering", async () => {
    const wrapper = mount(M2Workspace, {
      props: { gateway: createPrototypeGateway() },
    });
    await flushPromises();
    await wrapper.get("#m2-search").setValue("不存在的申请");
    expect(wrapper.text()).toContain("没有符合条件的申请");
    expect(wrapper.find('[aria-label="申请详情"]').exists()).toBe(false);
  });

  it("rejects missing or reversed time input before submitting, then adds a demo record", async () => {
    const gateway = createPrototypeGateway();
    const submit = vi.spyOn(gateway, "submit");
    const wrapper = mount(M2Workspace, { props: { gateway } });
    await flushPromises();
    await openForm(wrapper);
    await wrapper.get("form").trigger("submit");
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "填写用途和完整时段",
    );
    await fillForm(wrapper);
    await wrapper.get("#m2-end").setValue("2026-10-29T08:00");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "结束时间需要晚于开始时间",
    );
    expect(submit).not.toHaveBeenCalled();
    await wrapper.get("#m2-end").setValue("2026-10-29T11:00");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit.mock.calls[0]![0].purpose).toBe("测试用途");
    expect(wrapper.findAll(".record-card")).toHaveLength(4);
    expect(wrapper.get('[role="status"]').text()).toContain("没有发送真实申请");
  });

  it("retains input and does not report success when submit fails", async () => {
    const demo = createPrototypeGateway();
    const gateway: M2Gateway = {
      mode: "live",
      load: demo.load,
      submit: vi
        .fn()
        .mockRejectedValue(
          new GatewayMessage("服务拒绝了本次操作，请检查权限。"),
        ),
    };
    const wrapper = mount(M2Workspace, { props: { gateway } });
    await flushPromises();
    await openForm(wrapper);
    await fillForm(wrapper);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("请检查权限");
    expect(
      (wrapper.get("#m2-purpose").element as HTMLTextAreaElement).value,
    ).toBe("  测试用途  ");
    expect(wrapper.find(".notice").exists()).toBe(false);
  });

  it("prevents duplicate writes while a request is pending", async () => {
    const demo = createPrototypeGateway();
    let resolve!: (record: ApplicationView) => void;
    const data = await demo.load();
    const submit = vi.fn(
      () =>
        new Promise<ApplicationView>((done) => {
          resolve = done;
        }),
    );
    const wrapper = mount(M2Workspace, {
      props: { gateway: { ...demo, submit } },
    });
    await flushPromises();
    await openForm(wrapper);
    await fillForm(wrapper);
    await wrapper.get("form").trigger("submit");
    await wrapper.get("form").trigger("submit");
    expect(submit).toHaveBeenCalledTimes(1);
    expect(
      wrapper.get('button[type="submit"]').attributes("disabled"),
    ).toBeDefined();
    resolve(data.applications[0]!);
    await flushPromises();
    expect(wrapper.find(".notice").exists()).toBe(true);
  });

  it("does not silently fall back to fixtures when real integration is unconfigured", async () => {
    const wrapper = mount(M2Workspace, {
      props: { gateway: createUnconfiguredGateway() },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("申请服务尚未接入");
    expect(wrapper.text()).not.toContain("DEMO-001");
    expect(wrapper.find(".prototype-banner").exists()).toBe(false);
    await openForm(wrapper);
    expect(
      wrapper.get('button[type="submit"]').attributes("disabled"),
    ).toBeDefined();
    expect(wrapper.findAll("option")).toHaveLength(1);
  });

  it("distinguishes loading and an empty workspace", async () => {
    let resolve!: (data: WorkspaceData) => void;
    const gateway: M2Gateway = {
      mode: "live",
      load: () =>
        new Promise((done) => {
          resolve = done;
        }),
      submit: vi.fn(),
    };
    const wrapper = mount(M2Workspace, { props: { gateway } });
    await nextTick();
    expect(wrapper.get('[role="status"]').text()).toContain("正在载入");
    resolve({ rooms: [], applications: [] });
    await flushPromises();
    expect(wrapper.text()).toContain("没有符合条件的申请");
    expect(wrapper.text()).not.toContain("正在载入");
  });

  it("changes synthetic review results only through explicitly labelled preview actions", async () => {
    const wrapper = mount(M2Workspace, {
      props: { gateway: createPrototypeGateway() },
    });
    await flushPromises();
    await wrapper.findAll("nav button")[2]!.trigger("click");
    expect(wrapper.text()).toContain("不代表当前账号拥有审批权限");
    await wrapper.get(".decision-actions .primary").trigger("click");
    await flushPromises();
    expect(wrapper.get('[aria-label="申请详情"]').text()).toContain(
      "示例已处理",
    );
    expect(wrapper.get('[role="status"]').text()).toContain("没有执行真实审批");
  });
  it("masks unexpected load errors and can recover without synthetic fallback", async () => {
    const load = vi
      .fn()
      .mockRejectedValueOnce(
        new Error("internal-host-and-token-must-not-be-rendered"),
      )
      .mockResolvedValue({ rooms: [], applications: [] });
    const wrapper = mount(M2Workspace, {
      props: { gateway: { mode: "live", load, submit: vi.fn() } },
    });
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("暂时无法完成操作");
    expect(wrapper.text()).not.toContain("internal-host-and-token");
    expect(wrapper.text()).not.toContain("DEMO-001");
    await wrapper.get(".page-heading button").trigger("click");
    await flushPromises();
    expect(load).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("没有符合条件的申请");
  });
});
