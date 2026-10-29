import { GatewayMessage } from "./models";
import type { RoomOptionsPage, RoomOptionsQuery } from "./models";
import { isObject } from "./c-session";
export function roomQuery(query: RoomOptionsQuery = {}) {
  const { q = "", limit = 20, offset = 0 } = query;
  if (
    typeof q !== "string" ||
    q.length > 100 ||
    !Number.isSafeInteger(limit) ||
    limit < 1 ||
    limit > 100 ||
    !Number.isSafeInteger(offset) ||
    offset < 0
  )
    throw new GatewayMessage(
      "教室搜索最多100字符，每页1～100条，页码需要有效。",
    );
  return { q, limit, offset };
}
const invalid = () =>
  new GatewayMessage("教室目录响应异常，请重新查询；当前不能选择教室。");
export function parseRoomOptions(
  value: unknown,
  query: ReturnType<typeof roomQuery>,
): RoomOptionsPage {
  if (
    !isObject(value) ||
    !Array.isArray(value.items) ||
    typeof value.total !== "number" ||
    !Number.isSafeInteger(value.total) ||
    value.total < 0 ||
    value.limit !== query.limit ||
    value.offset !== query.offset ||
    value.items.length > query.limit ||
    value.items.length > Math.max(0, value.total - query.offset)
  )
    throw invalid();
  const seen = new Set<string>();
  const items = value.items.map((item) => {
    if (
      !isObject(item) ||
      typeof item.id !== "string" ||
      !/^[1-9][0-9]{0,18}$/.test(item.id) ||
      BigInt(item.id) > 9223372036854775807n ||
      seen.has(item.id) ||
      typeof item.code !== "string" ||
      !item.code.trim() ||
      item.code.length > 32 ||
      typeof item.name !== "string" ||
      !item.name.trim() ||
      item.name.length > 100 ||
      typeof item.location !== "string" ||
      item.location.length > 200
    )
      throw invalid();
    seen.add(item.id);
    return {
      id: item.id,
      code: item.code,
      name: item.name,
      location: item.location,
    };
  });
  return {
    items,
    total: value.total,
    limit: query.limit,
    offset: query.offset,
  };
}
