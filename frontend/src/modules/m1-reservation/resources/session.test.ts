import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { createPrototypeResourceGateway } from "./prototype";
import { createResourceSession, protectResourceSession } from "./session";
import { ResourceMessage } from "./models";
import type { Room } from "./models";
function setup() {
  const actor = ref<string | null>("A"),
    allowed = ref(true),
    gateway = createPrototypeResourceGateway();
  const session = createResourceSession(gateway, {
    currentActorId: () => actor.value,
    canManage: () => allowed.value,
  });
  const flow = session.current!;
  flow.open("room");
  Object.assign(flow.state.draft, {
    code: "NEW",
    name: "新示例",
    location: "示例区",
  });
  return { actor, allowed, gateway, session, flow };
}
describe("B resource editing survives application view changes", () => {
  it("keeps a mismatched acknowledgement unknown instead of showing success", async () => {
    const { gateway, flow } = setup();
    const result = await gateway.createRoom({
      code: "OTHER",
      name: "其他资源",
      location: "其他区域",
    });
    gateway.createRoom = vi.fn().mockResolvedValue(result);
    await flow.save();
    expect(flow.state.uncertain).toBe(true);
    expect(flow.state.notice).toBe("");
    expect(flow.state.pendingTarget).toContain("NEW");
  });
  it("keeps an unknown target after hiding the editor and blocks new writes", async () => {
    const { gateway, flow, session } = setup();
    gateway.createRoom = vi
      .fn()
      .mockRejectedValue(new ResourceMessage("unknown", true));
    await flow.save();
    expect(flow.closeEditor()).toBe(true);
    expect(flow.state.form).toBeNull();
    expect(flow.state.pendingTarget).toContain("NEW");
    session.clearSettled();
    expect(session.current).toBe(flow);
    expect(flow.open("room")).toBe(false);
    await flow.save();
    expect(gateway.createRoom).toHaveBeenCalledTimes(1);
    expect(session.pending).toBe(true);
  });
  it("uses one frozen payload while in flight and cannot close or double-submit", async () => {
    const { gateway, flow } = setup();
    let resolve!: (value: Room) => void;
    const create = gateway.createRoom;
    gateway.createRoom = vi.fn().mockReturnValue(
      new Promise<Room>((done) => {
        resolve = done;
      }),
    );
    const pending = flow.save();
    flow.state.draft.code = "CHANGED";
    await flow.save();
    expect(flow.closeEditor()).toBe(false);
    expect(gateway.createRoom).toHaveBeenCalledTimes(1);
    expect(vi.mocked(gateway.createRoom).mock.calls[0]?.[0].code).toBe("NEW");
    resolve(await create({ code: "NEW", name: "新示例", location: "示例区" }));
    await pending;
    expect(flow.state.notice).toContain("已保存");
    expect(flow.pending).toBe(false);
  });
  it("isolates accounts and prevents a stale flow reference from writing", async () => {
    const { actor, gateway, flow, session } = setup();
    const create = vi.spyOn(gateway, "createRoom");
    actor.value = "B";
    expect(session.current).not.toBe(flow);
    await flow.save();
    expect(create).not.toHaveBeenCalled();
    expect(flow.closeEditor()).toBe(false);
    actor.value = "A";
    expect(session.current).toBe(flow);
    await flow.save();
    expect(create).toHaveBeenCalledTimes(1);
  });
  it("retains a write as unknown when its owner changes before the response", async () => {
    const { actor, gateway, flow, session } = setup();
    const original = gateway.createRoom;
    let resolve!: (value: Room) => void;
    gateway.createRoom = vi.fn().mockReturnValue(
      new Promise<Room>((done) => {
        resolve = done;
      }),
    );
    const pending = flow.save();
    actor.value = "B";
    resolve(
      await original({ code: "NEW", name: "新示例", location: "示例区" }),
    );
    await pending;
    expect(flow.state.uncertain).toBe(true);
    expect(session.current!.state.form).toBeNull();
    actor.value = "A";
    expect(session.current).toBe(flow);
    expect(flow.state.pendingTarget).toContain("NEW");
  });
  it("allows correcting definite rejections but treats unclassified failures as unknown", async () => {
    const { gateway, flow } = setup();
    gateway.createRoom = vi
      .fn()
      .mockRejectedValueOnce(new ResourceMessage("duplicate", false))
      .mockRejectedValueOnce(new Error("private-connection"));
    await flow.save();
    expect(flow.state.uncertain).toBe(false);
    expect(flow.state.saveError).toBe("duplicate");
    await flow.save();
    expect(flow.state.uncertain).toBe(true);
    expect(flow.state.saveError).not.toContain("private-connection");
  });
  it("rechecks permission before writing and preserves correctable input", async () => {
    const { allowed, gateway, flow } = setup();
    const create = vi.spyOn(gateway, "createRoom");
    allowed.value = false;
    await flow.save();
    expect(create).not.toHaveBeenCalled();
    expect(flow.state.draft.code).toBe("NEW");
    allowed.value = true;
    await flow.save();
    expect(create).toHaveBeenCalledTimes(1);
  });
  it("rejects a read completed for a different account", async () => {
    const { actor, gateway, session } = setup(),
      original = gateway.listRooms;
    let resolve!: (value: Awaited<ReturnType<typeof original>>) => void;
    gateway.listRooms = vi.fn().mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const pending = session.listRooms({});
    actor.value = "B";
    resolve(await original({}));
    await expect(pending).rejects.toThrow("账号已变化");
  });
  it("protects page unload with no view mounted and removes its listener", async () => {
    const { gateway, flow, session } = setup();
    gateway.createRoom = vi
      .fn()
      .mockRejectedValue(new ResourceMessage("unknown", true));
    await flow.save();
    const dispose = protectResourceSession(session),
      event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    dispose();
    const after = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });
});
