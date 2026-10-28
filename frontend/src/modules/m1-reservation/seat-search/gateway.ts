import { localStart, reasonLabels, SearchError, validQuery } from "./models";
import type {
  Outlet,
  SearchResult,
  SearchSeat,
  SearchSettings,
  SeatQuery,
  SeatSearchGateway,
} from "./models";

const malformed = () =>
  new SearchError("查询服务返回的数据不完整，请稍后重试或联系管理员。");
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw malformed();
  return value as Record<string, unknown>;
}
function positive(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1)
    throw malformed();
  return value;
}
function identifier(value: unknown): string {
  if (typeof value === "number") return String(positive(value));
  if (typeof value === "string" && /^[1-9]\d*$/.test(value)) return value;
  throw malformed();
}
function textField(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) throw malformed();
  return value;
}
function instant(value: unknown): string {
  const text = textField(value);
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(
      text,
    ) ||
    !Number.isFinite(Date.parse(text)) ||
    Number(text.slice(11, 13)) > 23 ||
    Number(text.slice(14, 16)) > 59 ||
    Number(text.slice(17, 19)) > 59
  )
    throw malformed();
  // Date.parse normalizes impossible days; reject those too.
  const date = text.slice(0, 10);
  if (new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) !== date)
    throw malformed();
  return text;
}
function localTime(value: string, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const part = (name: string) =>
    parts.find((item) => item.type === name)!.value;
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}:${part("second")}`;
}
function parseResult(
  value: unknown,
  query: SeatQuery,
  timeZone: string,
): SearchResult {
  const data = object(value);
  const startAt = instant(data.start_at),
    endAt = instant(data.end_at);
  const hours = positive(data.hours);
  if (
    hours !== query.hours ||
    Date.parse(endAt) - Date.parse(startAt) !== hours * 3600000 ||
    Date.parse(startAt) % 1000 !== 0 ||
    localTime(startAt, timeZone) !== localStart(query) ||
    !Array.isArray(data.seats)
  )
    throw malformed();
  const seen = new Set<string>(),
    rooms = new Map<string, string>();
  const seats: SearchSeat[] = data.seats.map((value: unknown) => {
    const seat = object(value);
    const id = identifier(seat.seat_id),
      roomId = identifier(seat.room_id);
    const roomCode = textField(seat.room_code),
      roomName = textField(seat.room_name);
    if (
      seen.has(id) ||
      (rooms.has(roomId) &&
        rooms.get(roomId) !== JSON.stringify([roomCode, roomName]))
    )
      throw malformed();
    seen.add(id);
    rooms.set(roomId, JSON.stringify([roomCode, roomName]));
    if (
      typeof seat.outlet_type !== "string" ||
      !["none", "fixed", "rail"].includes(seat.outlet_type) ||
      typeof seat.available !== "boolean" ||
      !Array.isArray(seat.reasons) ||
      (query.roomId && query.roomId !== roomId) ||
      (query.outlet && query.outlet !== seat.outlet_type)
    )
      throw malformed();
    const reasons = seat.reasons.map((reason: unknown) =>
      textField(object(reason).code),
    );
    const known = reasons.every((code) => Object.hasOwn(reasonLabels, code));
    const consistent = seat.available
      ? reasons.length === 0
      : reasons.length > 0;
    const status =
      known && consistent
        ? seat.available
          ? "available"
          : "unavailable"
        : "unknown";
    return {
      id,
      code: textField(seat.seat_code),
      roomId,
      roomCode,
      roomName,
      outlet: seat.outlet_type as Outlet,
      status,
      reasons: [...new Set(reasons)],
    };
  });
  return { startAt, endAt, hours, seats };
}
function httpMessage(status: number): string {
  if (status === 401) return "请先登录后查询座位。";
  if (status === 403) return "当前账号没有查询权限，请联系管理员。";
  if (status === 422)
    return "查询条件未被服务接受，请检查日期、整点、时长及可预约日期范围。";
  return "座位查询服务暂时不可用，请稍后重试。";
}
export function createHttpSeatSearchGateway(options: {
  businessTimeZone: string;
  getAccessToken: () => string | null;
  request?: typeof fetch;
  timeoutMs?: number;
}): SeatSearchGateway {
  const {
    businessTimeZone,
    getAccessToken,
    request = fetch,
    timeoutMs = 10000,
  } = options;
  // No browser-timezone or development-identity defaults in real mode.
  new Intl.DateTimeFormat("en", { timeZone: businessTimeZone }).format();
  if (!businessTimeZone.trim() || !Number.isFinite(timeoutMs) || timeoutMs < 1)
    throw new SearchError("查询接入配置无效。");
  let settings: SearchSettings | undefined;
  async function get(url: string, signal?: AbortSignal): Promise<unknown> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    const timer = setTimeout(abort, timeoutMs);
    try {
      const token = getAccessToken();
      if (!token) throw new SearchError("请先登录后查询座位。");
      if (!/^[\x21-\x7e]+$/.test(token))
        throw new SearchError("会话信息无效，请重新登录。");
      const response = await request(url, {
        method: "GET",
        credentials: "same-origin",
        mode: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${token}`,
        },
        signal: controller.signal,
      });
      if (!response.ok) throw new SearchError(httpMessage(response.status));
      if (!response.headers.get("Content-Type")?.includes("application/json"))
        throw malformed();
      return await response.json();
    } catch (error) {
      if (error instanceof SearchError) throw error;
      throw new SearchError(
        controller.signal.aborted
          ? "查询已取消或超时，请重新查询。"
          : "无法连接查询服务，请检查网络后重试。",
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  return {
    mode: "live",
    businessTimeZone,
    async loadSettings(signal) {
      settings = undefined;
      const data = object(await get("/api/v1/m1/settings", signal));
      settings = {
        maxHours: positive(data.max_hours),
        bookingHorizonDays: positive(data.booking_horizon_days),
      };
      return { ...settings };
    },
    async search(query, signal) {
      if (!settings || !validQuery(query, settings))
        throw new SearchError(
          "请先读取预约规则，并填写有效的日期、整点和时长。",
        );
      const params = new URLSearchParams({
        start_at: localStart(query),
        hours: String(query.hours),
        only_available: String(query.onlyAvailable),
      });
      if (query.roomId) params.set("room_id", query.roomId);
      if (query.outlet) params.set("outlet_type", query.outlet);
      return parseResult(
        await get(`/api/v1/m1/seats/availability?${params}`, signal),
        query,
        businessTimeZone,
      );
    },
  };
}
export function createUnconfiguredSeatSearchGateway(): SeatSearchGateway {
  const unavailable = async (): Promise<never> => {
    throw new SearchError("座位查询尚未接入，请等待服务配置完成。");
  };
  return {
    mode: "unconfigured",
    businessTimeZone: null,
    loadSettings: unavailable,
    search: unavailable,
  };
}
