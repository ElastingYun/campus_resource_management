import type { SearchResult, SearchSeat } from "../seat-search/models";

export interface BookingSelection {
  seat: SearchSeat;
  startAt: string;
  endAt: string;
  hours: number;
}
export interface BookingIntent extends BookingSelection {
  actorId: string;
  key: string;
}
export const reservationLabels = {
  booked: "待签到",
  checked_in: "已签到",
  cancelled: "已取消",
  no_show: "未签到已取消",
};
export interface ReservationReceipt {
  id: string;
  seatId: string;
  roomId: string;
  seatCode: string;
  roomCode: string;
  roomName: string;
  startAt: string;
  endAt: string;
  status: keyof typeof reservationLabels;
  checkedInAt: string | null;
  cancelledAt: string | null;
  cancelReason: string | null;
  createdAt: string;
}
export interface BookingGateway {
  mode: "prototype" | "unconfigured" | "live";
  currentActorId(): string | null;
  create(
    intent: BookingIntent,
    signal?: AbortSignal,
  ): Promise<ReservationReceipt>;
  read(
    id: string,
    intent: BookingIntent,
    signal?: AbortSignal,
  ): Promise<ReservationReceipt>;
}
export class BookingError extends Error {
  constructor(
    message: string,
    readonly uncertain = false,
  ) {
    super(message);
  }
}
export function isIdentifier(value: unknown): value is string {
  return typeof value === "string" && /^[1-9]\d*$/.test(value);
}
export function isInstant(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(
      value,
    ) ||
    !Number.isFinite(Date.parse(value)) ||
    Number(value.slice(11, 13)) > 23 ||
    Number(value.slice(14, 16)) > 59 ||
    Number(value.slice(17, 19)) > 59
  )
    return false;
  return (
    new Date(`${value.slice(0, 10)}T00:00:00Z`).toISOString().slice(0, 10) ===
    value.slice(0, 10)
  );
}
export function validateSelection(selection: BookingSelection): void {
  if (
    selection.seat.status !== "available" ||
    selection.seat.reasons.length !== 0 ||
    !isIdentifier(selection.seat.id) ||
    !isIdentifier(selection.seat.roomId) ||
    !isInstant(selection.startAt) ||
    !isInstant(selection.endAt) ||
    !Number.isSafeInteger(selection.hours) ||
    selection.hours < 1 ||
    Date.parse(selection.endAt) - Date.parse(selection.startAt) !==
      selection.hours * 3600000 ||
    Date.parse(selection.startAt) % 1000 !== 0
  ) {
    throw new BookingError("座位或时段尚未确认，请重新查询后选择。");
  }
}
export function selectBooking(
  seat: SearchSeat,
  result: SearchResult,
): BookingSelection {
  const selection = {
    seat: { ...seat, reasons: [...seat.reasons] },
    startAt: result.startAt,
    endAt: result.endAt,
    hours: result.hours,
  };
  validateSelection(selection);
  return selection;
}
export function matchesIntent(
  receipt: ReservationReceipt,
  intent: BookingIntent,
): boolean {
  return (
    receipt.seatId === intent.seat.id &&
    receipt.roomId === intent.seat.roomId &&
    Date.parse(receipt.startAt) === Date.parse(intent.startAt) &&
    Date.parse(receipt.endAt) === Date.parse(intent.endAt)
  );
}
