import { shallowReactive } from "vue";
import { createBookingFlow } from "./flow";
import type { BookingFlow } from "./flow";
import { BookingError } from "./models";
import type { BookingGateway } from "./models";

/** Own at application lifetime, outside route components. No token or disk storage. */
export function createBookingSession(
  gateway: BookingGateway,
  makeKey?: () => string,
) {
  const mode = gateway.mode;
  const flows = shallowReactive(new Map<string, BookingFlow>());
  function actorId(): string | null {
    try {
      const value = gateway.currentActorId();
      return typeof value === "string" && value.trim() ? value : null;
    } catch {
      return null;
    }
  }
  function forActor(owner: string): BookingFlow {
    let flow = flows.get(owner);
    if (!flow) {
      const requireOwner = () => {
        if (actorId() !== owner)
          throw new BookingError("请使用原账号核对预约。");
      };
      flow = createBookingFlow(
        {
          mode,
          currentActorId: () => (actorId() === owner ? owner : null),
          async create(intent, signal) {
            requireOwner();
            return gateway.create(intent, signal);
          },
          async read(id, intent, signal) {
            requireOwner();
            return gateway.read(id, intent, signal);
          },
        },
        makeKey,
      );
      flows.set(owner, flow);
    }
    return flow;
  }
  return {
    get mode() {
      return mode;
    },
    get currentActorId() {
      return actorId();
    },
    get current(): BookingFlow | null {
      const id = actorId();
      return id ? forActor(id) : null;
    },
    get pending() {
      return [...flows.values()].some((flow) => flow.pending);
    },
    /** Explicit host interruption preserves unknown requests rather than clearing keys. */
    interruptPending() {
      for (const flow of flows.values()) if (flow.busy) flow.dispose();
    },
    /** Safe memory cleanup; outstanding requests are never discarded. */
    clearSettled() {
      for (const [id, flow] of flows)
        if (!flow.pending) {
          flow.close();
          flows.delete(id);
        }
    },
  };
}
export type BookingSession = ReturnType<typeof createBookingSession>;

/** Install once in the application shell, so protection remains while the view is absent. */
export function protectBookingSession(
  session: BookingSession,
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
