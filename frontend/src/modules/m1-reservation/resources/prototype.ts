/** Synthetic in-memory interaction demo. Never selected as fallback for a real API. */
import { ResourceMessage } from "./models";
import type { Page, ResourceGateway, Room, Seat } from "./models";

export function createPrototypeResourceGateway(): ResourceGateway {
  let sequence = 100;
  let version = 0;
  const revision = () => (++version).toString(16).padStart(64, "0");
  const rooms: Room[] = [
    {
      id: "1",
      code: "DEMO-A101",
      name: "示例自习室 A101",
      location: "示例教学楼 · 一层",
      access_scope: "campus",
      department_id: null,
      open_time: "08:00:00",
      close_time: "22:00:00",
      enabled: true,
      revision: revision(),
    },
    {
      id: "2",
      code: "DEMO-B201",
      name: "示例研讨室 B201",
      location: "示例教学楼 · 二层",
      access_scope: "department",
      department_id: "DEMO-DEPT",
      open_time: "09:00:00",
      close_time: "21:00:00",
      enabled: true,
      revision: revision(),
    },
  ];
  const seats: Seat[] = [
    {
      id: "1",
      room_id: "1",
      code: "01",
      outlet_type: "fixed",
      enabled: true,
      revision: revision(),
    },
    {
      id: "2",
      room_id: "1",
      code: "02",
      outlet_type: "none",
      enabled: true,
      revision: revision(),
    },
    {
      id: "3",
      room_id: "2",
      code: "01",
      outlet_type: "rail",
      enabled: true,
      revision: revision(),
    },
  ];
  const copy = <T>(value: T): T => structuredClone(value);
  const paginate = <T>(items: T[], limit = 20, offset = 0): Page<T> =>
    copy({
      items: items.slice(offset, offset + limit),
      total: items.length,
      limit,
      offset,
    });
  const conflict = () => {
    throw new ResourceMessage(
      "示例编号重复或资料已更新，请重新加载。",
      false,
      409,
    );
  };
  return {
    mode: "prototype",
    async listRooms(query) {
      const keyword = (query.q ?? "").toLocaleLowerCase();
      return paginate(
        rooms.filter((item) =>
          [item.code, item.name, item.location].some((text) =>
            text.toLocaleLowerCase().includes(keyword),
          ),
        ),
        query.limit,
        query.offset,
      );
    },
    async listSeats(roomId, query) {
      return paginate(
        seats.filter(
          (item) =>
            item.room_id === roomId &&
            item.code.includes(query.q ?? "") &&
            (!query.outlet_type || item.outlet_type === query.outlet_type),
        ),
        query.limit,
        query.offset,
      );
    },
    async createRoom(draft) {
      if (rooms.some((item) => item.code === draft.code)) return conflict();
      const record: Room = {
        ...draft,
        id: String(++sequence),
        access_scope: "campus",
        department_id: null,
        open_time: "08:00:00",
        close_time: "22:00:00",
        enabled: true,
        revision: revision(),
      };
      rooms.push(record);
      return copy(record);
    },
    async updateRoom(id, draft, expected) {
      const item = rooms.find((record) => record.id === id);
      if (
        !item ||
        item.revision !== expected ||
        rooms.some((record) => record.id !== id && record.code === draft.code)
      )
        return conflict();
      Object.assign(item, draft, { revision: revision() });
      return copy(item);
    },
    async createSeat(roomId, draft) {
      if (
        !rooms.some((item) => item.id === roomId) ||
        seats.some(
          (item) => item.room_id === roomId && item.code === draft.code,
        )
      )
        return conflict();
      const record: Seat = {
        ...draft,
        id: String(++sequence),
        room_id: roomId,
        enabled: true,
        revision: revision(),
      };
      seats.push(record);
      return copy(record);
    },
    async updateSeat(id, draft, expected) {
      const item = seats.find((record) => record.id === id);
      if (
        !item ||
        item.revision !== expected ||
        seats.some(
          (record) =>
            record.id !== id &&
            record.room_id === item.room_id &&
            record.code === draft.code,
        )
      )
        return conflict();
      Object.assign(item, draft, { revision: revision() });
      return copy(item);
    },
  };
}
