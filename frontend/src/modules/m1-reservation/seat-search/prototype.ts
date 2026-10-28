import { localStart, SearchError, validQuery } from "./models";
import type { SearchSeat, SeatSearchGateway } from "./models";

export function createPrototypeSeatSearchGateway(): SeatSearchGateway {
  const settings = { maxHours: 4, bookingHorizonDays: 7 };
  const example = (
    id: string,
    roomId: string,
    roomCode: string,
    roomName: string,
    status: SearchSeat["status"],
    reasons: string[],
    outlet: SearchSeat["outlet"],
  ): SearchSeat => ({
    id,
    code: id.padStart(2, "0"),
    roomId,
    roomCode,
    roomName,
    status,
    reasons,
    outlet,
  });
  const seats = [
    example("1", "1", "A101", "示例自习室 A101", "available", [], "fixed"),
    example(
      "2",
      "1",
      "A101",
      "示例自习室 A101",
      "unavailable",
      ["reserved"],
      "none",
    ),
    example(
      "3",
      "2",
      "B202",
      "示例自习室 B202",
      "unavailable",
      ["m2_approval", "m3_repair"],
      "rail",
    ),
    example(
      "4",
      "2",
      "B202",
      "示例自习室 B202",
      "unknown",
      ["future_status"],
      "fixed",
    ),
  ];
  return {
    mode: "prototype",
    businessTimeZone: "Asia/Shanghai",
    async loadSettings() {
      return { ...settings };
    },
    async search(query) {
      if (!validQuery(query, settings))
        throw new SearchError("请填写有效的日期、整点和时长。");
      const startAt = `${localStart(query)}+08:00`;
      const endAt = new Date(
        Date.parse(startAt) + query.hours * 3600000,
      ).toISOString();
      return {
        startAt,
        endAt,
        hours: query.hours,
        seats: seats
          .filter(
            (seat) =>
              (!query.roomId || query.roomId === seat.roomId) &&
              (!query.outlet || query.outlet === seat.outlet) &&
              (!query.onlyAvailable || seat.status === "available"),
          )
          .map((seat) => ({ ...seat, reasons: [...seat.reasons] })),
      };
    },
  };
}
