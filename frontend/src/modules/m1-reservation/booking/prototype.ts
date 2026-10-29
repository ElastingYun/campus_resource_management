import { BookingError, matchesIntent, validateSelection } from "./models";
import type {
  BookingGateway,
  BookingIntent,
  ReservationReceipt,
} from "./models";

export function createPrototypeBookingGateway(
  receipts = new Map<string, ReservationReceipt>(),
): BookingGateway {
  const requests = new Map<
    string,
    { fingerprint: string; receipt: ReservationReceipt }
  >();
  const fingerprint = (intent: BookingIntent) =>
    JSON.stringify([
      intent.actorId,
      intent.seat.id,
      Date.parse(intent.startAt),
      Date.parse(intent.endAt),
    ]);
  return {
    mode: "prototype",
    currentActorId: () => "prototype-student",
    async create(intent) {
      validateSelection(intent);
      if (intent.actorId !== "prototype-student")
        throw new BookingError("请使用原演示身份核对。");
      const prior = requests.get(intent.key);
      if (prior) {
        if (prior.fingerprint !== fingerprint(intent))
          throw new BookingError("原请求标识已用于其他演示预约。");
        return { ...prior.receipt };
      }
      if (
        [...receipts.values()].some(
          (item) =>
            item.seatId === intent.seat.id &&
            Date.parse(item.startAt) < Date.parse(intent.endAt) &&
            Date.parse(item.endAt) > Date.parse(intent.startAt),
        )
      )
        throw new BookingError("该演示座位已被预约，请重新选择时段。");
      const receipt: ReservationReceipt = {
        id: String(receipts.size + 1),
        seatId: intent.seat.id,
        roomId: intent.seat.roomId,
        seatCode: intent.seat.code,
        roomCode: intent.seat.roomCode,
        roomName: intent.seat.roomName,
        startAt: intent.startAt,
        endAt: intent.endAt,
        status: "booked",
        checkedInAt: null,
        cancelledAt: null,
        cancelReason: null,
        createdAt: new Date().toISOString(),
      };
      receipts.set(receipt.id, receipt);
      requests.set(intent.key, { fingerprint: fingerprint(intent), receipt });
      return { ...receipt };
    },
    async read(id, intent) {
      const receipt = receipts.get(id);
      if (
        !receipt ||
        !matchesIntent(receipt, intent) ||
        intent.actorId !== "prototype-student"
      )
        throw new BookingError("演示预约不存在。");
      return { ...receipt };
    },
  };
}
