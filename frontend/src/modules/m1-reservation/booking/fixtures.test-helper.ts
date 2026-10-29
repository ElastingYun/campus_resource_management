import type {
  BookingIntent,
  BookingSelection,
  ReservationReceipt,
} from "./models";
export function selection(): BookingSelection {
  return {
    seat: {
      id: "1",
      code: "01",
      roomId: "2",
      roomCode: "A101",
      roomName: "示例教室",
      outlet: "fixed",
      status: "available",
      reasons: [],
    },
    startAt: "2032-04-12T09:00:00+08:00",
    endAt: "2032-04-12T11:00:00+08:00",
    hours: 2,
  };
}
export function intent(): BookingIntent {
  return { ...selection(), actorId: "subject-a", key: "b04-synthetic-key" };
}
export function receipt(): ReservationReceipt {
  const value = selection();
  return {
    id: "7",
    seatId: value.seat.id,
    roomId: value.seat.roomId,
    seatCode: value.seat.code,
    roomCode: value.seat.roomCode,
    roomName: value.seat.roomName,
    startAt: value.startAt,
    endAt: value.endAt,
    status: "booked",
    checkedInAt: null,
    cancelledAt: null,
    cancelReason: null,
    createdAt: "2032-04-11T08:00:00Z",
  };
}
export function wireReceipt() {
  const value = receipt();
  return {
    id: 7,
    seat_id: 1,
    room_id: 2,
    seat_code: value.seatCode,
    room_code: value.roomCode,
    room_name: value.roomName,
    start_at: value.startAt,
    end_at: value.endAt,
    status: value.status as string,
    checked_in_at: null as string | null,
    cancelled_at: null as string | null,
    cancel_reason: null as string | null,
    created_at: value.createdAt,
  };
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
