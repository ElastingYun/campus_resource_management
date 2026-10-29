import { reactive, readonly } from "vue";
import { BookingError, matchesIntent, validateSelection } from "./models";
import type {
  BookingGateway,
  BookingIntent,
  BookingSelection,
  ReservationReceipt,
} from "./models";

type Phase =
  | "idle"
  | "confirming"
  | "submitting"
  | "checking"
  | "unknown"
  | "rejected"
  | "resolved";
export function createBookingFlow(
  gateway: BookingGateway,
  makeKey: () => string = () => crypto.randomUUID(),
) {
  const state = reactive<{
    phase: Phase;
    selection: BookingSelection | null;
    receipt: ReservationReceipt | null;
    message: string;
  }>({
    phase: "idle",
    selection: null,
    receipt: null,
    message: "",
  });
  let intent: BookingIntent | undefined,
    knownId: string | undefined,
    selectionActor: string | null = null;
  let controller: AbortController | undefined,
    generation = 0;
  const busy = () => ["submitting", "checking"].includes(state.phase);
  const pending = () => busy() || state.phase === "unknown";
  const actorMatches = () =>
    !!selectionActor && gateway.currentActorId() === selectionActor;
  async function execute(recovery: boolean) {
    if (!intent || busy()) return;
    if (!actorMatches()) {
      state.message = "账号已变化，请切回原账号核对预约。";
      return;
    }
    const current = ++generation;
    controller = new AbortController();
    state.message = "";
    state.phase = knownId ? "checking" : "submitting";
    try {
      if (!knownId) {
        const created = await gateway.create(intent, controller.signal);
        if (current !== generation) return;
        if (!matchesIntent(created, intent))
          throw new BookingError("预约响应不匹配，请核对原请求。", true);
        knownId = created.id;
      }
      if (!actorMatches())
        throw new BookingError("账号已变化，请切回原账号核对预约。", true);
      state.phase = "checking";
      const receipt = await gateway.read(knownId, intent, controller.signal);
      if (current !== generation) return;
      if (
        !actorMatches() ||
        !matchesIntent(receipt, intent) ||
        receipt.id !== knownId
      )
        throw new BookingError(
          "账号或预约响应已变化，请切回原账号核对。",
          true,
        );
      state.receipt = receipt;
      state.phase = "resolved";
    } catch (error) {
      if (current !== generation) return;
      state.phase =
        recovery ||
        knownId ||
        !(error instanceof BookingError) ||
        error.uncertain
          ? "unknown"
          : "rejected";
      state.message =
        error instanceof BookingError
          ? error.message
          : "提交结果尚未确认，请核对原预约请求。";
    }
  }
  return {
    state: readonly(state),
    get active() {
      return state.phase !== "idle";
    },
    get busy() {
      return busy();
    },
    get pending() {
      return pending();
    },
    get actorMatches() {
      return actorMatches();
    },
    get visibleReceipt() {
      return actorMatches() ? state.receipt : null;
    },
    open(selection: BookingSelection) {
      if (state.phase !== "idle" || gateway.mode === "unconfigured")
        return false;
      validateSelection(selection);
      selectionActor = gateway.currentActorId();
      if (!selectionActor) {
        state.message = "请先登录后预约。";
        return false;
      }
      state.selection = {
        ...selection,
        seat: { ...selection.seat, reasons: [...selection.seat.reasons] },
      };
      state.phase = "confirming";
      state.message = "";
      return true;
    },
    async confirm() {
      if (state.phase !== "confirming" || !state.selection) return;
      if (!actorMatches()) {
        state.phase = "rejected";
        state.message = "账号已变化，请重新查询后选择。";
        return;
      }
      try {
        intent = Object.freeze({
          ...state.selection,
          seat: Object.freeze({ ...state.selection.seat, reasons: [] }),
          actorId: selectionActor!,
          key: makeKey(),
        });
      } catch {
        state.phase = "rejected";
        state.message = "无法创建预约请求标识，请重新选择。";
        return;
      }
      await execute(false);
    },
    async recover() {
      if (state.phase === "unknown") await execute(true);
    },
    close() {
      if (pending()) return false;
      state.phase = "idle";
      state.selection = null;
      state.receipt = null;
      state.message = "";
      intent = undefined;
      knownId = undefined;
      selectionActor = null;
      return true;
    },
    dispose() {
      generation++;
      controller?.abort();
      if (busy()) {
        state.phase = "unknown";
        state.message = "请求尚未核对，请使用原账号核对预约记录。";
      }
    },
  };
}
export type BookingFlow = ReturnType<typeof createBookingFlow>;
