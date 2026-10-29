import {
  BookingError,
  isIdentifier,
  isInstant,
  matchesIntent,
  reservationLabels,
  validateSelection,
} from "./models";
import type {
  BookingGateway,
  BookingIntent,
  ReservationReceipt,
} from "./models";

const rejected: Record<string, [number, string]> = {
  seat_conflict: [409, "该座位已被预约，请重新查询。"],
  user_overlap: [409, "你在该时段已有有效预约，请先查看已有预约。"],
  room_disabled: [409, "教室已停用，请重新查询。"],
  seat_disabled: [409, "座位已停用，请重新查询。"],
  seat_restricted: [409, "该时段教室已被占用或正在维修，请重新查询。"],
  department_restricted: [403, "当前账号不符合该教室的准入条件。"],
  outside_opening_hours: [422, "所选时段不在教室开放时间内。"],
  start_not_in_future: [422, "所选时段已经开始，请重新选择。"],
  beyond_booking_horizon: [422, "所选日期超出可预约范围。"],
  invalid_duration: [422, "当前服务不接受此预约时长，请重新查询规则。"],
  not_whole_hour: [422, "预约需要从业务时区的整点开始。"],
  seat_not_found: [404, "该座位不存在或不可访问。"],
  idempotency_key_reused: [
    409,
    "原预约请求无法按当前内容恢复，请先核对我的预约或联系管理员。",
  ],
  unauthenticated: [401, "请先登录或重新登录后操作。"],
  forbidden: [403, "当前账号没有预约权限。"],
  INVALID_SESSION: [401, "登录已失效，请重新登录。"],
  AUTHENTICATION_REQUIRED: [401, "请先登录后操作。"],
  FORBIDDEN: [403, "当前账号没有预约权限。"],
};
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("invalid payload");
  return value as Record<string, unknown>;
}
function identifier(value: unknown): string {
  if (typeof value === "number" && Number.isSafeInteger(value) && value > 0)
    return String(value);
  if (isIdentifier(value)) return value;
  throw new Error("invalid identifier");
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim())
    throw new Error("invalid text");
  return value;
}
function instant(value: unknown): string {
  if (!isInstant(value)) throw new Error("invalid timestamp");
  return value;
}
function nullableTime(value: unknown): string | null {
  return value === null ? null : instant(value);
}
function parseReceipt(
  value: unknown,
  intent: BookingIntent,
): ReservationReceipt {
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
    !matchesIntent(receipt, intent) ||
    (receipt.status === "booked" &&
      (receipt.checkedInAt !== null || receipt.cancelledAt !== null)) ||
    (receipt.status === "checked_in" && receipt.checkedInAt === null) ||
    (["cancelled", "no_show"].includes(receipt.status) &&
      receipt.cancelledAt === null)
  )
    throw new Error("mismatched receipt");
  return receipt;
}
export function createHttpBookingGateway(options: {
  getSession: () => { subjectId: string; accessToken: string } | null;
  request?: typeof fetch;
  timeoutMs?: number;
}): BookingGateway {
  const { getSession, request = fetch, timeoutMs = 10000 } = options;
  if (!Number.isFinite(timeoutMs) || timeoutMs < 1)
    throw new BookingError("预约接入配置无效。");
  async function send(
    method: "GET" | "POST",
    url: string,
    intent: BookingIntent,
    signal?: AbortSignal,
  ): Promise<ReservationReceipt> {
    validateSelection(intent);
    let session;
    try {
      session = getSession();
    } catch {
      throw new BookingError("无法读取当前登录状态，请重新登录。");
    }
    if (!session || session.subjectId !== intent.actorId)
      throw new BookingError("账号已变化，请切回原账号核对预约。");
    if (
      typeof session.subjectId !== "string" ||
      !session.subjectId.trim() ||
      typeof session.accessToken !== "string" ||
      !/^[\x21-\x7e]+$/.test(session.accessToken)
    )
      throw new BookingError("登录信息无效，请重新登录。");
    if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(intent.key))
      throw new BookingError("预约请求标识无效，请重新选择。");
    // A's current request schema is numeric. Do not round an unsafe BIGINT.
    const seatId = Number(intent.seat.id);
    if (
      method === "POST" &&
      (!Number.isSafeInteger(seatId) || String(seatId) !== intent.seat.id)
    )
      throw new BookingError(
        "座位编号超出当前接口的安全范围，请联系管理员确认接口格式。",
      );
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    const timer = setTimeout(abort, timeoutMs);
    let attempted = false;
    try {
      if (controller.signal.aborted) throw new BookingError("请求已取消。");
      attempted = true;
      const response = await request(url, {
        method,
        credentials: "same-origin",
        mode: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${session.accessToken}`,
          ...(method === "POST"
            ? {
                "Content-Type": "application/json",
                "Idempotency-Key": intent.key,
              }
            : {}),
        },
        ...(method === "POST"
          ? {
              body: JSON.stringify({
                seat_id: seatId,
                start_at: intent.startAt,
                hours: intent.hours,
              }),
            }
          : {}),
        signal: controller.signal,
      });
      if (!response.ok) {
        let data: Record<string, unknown> = {};
        try {
          data = object(await response.json());
        } catch {
          /* Never expose raw server data. */
        }
        const error =
          data.error && typeof data.error === "object"
            ? object(data.error)
            : {};
        const code = typeof error.code === "string" ? error.code : "";
        if (
          Object.hasOwn(rejected, code) &&
          rejected[code]![0] === response.status
        )
          throw new BookingError(rejected[code]![1]);
        if (response.status === 422 && Array.isArray(data.detail))
          throw new BookingError("预约字段未被服务接受，请重新查询后选择。");
        throw new BookingError(
          method === "POST"
            ? "提交结果尚未确认，请核对原预约请求。"
            : "暂时无法读取预约状态，请稍后核对。",
          method === "POST",
        );
      }
      if (
        (method === "POST" && ![200, 201].includes(response.status)) ||
        (method === "GET" && response.status !== 200) ||
        !response.headers.get("Content-Type")?.includes("application/json")
      )
        throw new Error("invalid response");
      const receipt = parseReceipt(await response.json(), intent);
      if (getSession()?.subjectId !== intent.actorId)
        throw new BookingError(
          "账号已变化，请切回原账号核对预约。",
          method === "POST",
        );
      return receipt;
    } catch (error) {
      if (error instanceof BookingError) throw error;
      throw new BookingError(
        method === "POST" && attempted
          ? "提交结果尚未确认，请核对原预约请求。"
          : "暂时无法读取预约状态，请稍后核对。",
        method === "POST" && attempted,
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  return {
    mode: "live",
    currentActorId() {
      try {
        const value = getSession()?.subjectId;
        return typeof value === "string" && value.trim() ? value : null;
      } catch {
        return null;
      }
    },
    create: (intent, signal) =>
      send("POST", "/api/v1/m1/reservations", intent, signal),
    async read(id, intent, signal) {
      if (!isIdentifier(id))
        throw new BookingError("预约标识无效，请联系管理员核对。");
      const receipt = await send(
        "GET",
        `/api/v1/m1/reservations/${id}`,
        intent,
        signal,
      );
      if (receipt.id !== id)
        throw new BookingError("预约响应不匹配，请稍后重新核对。");
      return receipt;
    },
  };
}
export function createUnconfiguredBookingGateway(): BookingGateway {
  const unavailable = async (): Promise<never> => {
    throw new BookingError("预约提交尚未接入。");
  };
  return {
    mode: "unconfigured",
    currentActorId: () => null,
    create: unavailable,
    read: unavailable,
  };
}
