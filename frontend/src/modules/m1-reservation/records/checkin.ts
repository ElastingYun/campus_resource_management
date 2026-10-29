import { computed, reactive, shallowReactive } from "vue";
import { isIdentifier } from "../booking/models";
import type { ReservationReceipt } from "../booking/models";
import { RecordsError } from "./models";
import type { RecordsGateway } from "./models";

/** The application owns this object, outside keyed views. Codes are never retained. */
export function createCheckinSession(gateway: RecordsGateway) {
  const mode = gateway.mode;
  const flows = shallowReactive(
    new Map<string, ReturnType<typeof createFlow>>(),
  );
  const actor = () => {
    try {
      const id = gateway.currentActorId();
      return typeof id === "string" && id.trim() ? id : null;
    } catch {
      return null;
    }
  };
  function createFlow(owner: string) {
    const state = reactive({
      phase: "idle" as
        | "idle"
        | "ready"
        | "submitting"
        | "checking"
        | "unknown"
        | "rejected"
        | "resolved",
      receipt: null as ReservationReceipt | null,
      message: "",
    });
    const busy = computed(() =>
      ["submitting", "checking"].includes(state.phase),
    );
    const pending = computed(() => busy.value || state.phase === "unknown");
    let original: ReservationReceipt | null = null;
    const matches = (item: ReservationReceipt) =>
      original &&
      item.id === original.id &&
      item.seatId === original.seatId &&
      item.roomId === original.roomId &&
      Date.parse(item.startAt) === Date.parse(original.startAt) &&
      Date.parse(item.endAt) === Date.parse(original.endAt);
    const requireOwner = () => {
      if (actor() !== owner) throw new RecordsError("请使用原账号核对签到。");
    };
    async function reconcile() {
      if (!original) return;
      state.phase = "checking";
      try {
        requireOwner();
        const latest = await gateway.read(original.id, owner);
        requireOwner();
        if (!matches(latest)) throw new RecordsError("预约响应不匹配。");
        state.receipt = { ...latest };
        if (latest.status === "booked") {
          state.phase = "unknown";
          state.message =
            "仍显示待签到，尚不能确认原提交结果。请继续查询或联系管理员，不要重复提交。";
        } else {
          state.phase = "resolved";
          state.message =
            latest.status === "checked_in"
              ? "已核实签到成功。"
              : "预约已结束或取消，未确认签到成功。";
        }
      } catch {
        state.phase = "unknown";
        state.message = "暂时无法核实签到。请使用原账号查询同一预约。";
      }
    }
    return {
      state,
      get busy() {
        return busy.value;
      },
      get pending() {
        return pending.value;
      },
      get visibleReceipt() {
        return actor() === owner ? state.receipt : null;
      },
      open(item: ReservationReceipt) {
        if (
          state.phase !== "idle" ||
          actor() !== owner ||
          mode === "unconfigured" ||
          item.status !== "booked" ||
          !isIdentifier(item.id)
        )
          return false;
        original = { ...item };
        state.receipt = { ...item };
        state.phase = "ready";
        state.message =
          "请输入现场展示的教室码，服务端将核对身份、教室与签到时段。";
        return true;
      },
      async submit(code: string) {
        if (
          !["ready", "rejected"].includes(state.phase) ||
          !original ||
          actor() !== owner
        )
          return;
        if (!code.trim() || code.trim().length > 32) {
          state.message = "请输入 1–32 个字符的现场码。";
          return;
        }
        state.phase = "submitting";
        state.message = "正在提交签到，请等待核对。";
        try {
          requireOwner();
          const result = await gateway.checkIn(original.id, code.trim(), owner);
          requireOwner();
          if (!matches(result))
            throw new RecordsError("签到响应不匹配。", true);
        } catch (error) {
          if (
            error instanceof RecordsError &&
            !error.uncertain &&
            actor() === owner
          ) {
            state.phase = "rejected";
            state.message = error.message;
            return;
          }
          if (actor() !== owner) {
            state.phase = "unknown";
            state.message = "账号已变化，请用原账号核对签到。";
            return;
          }
        }
        await reconcile();
      },
      async recover() {
        if (state.phase !== "unknown" || actor() !== owner) return;
        await reconcile();
      },
      close() {
        if (pending.value) return false;
        state.phase = "idle";
        state.receipt = null;
        state.message = "";
        original = null;
        return true;
      },
    };
  }
  return {
    get mode() {
      return mode;
    },
    get currentActorId() {
      return actor();
    },
    get current() {
      const id = actor();
      if (!id) return null;
      let flow = flows.get(id);
      if (!flow) {
        flow = createFlow(id);
        flows.set(id, flow);
      }
      return flow;
    },
    get pending() {
      return [...flows.values()].some((flow) => flow.pending);
    },
    clearSettled() {
      for (const [id, flow] of flows)
        if (!flow.pending) {
          flow.close();
          flows.delete(id);
        }
    },
  };
}
export type CheckinSession = ReturnType<typeof createCheckinSession>;

export function protectCheckinSession(
  session: CheckinSession,
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
