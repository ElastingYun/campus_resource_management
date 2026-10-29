import { reactive, shallowReactive } from "vue";
import { ResourceMessage } from "./models";
import type { ResourceGateway, Room, Seat, OutletType } from "./models";

interface ResourceForm {
  kind: "room" | "seat";
  id?: string;
  revision?: string;
  roomId?: string;
}

/** Host owns this with the same trusted session used by the gateway's transport. */
export function createResourceSession(
  gateway: ResourceGateway,
  identity: {
    currentActorId(): string | null;
    canManage(): boolean;
  },
) {
  const mode = gateway.mode;
  const actor = () => {
    try {
      const id = identity.currentActorId();
      return typeof id === "string" && id.trim() ? id : null;
    } catch {
      return null;
    }
  };
  const canManage = () => {
    try {
      return (
        mode !== "unconfigured" && !!actor() && identity.canManage() === true
      );
    } catch {
      return false;
    }
  };
  const flows = shallowReactive(new Map<string, ReturnType<typeof editor>>());
  function editor(owner: string) {
    const state = reactive({
      form: null as ResourceForm | null,
      draft: {
        code: "",
        name: "",
        location: "",
        outlet_type: "none" as OutletType,
      },
      notice: "",
      saveError: "",
      saving: false,
      uncertain: false,
      result: null as Room | Seat | null,
      savedKind: null as "room" | "seat" | null,
      pendingTarget: "",
    });
    const pending = () => state.saving || state.uncertain;
    return {
      state,
      get pending() {
        return pending();
      },
      open(kind: "room" | "seat", item?: Room | Seat, roomId?: string) {
        if (pending() || state.form || actor() !== owner || !canManage())
          return false;
        state.notice = "";
        state.saveError = "";
        state.result = null;
        state.savedKind = null;
        state.form = { kind, id: item?.id, revision: item?.revision, roomId };
        state.draft = {
          code: item?.code ?? "",
          name: item && "name" in item ? item.name : "",
          location: item && "location" in item ? item.location : "",
          outlet_type:
            item && "outlet_type" in item ? item.outlet_type : "none",
        };
        return true;
      },
      closeEditor() {
        if (state.saving || actor() !== owner) return false;
        // Unknown writes retain the original target and block further mutations,
        // even when the editor is hidden so the owner can inspect read-only lists.
        state.form = null;
        return true;
      },
      async save() {
        if (!state.form || pending() || actor() !== owner || !canManage())
          return;
        const form = Object.freeze({ ...state.form }),
          draft = Object.freeze({ ...state.draft });
        const code = draft.code.trim(),
          name = draft.name.trim(),
          location = draft.location.trim();
        if (
          !code ||
          code.length > 32 ||
          (form.kind === "room" &&
            (!name || name.length > 100 || !location || location.length > 200))
        ) {
          state.saveError = "请填写完整资料，并检查字段长度。";
          return;
        }
        state.saving = true;
        state.saveError = "";
        state.pendingTarget = `${form.kind === "room" ? "教室" : "座位"} ${code}${form.id ? `（ID ${form.id}）` : "（新增）"}${form.kind === "seat" ? `，所属教室 ${form.roomId}` : ""}`;
        try {
          let result: Room | Seat;
          if (form.kind === "room") {
            const data = { code, name, location };
            result = form.id
              ? await gateway.updateRoom(form.id, data, form.revision!)
              : await gateway.createRoom(data);
          } else {
            const data = { code, outlet_type: draft.outlet_type };
            result = form.id
              ? await gateway.updateSeat(form.id, data, form.revision!)
              : await gateway.createSeat(form.roomId!, data);
          }
          if (
            (form.id && result.id !== form.id) ||
            result.code !== code ||
            (form.kind === "room" &&
              (!("name" in result) ||
                result.name !== name ||
                result.location !== location)) ||
            (form.kind === "seat" &&
              (!("room_id" in result) ||
                result.room_id !== form.roomId ||
                result.outlet_type !== draft.outlet_type))
          )
            throw new ResourceMessage(
              "保存响应与原资源操作不匹配，请先核对结果。",
              true,
            );
          if (actor() !== owner)
            throw new ResourceMessage(
              "账号已变化，请使用原账号核对原资源操作。",
              true,
            );
          state.result = result;
          state.savedKind = form.kind;
          state.form = null;
          state.pendingTarget = "";
          state.notice =
            mode === "prototype"
              ? `示例${form.kind === "room" ? "教室" : "座位"}已保存，仅在本页演示中有效。`
              : `${form.kind === "room" ? "教室" : "座位"}已保存。`;
        } catch (error) {
          state.saveError =
            error instanceof ResourceMessage
              ? error.message
              : "保存结果尚未确认，请核对原资源操作。";
          state.uncertain =
            !(error instanceof ResourceMessage) || error.uncertain;
          if (!state.uncertain) state.pendingTarget = "";
        } finally {
          state.saving = false;
        }
      },
    };
  }
  async function read<T>(operation: () => Promise<T>): Promise<T> {
    const owner = actor();
    if (!owner || mode === "unconfigured")
      throw new ResourceMessage("资源身份与会话生命周期尚未接入。");
    const result = await operation();
    if (actor() !== owner)
      throw new ResourceMessage("账号已变化，请重新查询资源。");
    return result;
  }
  return {
    get gateway() {
      return gateway;
    },
    get mode() {
      return mode;
    },
    get currentActorId() {
      return actor();
    },
    get canManage() {
      return canManage();
    },
    get current() {
      const id = actor();
      if (!id) return null;
      let flow = flows.get(id);
      if (!flow) {
        flow = editor(id);
        flows.set(id, flow);
      }
      return flow;
    },
    get pending() {
      return [...flows.values()].some((flow) => flow.pending);
    },
    listRooms: (
      query: Parameters<ResourceGateway["listRooms"]>[0],
      signal?: AbortSignal,
    ) => read(() => gateway.listRooms(query, signal)),
    listSeats: (
      id: string,
      query: Parameters<ResourceGateway["listSeats"]>[1],
      signal?: AbortSignal,
    ) => read(() => gateway.listSeats(id, query, signal)),
    clearSettled() {
      for (const [id, flow] of flows)
        if (!flow.pending && !flow.state.form) flows.delete(id);
    },
  };
}
export type ResourceSession = ReturnType<typeof createResourceSession>;

export function protectResourceSession(
  session: ResourceSession,
  target: Window = window,
): () => void {
  const listener = (event: BeforeUnloadEvent) => {
    if (session.pending) {
      event.preventDefault();
      event.returnValue = "";
    }
  };
  target.addEventListener("beforeunload", listener);
  return () => target.removeEventListener("beforeunload", listener);
}
