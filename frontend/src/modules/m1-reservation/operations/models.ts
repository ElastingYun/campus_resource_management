import { isInstant } from "../booking/models";
export interface UsageRoom {
  id: string;
  code: string;
  seats: number;
  reservations: {
    booked: number;
    checked_in: number;
    cancelled: number;
    no_show: number;
  };
  checkedInHours: number;
  capacityHours: number;
  utilization: number;
}
export interface UsageReport {
  date: string;
  rooms: UsageRoom[];
}
export interface SeatEvent {
  occurredAt: string;
  sourceType: string;
  sourceId: string;
  action: string;
  roomId: string;
  seatId: string | null;
  startAt: string;
  endAt: string | null;
}
export interface EventQuery {
  roomId: string;
  seatId: string;
  limit: number;
}
export interface RoomCode {
  roomId: string;
  date: string;
  code: string;
  validUntil: string;
}
export interface OperationsGateway {
  mode: "prototype" | "live" | "unconfigured";
  currentActorId(): string | null;
  capabilities(): { operations: boolean; roomCode: boolean };
  usage(
    date: string,
    actorId: string,
    signal?: AbortSignal,
  ): Promise<UsageReport>;
  events(
    query: EventQuery,
    actorId: string,
    signal?: AbortSignal,
  ): Promise<SeatEvent[]>;
  roomCode(
    roomId: string,
    actorId: string,
    signal?: AbortSignal,
  ): Promise<RoomCode>;
}
export class OperationsError extends Error {}
export function isDate(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    isInstant(`${value}T00:00:00Z`)
  );
}
