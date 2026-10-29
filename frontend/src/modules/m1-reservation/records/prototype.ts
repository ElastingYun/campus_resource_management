import type { ReservationReceipt } from "../booking/models";
import { RecordsError } from "./models";
import type { RecordsGateway } from "./models";

/** Explicit synthetic demonstration. No real check-in window, secret, or identity policy. */
export function createPrototypeRecordsGateway(
  receipts = new Map<string, ReservationReceipt>(),
): RecordsGateway {
  const requireActor = (id: string) => {
    if (id !== "prototype-student")
      throw new RecordsError("请使用原演示身份。");
  };
  const read = async (id: string, actorId: string) => {
    requireActor(actorId);
    const item = receipts.get(id);
    if (!item) throw new RecordsError("演示预约不存在。");
    return { ...item };
  };
  return {
    mode: "prototype",
    currentActorId: () => "prototype-student",
    read,
    async list(query, actorId) {
      requireActor(actorId);
      const items = [...receipts.values()]
        .filter((item) => !query.status || item.status === query.status)
        .reverse();
      return {
        ...query,
        items: items
          .slice(query.offset, query.offset + query.limit)
          .map((item) => ({ ...item })),
      };
    },
    async violations(actorId) {
      requireActor(actorId);
      return [];
    },
    async checkIn(id, code, actorId) {
      const item = await read(id, actorId);
      if (item.status !== "booked")
        throw new RecordsError("演示预约状态已变化，请查询核对。", true);
      if (code !== "DEMO")
        throw new RecordsError("演示码为 DEMO；真实签到请使用教室现场码。");
      const latest: ReservationReceipt = {
        ...item,
        status: "checked_in",
        checkedInAt: new Date().toISOString(),
      };
      receipts.set(id, latest);
      return { ...latest };
    },
  };
}
