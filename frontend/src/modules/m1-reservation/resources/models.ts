/** B-02 integration proposal. The shared schema and C's role mapping need owner review. */
export type OutletType = "none" | "fixed" | "rail";
export interface Room {
  id: string;
  code: string;
  name: string;
  location: string;
  access_scope: "campus" | "department";
  department_id: string | null;
  open_time: string;
  close_time: string;
  enabled: boolean;
  revision: string;
}
export interface Seat {
  id: string;
  room_id: string;
  code: string;
  outlet_type: OutletType;
  enabled: boolean;
  revision: string;
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface RoomDraft {
  code: string;
  name: string;
  location: string;
}
export interface SeatDraft {
  code: string;
  outlet_type: OutletType;
}
export interface ListQuery {
  q?: string;
  limit?: number;
  offset?: number;
}
export interface SeatQuery extends ListQuery {
  outlet_type?: OutletType;
}
export interface ResourceGateway {
  readonly mode: "prototype" | "unconfigured" | "live";
  listRooms(query: ListQuery, signal?: AbortSignal): Promise<Page<Room>>;
  listSeats(
    roomId: string,
    query: SeatQuery,
    signal?: AbortSignal,
  ): Promise<Page<Seat>>;
  createRoom(draft: RoomDraft): Promise<Room>;
  updateRoom(id: string, draft: RoomDraft, revision: string): Promise<Room>;
  createSeat(roomId: string, draft: SeatDraft): Promise<Seat>;
  updateSeat(id: string, draft: SeatDraft, revision: string): Promise<Seat>;
}
export class ResourceMessage extends Error {
  constructor(
    message: string,
    readonly uncertain = false,
    readonly status?: number,
  ) {
    super(message);
  }
}
