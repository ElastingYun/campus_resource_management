import { isIdentifier, reservationLabels } from "../booking/models";
import { identifier, instant, object, text } from "../booking/receipt";
import { isDate, OperationsError } from "./models";
import type { OperationsGateway, UsageRoom } from "./models";
import { businessDate } from "../seat-search/models";

export const OPS_PERMISSION = "m1:ops:view",
  CODE_PERMISSION = "m1:checkin_code:view";
function nonnegative(value: unknown, integer = false): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < 0 ||
    (integer && !Number.isSafeInteger(value))
  )
    throw new Error("invalid metric");
  return value;
}
export function createHttpOperationsGateway(options: {
  getSession: () => {
    subjectId: string;
    accessToken: string;
    permissions: readonly string[];
  } | null;
  request?: typeof fetch;
  timeoutMs?: number;
  businessTimeZone?: string;
}): OperationsGateway {
  const { getSession, request = fetch, timeoutMs = 10000 } = options;
  if (!Number.isFinite(timeoutMs) || timeoutMs < 1)
    throw new OperationsError("运营接入配置无效。");
  let codeTimeZone: string | undefined;
  try {
    if (options.businessTimeZone) {
      new Intl.DateTimeFormat("zh-CN", { timeZone: options.businessTimeZone });
      codeTimeZone = options.businessTimeZone;
    }
  } catch {
    /* Code display stays closed. */
  }
  function session() {
    try {
      const value = getSession();
      return value &&
        typeof value.subjectId === "string" &&
        value.subjectId.trim() &&
        typeof value.accessToken === "string" &&
        /^[\x21-\x7e]+$/.test(value.accessToken) &&
        Array.isArray(value.permissions) &&
        value.permissions.every((item) => typeof item === "string")
        ? value
        : null;
    } catch {
      return null;
    }
  }
  async function send<T>(
    url: string,
    actorId: string,
    permission: string,
    parse: (value: unknown) => T,
    signal?: AbortSignal,
  ): Promise<T> {
    const current = session();
    if (!current || current.subjectId !== actorId)
      throw new OperationsError("请先登录或使用原账号查询。");
    if (!current.permissions.includes(permission))
      throw new OperationsError("当前账号没有此查看权限。");
    const controller = new AbortController(),
      abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    const timer = setTimeout(abort, timeoutMs);
    try {
      if (controller.signal.aborted) throw new Error("aborted");
      const response = await request(url, {
        method: "GET",
        credentials: "same-origin",
        mode: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${current.accessToken}`,
        },
        signal: controller.signal,
      });
      if (!response.ok) {
        const messages: Record<number, string> = {
          401: "登录已失效，请重新登录。",
          403: "当前账号没有此查看权限。",
          404: "教室或记录不存在，或不可访问。",
          422: "查询参数未被服务接受。",
        };
        throw new OperationsError(
          messages[response.status] ?? "运营服务暂不可用，请稍后查询。",
        );
      }
      if (
        response.status !== 200 ||
        !response.headers.get("Content-Type")?.includes("application/json")
      )
        throw new Error("invalid response");
      const result = parse(await response.json()),
        latest = session();
      if (
        controller.signal.aborted ||
        latest?.subjectId !== actorId ||
        !latest.permissions.includes(permission)
      )
        throw new OperationsError("账号或权限已变化，请重新查询。");
      return result;
    } catch (error) {
      if (error instanceof OperationsError) throw error;
      throw new OperationsError("响应未通过校验或查询已中断，请稍后重新查询。");
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  return {
    mode: "live",
    currentActorId: () => session()?.subjectId ?? null,
    capabilities: () => ({
      operations: session()?.permissions.includes(OPS_PERMISSION) ?? false,
      roomCode:
        !!codeTimeZone &&
        (session()?.permissions.includes(CODE_PERMISSION) ?? false),
    }),
    async usage(date, actorId, signal) {
      if (!isDate(date)) throw new OperationsError("请选择有效日期。");
      return send(
        `/api/v1/m1/ops/usage?${new URLSearchParams({ date })}`,
        actorId,
        OPS_PERMISSION,
        (value) => {
          const data = object(value);
          if (data.date !== date || !Array.isArray(data.rooms))
            throw new Error("wrong report");
          const rooms = data.rooms.map((item): UsageRoom => {
            const row = object(item),
              counts = object(row.reservations);
            if (
              Object.keys(counts).length !== 4 ||
              Object.keys(counts).some(
                (key) => !Object.hasOwn(reservationLabels, key),
              )
            )
              throw new Error("unknown reservation metrics");
            for (const key of Object.keys(reservationLabels))
              nonnegative(counts[key], true);
            return {
              id: identifier(row.room_id),
              code: text(row.room_code),
              seats: nonnegative(row.seat_count, true),
              reservations: {
                booked: counts.booked as number,
                checked_in: counts.checked_in as number,
                cancelled: counts.cancelled as number,
                no_show: counts.no_show as number,
              },
              checkedInHours: nonnegative(row.checked_in_seat_hours),
              capacityHours: nonnegative(row.capacity_seat_hours),
              utilization: nonnegative(row.utilization),
            };
          });
          if (new Set(rooms.map((room) => room.id)).size !== rooms.length)
            throw new Error("duplicate rooms");
          return { date, rooms };
        },
        signal,
      );
    },
    async events(query, actorId, signal) {
      if (
        !isIdentifier(query.roomId) ||
        (query.seatId && !isIdentifier(query.seatId)) ||
        !Number.isSafeInteger(query.limit) ||
        query.limit < 1 ||
        query.limit > 500
      )
        throw new OperationsError("请填写有效教室、座位编号和查询上限。");
      const params = new URLSearchParams({
        room_id: query.roomId,
        limit: String(query.limit),
      });
      if (query.seatId) params.set("seat_id", query.seatId);
      return send(
        `/api/v1/m1/ops/seat-events?${params}`,
        actorId,
        OPS_PERMISSION,
        (value) => {
          if (!Array.isArray(value) || value.length > query.limit)
            throw new Error("invalid events");
          return value.map((item) => {
            const row = object(item),
              roomId = identifier(row.room_id),
              seatId = row.seat_id === null ? null : identifier(row.seat_id);
            const startAt = instant(row.start_at),
              endAt = row.end_at === null ? null : instant(row.end_at);
            if (
              roomId !== query.roomId ||
              (query.seatId && seatId !== null && seatId !== query.seatId) ||
              (endAt && Date.parse(endAt) <= Date.parse(startAt))
            )
              throw new Error("wrong event scope");
            // actor_id is intentionally never copied into client state.
            return {
              roomId,
              seatId,
              startAt,
              endAt,
              occurredAt: instant(row.occurred_at),
              sourceType: text(row.source_type),
              sourceId: text(row.source_id),
              action: text(row.action),
            };
          });
        },
        signal,
      );
    },
    async roomCode(roomId, actorId, signal) {
      if (!codeTimeZone) throw new OperationsError("教室码业务时区尚未配置。");
      if (!isIdentifier(roomId))
        throw new OperationsError("请填写有效教室编号。");
      return send(
        `/api/v1/m1/rooms/${roomId}/checkin-code`,
        actorId,
        CODE_PERMISSION,
        (value) => {
          const data = object(value),
            id = identifier(data.room_id),
            validUntil = instant(data.valid_until);
          if (
            id !== roomId ||
            !isDate(data.date) ||
            typeof data.code !== "string" ||
            !/^\d{6}$/.test(data.code) ||
            Date.parse(validUntil) <= Date.now() ||
            businessDate(new Date(), codeTimeZone!) !== data.date ||
            businessDate(
              new Date(Date.parse(validUntil) - 1),
              codeTimeZone!,
            ) !== data.date
          )
            throw new Error("invalid or expired code");
          return { roomId: id, date: data.date, code: data.code, validUntil };
        },
        signal,
      );
    },
  };
}
export function createUnconfiguredOperationsGateway(): OperationsGateway {
  const unavailable = async (): Promise<never> => {
    throw new OperationsError("运营接口尚未接入。");
  };
  return {
    mode: "unconfigured",
    currentActorId: () => null,
    capabilities: () => ({ operations: false, roomCode: false }),
    usage: unavailable,
    events: unavailable,
    roomCode: unavailable,
  };
}
