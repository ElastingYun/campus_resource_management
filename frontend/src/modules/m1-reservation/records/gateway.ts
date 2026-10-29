import { isIdentifier, reservationLabels } from "../booking/models";
import {
  identifier,
  instant,
  object,
  parseReceipt,
  text,
} from "../booking/receipt";
import { RecordsError } from "./models";
import type { RecordsGateway } from "./models";

const rejected: Record<string, [number, string]> = {
  unauthenticated: [401, "请先登录或重新登录。"],
  forbidden: [403, "当前账号没有此操作权限。"],
  INVALID_SESSION: [401, "登录已失效，请重新登录。"],
  AUTHENTICATION_REQUIRED: [401, "请先登录。"],
  FORBIDDEN: [403, "当前账号没有此操作权限。"],
  reservation_not_found: [404, "预约不存在或不可访问。"],
  invalid_checkin_code: [422, "现场码不正确，请核对教室后重新输入。"],
  checkin_not_open: [409, "尚未到服务端允许的签到时间。"],
  checkin_closed: [409, "服务端签到窗口已关闭，请刷新预约状态。"],
};

export function createHttpRecordsGateway(options: {
  getSession: () => { subjectId: string; accessToken: string } | null;
  request?: typeof fetch;
  timeoutMs?: number;
}): RecordsGateway {
  const { getSession, request = fetch, timeoutMs = 10000 } = options;
  if (!Number.isFinite(timeoutMs) || timeoutMs < 1)
    throw new RecordsError("预约记录接入配置无效。");
  const actor = () => {
    try {
      const id = getSession()?.subjectId;
      return typeof id === "string" && id.trim() ? id : null;
    } catch {
      return null;
    }
  };
  async function send(
    url: string,
    actorId: string,
    signal?: AbortSignal,
    code?: string,
  ): Promise<unknown> {
    let session;
    try {
      session = getSession();
    } catch {
      throw new RecordsError("无法读取登录状态。");
    }
    if (
      !session ||
      session.subjectId !== actorId ||
      actor() !== actorId ||
      !actorId.trim() ||
      typeof session.accessToken !== "string" ||
      !/^[\x21-\x7e]+$/.test(session.accessToken)
    )
      throw new RecordsError("请使用原账号核对预约。");
    const writing = code !== undefined;
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    const timer = setTimeout(abort, timeoutMs);
    let attempted = false;
    try {
      if (controller.signal.aborted) throw new RecordsError("请求已取消。");
      attempted = true;
      const response = await request(url, {
        method: writing ? "POST" : "GET",
        credentials: "same-origin",
        mode: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${session.accessToken}`,
          ...(writing ? { "Content-Type": "application/json" } : {}),
        },
        ...(writing ? { body: JSON.stringify({ code }) } : {}),
        signal: controller.signal,
      });
      if (!response.ok) {
        let data: Record<string, unknown> = {};
        try {
          data = object(await response.json());
        } catch {
          /* Do not expose raw payloads. */
        }
        const error =
          data.error && typeof data.error === "object"
            ? object(data.error)
            : {};
        const errorCode = typeof error.code === "string" ? error.code : "";
        if (
          Object.hasOwn(rejected, errorCode) &&
          rejected[errorCode]![0] === response.status
        )
          throw new RecordsError(rejected[errorCode]![1]);
        if (response.status === 422 && Array.isArray(data.detail))
          throw new RecordsError("签到字段未被服务接受，请核对输入。");
        throw new RecordsError(
          writing
            ? "签到结果尚未确认，请查询原预约。"
            : "暂时无法读取预约记录。",
          writing,
        );
      }
      if (
        response.status !== 200 ||
        !response.headers.get("Content-Type")?.includes("application/json")
      )
        throw new Error("invalid response");
      const data: unknown = await response.json();
      if (controller.signal.aborted || actor() !== actorId)
        throw new Error("request expired or actor changed");
      return data;
    } catch (error) {
      if (error instanceof RecordsError) throw error;
      throw new RecordsError(
        writing && attempted
          ? "签到结果尚未确认，请查询原预约。"
          : "暂时无法读取预约记录。",
        writing && attempted,
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  function path(id: string) {
    if (!isIdentifier(id)) throw new RecordsError("预约编号无效。");
    return `/api/v1/m1/reservations/${id}`;
  }
  function receipt(value: unknown, id: string, writing = false) {
    try {
      const result = parseReceipt(value);
      if (result.id !== id) throw new Error("wrong reservation");
      return result;
    } catch {
      throw new RecordsError("预约响应未通过校验，请重新核对。", writing);
    }
  }
  return {
    mode: "live",
    currentActorId: actor,
    async list(query, actorId, signal) {
      if (
        !Number.isSafeInteger(query.limit) ||
        query.limit < 1 ||
        query.limit > 200 ||
        !Number.isSafeInteger(query.offset) ||
        query.offset < 0 ||
        (query.status !== "" && !Object.hasOwn(reservationLabels, query.status))
      )
        throw new RecordsError("列表条件无效。");
      const params = new URLSearchParams({
        limit: String(query.limit),
        offset: String(query.offset),
      });
      if (query.status) params.set("status", query.status);
      const value = await send(
        `/api/v1/m1/reservations/me?${params}`,
        actorId,
        signal,
      );
      try {
        const data = object(value);
        if (
          data.limit !== query.limit ||
          data.offset !== query.offset ||
          !Array.isArray(data.items) ||
          data.items.length > query.limit
        )
          throw new Error("invalid page");
        const items = data.items.map(parseReceipt);
        if (
          new Set(items.map((item) => item.id)).size !== items.length ||
          items.some((item) => query.status && item.status !== query.status)
        )
          throw new Error("invalid items");
        return { items, limit: query.limit, offset: query.offset };
      } catch {
        throw new RecordsError("预约列表未通过校验，请重新查询。");
      }
    },
    async read(id, actorId, signal) {
      return receipt(await send(path(id), actorId, signal), id);
    },
    async checkIn(id, code, actorId, signal) {
      if (!code.trim() || code.trim().length > 32)
        throw new RecordsError("请输入 1–32 个字符的现场码。");
      return receipt(
        await send(`${path(id)}/check-in`, actorId, signal, code.trim()),
        id,
        true,
      );
    },
    async violations(actorId, signal) {
      const value = await send("/api/v1/m1/violations/me", actorId, signal);
      try {
        if (!Array.isArray(value)) throw new Error("invalid records");
        const items = value.map((item) => {
          const data = object(item);
          return {
            id: identifier(data.id),
            reservationId: identifier(data.reservation_id),
            reason: text(data.reason),
            occurredAt: instant(data.occurred_at),
          };
        });
        if (new Set(items.map((item) => item.id)).size !== items.length)
          throw new Error("duplicate records");
        return items;
      } catch {
        throw new RecordsError("违约记录未通过校验，请重新查询。");
      }
    },
  };
}
export function createUnconfiguredRecordsGateway(): RecordsGateway {
  const unavailable = async (): Promise<never> => {
    throw new RecordsError("预约记录尚未接入。");
  };
  return {
    mode: "unconfigured",
    currentActorId: () => null,
    list: unavailable,
    read: unavailable,
    checkIn: unavailable,
    violations: unavailable,
  };
}
