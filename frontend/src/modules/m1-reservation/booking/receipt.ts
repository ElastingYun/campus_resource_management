import { isIdentifier, isInstant, reservationLabels } from "./models";
import type { ReservationReceipt } from "./models";

export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("invalid payload");
  return value as Record<string, unknown>;
}
export function identifier(value: unknown): string {
  if (typeof value === "number" && Number.isSafeInteger(value) && value > 0)
    return String(value);
  if (isIdentifier(value)) return value;
  throw new Error("invalid identifier");
}
export function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim())
    throw new Error("invalid text");
  return value;
}
export function instant(value: unknown): string {
  if (!isInstant(value)) throw new Error("invalid timestamp");
  return value;
}
function nullableTime(value: unknown): string | null {
  return value === null ? null : instant(value);
}
export function parseReceipt(value: unknown): ReservationReceipt {
  const data = object(value);
  const status = text(data.status);
  if (!Object.hasOwn(reservationLabels, status))
    throw new Error("invalid status");
  const receipt: ReservationReceipt = {
    id: identifier(data.id),
    seatId: identifier(data.seat_id),
    roomId: identifier(data.room_id),
    seatCode: text(data.seat_code),
    roomCode: text(data.room_code),
    roomName: text(data.room_name),
    startAt: instant(data.start_at),
    endAt: instant(data.end_at),
    status: status as ReservationReceipt["status"],
    checkedInAt: nullableTime(data.checked_in_at),
    cancelledAt: nullableTime(data.cancelled_at),
    cancelReason: data.cancel_reason === null ? null : text(data.cancel_reason),
    createdAt: instant(data.created_at),
  };
  if (
    Date.parse(receipt.endAt) <= Date.parse(receipt.startAt) ||
    (receipt.status === "booked" &&
      (receipt.checkedInAt !== null || receipt.cancelledAt !== null)) ||
    (receipt.status === "checked_in" && receipt.checkedInAt === null) ||
    (["cancelled", "no_show"].includes(receipt.status) &&
      receipt.cancelledAt === null)
  )
    throw new Error("mismatched receipt");
  return receipt;
}
