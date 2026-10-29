import type { ReservationReceipt } from "../booking/models";

export type ReservationStatus = ReservationReceipt["status"];
export interface RecordQuery {
  status: ReservationStatus | "";
  limit: number;
  offset: number;
}
export interface ReservationPage {
  items: ReservationReceipt[];
  limit: number;
  offset: number;
}
export interface Violation {
  id: string;
  reservationId: string;
  reason: string;
  occurredAt: string;
}
export interface RecordsGateway {
  mode: "prototype" | "live" | "unconfigured";
  currentActorId(): string | null;
  list(
    query: RecordQuery,
    actorId: string,
    signal?: AbortSignal,
  ): Promise<ReservationPage>;
  read(
    id: string,
    actorId: string,
    signal?: AbortSignal,
  ): Promise<ReservationReceipt>;
  violations(actorId: string, signal?: AbortSignal): Promise<Violation[]>;
  checkIn(
    id: string,
    code: string,
    actorId: string,
    signal?: AbortSignal,
  ): Promise<ReservationReceipt>;
}
export class RecordsError extends Error {
  constructor(
    message: string,
    readonly uncertain = false,
  ) {
    super(message);
  }
}
