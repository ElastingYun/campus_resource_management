/** E ticket contract at main 40a9977. No role, room-eligibility or action policy. */
export interface M3Session {
  subjectId: string;
  accessToken: string;
  canCreate: boolean;
  canReadOwn: boolean;
}

export interface ReportDraft {
  roomId: string;
  description: string;
}

export interface RepairTicket extends ReportDraft {
  id: string;
  status: string;
  createdAt: string;
}

export interface OwnTicketPage {
  items: RepairTicket[];
  limit: number;
  offset: number;
}

export type M3Failure =
  | "configuration"
  | "session"
  | "permission"
  | "validation"
  | "busy"
  | "recovery_required"
  | "session_changed"
  | "http"
  | "network"
  | "timeout"
  | "invalid_response";

export class M3ClientError extends Error {
  constructor(
    readonly kind: M3Failure,
    readonly mayHaveWritten = false,
    readonly status?: number,
    readonly serverCode?: string,
  ) {
    super(
      mayHaveWritten
        ? "报修结果尚未确认，请保留原记录并恢复查询。"
        : "无法完成请求，请检查会话、输入或服务状态。",
    );
    this.name = "M3ClientError";
  }
}

export const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

export const isUuid = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);

export const isRoomId = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[1-9][0-9]{0,18}$/.test(v) &&
  (v.length < 19 || v <= "9223372036854775807");

export function prepareDraft(draft: ReportDraft): Readonly<ReportDraft> {
  if (
    !isObject(draft) ||
    !isRoomId(draft.roomId) ||
    typeof draft.description !== "string" ||
    /[\u0000-\u001f\u007f]/.test(draft.description)
  )
    throw new M3ClientError("validation");
  const description = draft.description.trim();
  if (description.length === 0 || Array.from(description).length > 2000)
    throw new M3ClientError("validation");
  return Object.freeze({ roomId: draft.roomId, description });
}

export function parseTicket(value: unknown): RepairTicket {
  if (
    !isObject(value) ||
    !isUuid(value.id) ||
    !isRoomId(value.room_id) ||
    typeof value.description !== "string" ||
    value.description.trim().length === 0 ||
    Array.from(value.description).length > 2000 ||
    /[\u0000-\u001f\u007f]/.test(value.description) ||
    typeof value.status !== "string" ||
    !/^[A-Z][A-Z_]{0,39}$/.test(value.status) ||
    typeof value.created_at !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(
      value.created_at,
    ) ||
    !Number.isFinite(Date.parse(value.created_at))
  )
    throw new M3ClientError("invalid_response");
  return {
    id: value.id.toLowerCase(),
    roomId: value.room_id,
    description: value.description,
    status: value.status,
    createdAt: value.created_at,
  };
}

export function parsePage(
  value: unknown,
  limit: number,
  offset: number,
): OwnTicketPage {
  if (
    !isObject(value) ||
    !Array.isArray(value.items) ||
    value.items.length > limit ||
    value.limit !== limit ||
    value.offset !== offset
  )
    throw new M3ClientError("invalid_response");
  const items = value.items.map(parseTicket);
  if (new Set(items.map((item) => item.id)).size !== items.length)
    throw new M3ClientError("invalid_response");
  return { items, limit, offset };
}
