import { ResourceMessage } from "./models";
import type { Page, ResourceGateway, Room, Seat } from "./models";

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isId = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[1-9]\d{0,18}$/.test(value) &&
  BigInt(value) <= 9223372036854775807n;
const isRevision = (value: unknown) =>
  typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const isTime = (value: unknown) =>
  typeof value === "string" &&
  /^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(value);
const boundedText = (value: unknown, min: number, max: number) =>
  typeof value === "string" && value.length >= min && value.length <= max;

function room(value: unknown): Room {
  if (
    !isObject(value) ||
    !isId(value.id) ||
    !isRevision(value.revision) ||
    !boundedText(value.code, 1, 32) ||
    !boundedText(value.name, 1, 100) ||
    !boundedText(value.location, 0, 200) ||
    !["campus", "department"].includes(String(value.access_scope)) ||
    !(
      value.department_id === null || typeof value.department_id === "string"
    ) ||
    typeof value.enabled !== "boolean" ||
    !isTime(value.open_time) ||
    !isTime(value.close_time)
  ) {
    throw new Error("Invalid room response");
  }
  return value as unknown as Room;
}
function seat(value: unknown): Seat {
  if (
    !isObject(value) ||
    !isId(value.id) ||
    !isId(value.room_id) ||
    !isRevision(value.revision) ||
    !boundedText(value.code, 1, 32) ||
    typeof value.enabled !== "boolean" ||
    !["none", "fixed", "rail"].includes(String(value.outlet_type))
  ) {
    throw new Error("Invalid seat response");
  }
  return value as unknown as Seat;
}
function page<T>(value: unknown, parse: (item: unknown) => T): Page<T> {
  if (
    !isObject(value) ||
    !Array.isArray(value.items) ||
    !Number.isSafeInteger(value.total) ||
    Number(value.total) < value.items.length ||
    !Number.isSafeInteger(value.limit) ||
    Number(value.limit) < 1 ||
    Number(value.limit) > 100 ||
    !Number.isSafeInteger(value.offset) ||
    Number(value.offset) < 0
  ) {
    throw new Error("Invalid page response");
  }
  return {
    items: value.items.map(parse),
    total: Number(value.total),
    limit: Number(value.limit),
    offset: Number(value.offset),
  };
}

/** A module-local adapter; it neither chooses C's login method nor stores tokens. */
export function createHttpResourceGateway(
  request: typeof fetch = globalThis.fetch.bind(globalThis),
  base = "/api/v1/resources",
): ResourceGateway {
  async function send<T>(
    path: string,
    method: string,
    parse: (data: unknown) => T,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    const write = method !== "GET";
    if (!/^\/(?!\/)[A-Za-z0-9/_-]+$/.test(base) || signal?.aborted) {
      throw new ResourceMessage("请求未发送，请检查配置或重新加载。");
    }
    let response: Response;
    try {
      response = await request(base.replace(/\/$/, "") + path, {
        method,
        credentials: "same-origin",
        mode: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: signal
          ? AbortSignal.any([signal, AbortSignal.timeout(10000)])
          : AbortSignal.timeout(10000),
      });
    } catch {
      throw new ResourceMessage(
        write
          ? "保存结果尚不确定，请先刷新列表核对，暂不要重复提交。"
          : "暂时无法读取资源，请重试。",
        write,
      );
    }
    if (!response.ok) {
      const uncertain =
        write && (response.status >= 500 || response.status === 408);
      let message =
        response.status === 401
          ? "登录已失效，请重新登录。"
          : response.status === 403
            ? "没有执行该操作的权限。"
            : response.status === 404
              ? "资源不存在或不可访问，请刷新列表。"
              : response.status === 409
                ? "编号重复或资料已更新，请刷新后核对。"
                : response.status === 422
                  ? "请检查必填字段、编号和插座选项。"
                  : "资源服务暂不可用。";
      if (uncertain)
        message = "保存结果尚不确定，请先刷新列表核对，暂不要重复提交。";
      throw new ResourceMessage(message, uncertain, response.status);
    }
    try {
      return parse(await response.json());
    } catch {
      throw new ResourceMessage(
        write
          ? "保存响应无法确认，请先查询结果，暂不要重复提交。"
          : "资源数据格式不符合约定，请联系管理员。",
        write,
      );
    }
  }
  const idPath = (value: string) => {
    if (!isId(value)) throw new ResourceMessage("资源标识无效，请重新加载。");
    return value;
  };
  const queryString = (query: Record<string, unknown>) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    return "?" + params.toString();
  };
  return {
    mode: "live",
    listRooms: (query, signal) =>
      send(
        "/rooms" + queryString({ ...query }),
        "GET",
        (data) => page(data, room),
        undefined,
        signal,
      ),
    listSeats: (id, query, signal) =>
      send(
        `/rooms/${idPath(id)}/seats` + queryString({ ...query }),
        "GET",
        (data) => {
          const result = page(data, seat);
          if (result.items.some((item) => item.room_id !== id))
            throw new Error("Wrong room response");
          return result;
        },
        undefined,
        signal,
      ),
    createRoom: (draft) => send("/rooms", "POST", room, draft),
    updateRoom: (id, draft, revision) =>
      send(`/rooms/${idPath(id)}`, "PATCH", room, {
        ...draft,
        expected_revision: revision,
      }),
    createSeat: (id, draft) =>
      send(`/rooms/${idPath(id)}/seats`, "POST", seat, draft),
    updateSeat: (id, draft, revision) =>
      send(`/seats/${idPath(id)}`, "PATCH", seat, {
        ...draft,
        expected_revision: revision,
      }),
  };
}

export function createUnconfiguredResourceGateway(): ResourceGateway {
  const unavailable = async (): Promise<never> => {
    throw new ResourceMessage("资源服务尚未接入，暂不能读取或保存真实数据。");
  };
  return {
    mode: "unconfigured",
    listRooms: unavailable,
    listSeats: unavailable,
    createRoom: unavailable,
    updateRoom: unavailable,
    createSeat: unavailable,
    updateSeat: unavailable,
  };
}
