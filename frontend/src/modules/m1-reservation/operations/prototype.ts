import type { OperationsGateway } from "./models";
import { businessDate } from "../seat-search/models";
export function createPrototypeOperationsGateway(): OperationsGateway {
  return {
    mode: "prototype",
    currentActorId: () => "prototype-operator",
    capabilities: () => ({ operations: true, roomCode: true }),
    async usage(date) {
      return {
        date,
        rooms: [
          {
            id: "2",
            code: "A101",
            seats: 20,
            reservations: {
              booked: 4,
              checked_in: 6,
              cancelled: 1,
              no_show: 1,
            },
            checkedInHours: 12,
            capacityHours: 240,
            utilization: 0.05,
          },
        ],
      };
    },
    async events(query) {
      return [
        {
          roomId: query.roomId,
          seatId: null,
          startAt: "2032-04-12T09:00:00+08:00",
          endAt: null,
          occurredAt: "2032-04-12T08:00:00+08:00",
          sourceType: "m3_repair",
          sourceId: "synthetic-repair",
          action: "synthetic",
        },
      ];
    },
    async roomCode(roomId) {
      return {
        roomId,
        date: businessDate(new Date(), "Asia/Shanghai"),
        code: "123456",
        validUntil: new Date(Date.now() + 60000).toISOString(),
      };
    },
  };
}
