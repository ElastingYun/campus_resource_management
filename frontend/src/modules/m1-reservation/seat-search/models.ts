export type Outlet = "none" | "fixed" | "rail";
export const outletLabels: Record<Outlet, string> = {
  none: "无插座",
  fixed: "固定插座",
  rail: "轨道插座",
};
export const reasonLabels: Record<string, string> = {
  room_disabled: "教室已停用",
  seat_disabled: "座位已停用",
  department_restricted: "院系准入受限",
  outside_opening_hours: "不在开放时间内",
  reserved: "已有座位预约",
  m2_approval: "整教室审批占用",
  m3_repair: "教室维修中",
};
export function reasonLabel(code: string): string {
  return Object.hasOwn(reasonLabels, code)
    ? reasonLabels[code]!
    : "未知限制原因，请重新查询或联系管理员";
}
export interface SearchSettings {
  maxHours: number;
  bookingHorizonDays: number;
}
export interface SeatQuery {
  date: string;
  hour: number;
  hours: number;
  outlet: "" | Outlet;
  roomId: string;
  onlyAvailable: boolean;
}
export interface SearchSeat {
  id: string;
  code: string;
  roomId: string;
  roomCode: string;
  roomName: string;
  outlet: Outlet;
  status: "available" | "unavailable" | "unknown";
  reasons: string[];
}
export interface SearchResult {
  startAt: string;
  endAt: string;
  hours: number;
  seats: SearchSeat[];
}
export interface SeatSearchGateway {
  mode: "prototype" | "unconfigured" | "live";
  businessTimeZone: string | null;
  loadSettings(signal?: AbortSignal): Promise<SearchSettings>;
  search(query: SeatQuery, signal?: AbortSignal): Promise<SearchResult>;
}
export class SearchError extends Error {}
export function localStart(query: SeatQuery): string {
  return `${query.date}T${String(query.hour).padStart(2, "0")}:00:00`;
}
export function validQuery(
  query: SeatQuery,
  settings: SearchSettings,
): boolean {
  const day = new Date(`${query.date}T00:00:00Z`);
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(query.date) &&
    Number.isFinite(day.getTime()) &&
    day.toISOString().slice(0, 10) === query.date &&
    Number.isInteger(query.hour) &&
    query.hour >= 0 &&
    query.hour <= 23 &&
    Number.isSafeInteger(query.hours) &&
    query.hours >= 1 &&
    query.hours <= settings.maxHours &&
    ["", "none", "fixed", "rail"].includes(query.outlet) &&
    (query.roomId === "" || /^[1-9]\d*$/.test(query.roomId))
  );
}
export function businessDate(now: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (name: string) =>
    parts.find((item) => item.type === name)!.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}
