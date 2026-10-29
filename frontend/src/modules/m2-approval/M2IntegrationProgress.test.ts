import { afterEach, describe, expect, it, vi } from "vitest";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import M2IntegrationProgress from "./M2IntegrationProgress.vue";
import M2Workspace from "./M2Workspace.vue";
import type { ApplicationDetails, IntegrationProgress } from "./models";
import { applicationId, integrationProgress } from "./c-test-fixtures";
import { parseIntegrationProgress } from "./integration-progress";
enableAutoUnmount(afterEach);
const record = (): ApplicationDetails => ({
  id: applicationId,
  roomId: "1",
  roomName: "合成测试教室",
  purpose: "合成进度测试",
  startsAt: "2030-01-02T01:00:00Z",
  endsAt: "2030-01-02T03:00:00Z",
  statusLabel: "审批已通过",
  statusTone: "neutral",
  note: "占用尚未确认",
  version: 1,
  allowedActions: [],
  history: [],
  integrationStatus: "APPLY_UNKNOWN",
  effective: false,
});
const attention = () =>
  parseIntegrationProgress(
    integrationProgress({
      operations: [
        {
          ...integrationProgress().operations[0]!,
          state: "ATTENTION",
          attempts: 3,
          error_code: "RETRY_LIMIT",
        },
      ],
    }),
  );

describe("observable integration diagnostics", () => {
  it("refreshes the same version from UNKNOWN to ATTENTION without offering retry writes", async () => {
    const loadProgress = vi
      .fn()
      .mockResolvedValueOnce(parseIntegrationProgress(integrationProgress()))
      .mockResolvedValue(attention());
    const wrapper = mount(M2IntegrationProgress, {
      props: { application: record(), loadProgress },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("结果尚未确认");
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(loadProgress).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("已领取 3 次");
    expect(wrapper.text()).toContain("自动重试已停止");
    expect(wrapper.findAll("button").map((button) => button.text())).toEqual([
      "刷新占用进度",
    ]);
    expect(wrapper.text()).toContain("领取次数不等于远端写入次数");
  });
  it("removes prior successful progress when a subsequent read fails and keeps raw errors hidden", async () => {
    const loadProgress = vi
      .fn()
      .mockResolvedValueOnce(attention())
      .mockRejectedValue(new Error("private service credentials"));
    const wrapper = mount(M2IntegrationProgress, {
      props: { application: record(), loadProgress },
    });
    await flushPromises();
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("暂时无法查询");
    expect(wrapper.find(".operation-list").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("private service credentials");
  });
  it.each([
    { version: 2 },
    { applicationId: "00000000-0000-4000-8000-000000000099" },
    { integrationStatus: "APPLIED", effective: true },
  ])(
    "does not mix an incompatible snapshot with application details %j",
    async (changes) => {
      const wrapper = mount(M2IntegrationProgress, {
        props: {
          application: record(),
          loadProgress: async () => ({ ...attention(), ...changes }),
        },
      });
      await flushPromises();
      expect(wrapper.get('[role="alert"]').text()).toContain("重新载入申请");
      expect(wrapper.find(".operation-list").exists()).toBe(false);
    },
  );
  it("labels older DONE as historical and does not use it to claim the current release succeeded", async () => {
    const progress = attention();
    progress.generation = 2;
    progress.integrationStatus = "RELEASE_UNKNOWN";
    progress.operations.unshift({
      ...progress.operations[0]!,
      id: "00000000-0000-4000-8000-000000000021",
      state: "DONE",
      errorCode: null,
    });
    progress.operations[1] = {
      ...progress.operations[1]!,
      generation: 2,
      kind: "RELEASE",
      errorCode: "NEW_SAFE_CODE",
    };
    const wrapper = mount(M2IntegrationProgress, {
      props: {
        application: { ...record(), integrationStatus: "RELEASE_UNKNOWN" },
        loadProgress: async () => progress,
      },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("历史意图（第 1 代）");
    expect(wrapper.text()).toContain("当前意图（第 2 代）");
    expect(wrapper.text()).toContain("未识别的诊断码");
    expect(wrapper.text()).not.toContain("NEW_SAFE_CODE");
    expect(wrapper.text()).not.toContain("服务端已确认生效");
  });
  it("ignores an old application's late response after selection changes", async () => {
    let resolve!: (progress: IntegrationProgress) => void;
    const nextId = "00000000-0000-4000-8000-000000000099";
    const loadProgress = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<IntegrationProgress>((done) => {
            resolve = done;
          }),
      )
      .mockResolvedValue({
        ...attention(),
        applicationId: nextId,
        operations: [],
      });
    const wrapper = mount(M2IntegrationProgress, {
      props: { application: record(), loadProgress },
    });
    await wrapper.setProps({ application: { ...record(), id: nextId } });
    await flushPromises();
    resolve(attention());
    await flushPromises();
    expect(wrapper.text()).toContain("尚未产生占用或释放操作");
    expect(wrapper.text()).not.toContain("自动重试已停止");
  });
  it("requeries progress on full workspace reload even when the selected application version is unchanged", async () => {
    const integration = vi
      .fn()
      .mockResolvedValueOnce(parseIntegrationProgress(integrationProgress()))
      .mockResolvedValue(attention());
    const wrapper = mount(M2Workspace, {
      props: {
        gateway: {
          mode: "live",
          load: async () => ({ rooms: [], applications: [record()] }),
          submit: vi.fn(),
          detail: async () => record(),
          integration,
        },
      },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("结果尚未确认");
    await wrapper.get(".page-heading button").trigger("click");
    await flushPromises();
    expect(integration).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("自动重试已停止");
  });
});
