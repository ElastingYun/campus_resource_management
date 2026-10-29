import { GatewayMessage } from "./models";
import type {
  ApplicationDetails,
  ApplicationDraft,
  ApplicationView,
  M2Gateway,
  RoomOption,
  WorkspaceQuery,
  RoomOptionsQuery,
  RoomOptionsPage,
} from "./models";
import { parseRoomOptions, roomQuery } from "./room-options";
import { parseIntegrationProgress } from "./integration-progress";
import { isObject, isUuid } from "./c-session";
import type { CSession, CSessionState } from "./c-session";
import { M2HttpError, requestJson } from "./http";

const reviewLabels: Record<string, string> = {
  REVIEWING: "审批中",
  REJECTED: "已驳回",
  TIMED_OUT: "审批已超时",
  PASSED: "审批已通过",
};
const integrationLabels: Record<string, string> = {
  NONE: "尚无占用意图",
  APPLY_PENDING: "正在确认占用",
  APPLY_UNKNOWN: "占用结果待确认",
  APPLIED: "占用已确认",
  APPLY_CONFLICT: "占用冲突",
  RELEASE_PENDING: "正在确认释放",
  RELEASE_UNKNOWN: "释放结果待确认",
  RELEASED: "本申请来源已释放",
};
export interface CApplication {
  id: string;
  applicant_id: string;
  room_id: string;
  purpose: string;
  starts_at: string;
  ends_at: string;
  review_status: string;
  integration_status: string;
  step_index: number;
  step_count: number;
  deadline: string;
  version: number;
  revoked: boolean;
  effective: boolean;
  created_at: string;
  updated_at: string;
}
const aware = (value: unknown): value is string =>
  typeof value === "string" &&
  /(Z|[+-]\d{2}:\d{2})$/.test(value) &&
  Number.isFinite(Date.parse(value));
export function parseApplication(value: unknown): CApplication {
  if (
    !isObject(value) ||
    !isUuid(value.id) ||
    !isUuid(value.applicant_id) ||
    typeof value.room_id !== "string" ||
    !value.room_id ||
    typeof value.purpose !== "string" ||
    !aware(value.starts_at) ||
    !aware(value.ends_at) ||
    !aware(value.deadline) ||
    !aware(value.created_at) ||
    !aware(value.updated_at) ||
    typeof value.review_status !== "string" ||
    typeof value.integration_status !== "string" ||
    typeof value.revoked !== "boolean" ||
    typeof value.effective !== "boolean" ||
    !Number.isSafeInteger(value.version) ||
    Number(value.version) < 1 ||
    !Number.isSafeInteger(value.step_index) ||
    !Number.isSafeInteger(value.step_count) ||
    Number(value.step_index) < 0 ||
    Number(value.step_count) < 1 ||
    Number(value.step_index) > Number(value.step_count)
  )
    throw new GatewayMessage(
      "申请响应格式不符合 C-v1，请刷新或联系服务维护者。",
    );
  if (
    value.effective &&
    (value.revoked ||
      value.review_status !== "PASSED" ||
      value.integration_status !== "APPLIED")
  )
    throw new GatewayMessage("申请生效状态不一致，暂不能确认占用。");
  return value as unknown as CApplication;
}
function toView(value: CApplication, rooms: RoomOption[]): ApplicationView {
  return {
    id: value.id,
    roomId: value.room_id,
    roomName:
      rooms.find((room) => room.id === value.room_id)?.name ??
      `教室 ${value.room_id}`,
    purpose: value.purpose,
    startsAt: value.starts_at,
    endsAt: value.ends_at,
    statusLabel: value.revoked
      ? "已撤销"
      : (reviewLabels[value.review_status] ?? "状态待确认"),
    statusTone: value.effective
      ? "positive"
      : value.review_status === "REJECTED" ||
          value.review_status === "TIMED_OUT" ||
          value.integration_status === "APPLY_CONFLICT"
        ? "attention"
        : "neutral",
    note: value.effective
      ? "服务端已确认本申请占用生效。"
      : value.revoked
        ? "撤销只针对本申请来源；教室是否可预约仍由资源服务判断。"
        : "审批结果与占用生效分别确认，当前未确认本申请占用生效。",
    reviewLabel: reviewLabels[value.review_status] ?? "未知审批状态",
    integrationStatus: value.integration_status,
    integrationLabel:
      integrationLabels[value.integration_status] ?? "集成结果待确认",
    effective: value.effective,
    stepLabel: `${Math.min(value.step_index + 1, value.step_count)} / ${value.step_count}`,
    version: value.version,
  };
}
interface PendingWrite {
  owner: string;
  path: string;
  key: string;
  payload: unknown;
  label: string;
  resultId?: string;
  uncertain: boolean;
}
export interface CGatewayOptions {
  loadRooms?: (token: string) => Promise<RoomOption[]>;
  key?: () => string;
}
export function createCGateway(
  session: CSession,
  options: CGatewayOptions = {},
): M2Gateway & { hasAnyPending(): boolean } {
  let rooms: RoomOption[] = [];
  let roomOwner: CSessionState | undefined;
  let roomRequest = 0;
  const sameSession = (
    left: CSessionState | undefined,
    right: CSessionState | null,
  ) =>
    !!left &&
    !!right &&
    left.accessToken === right.accessToken &&
    left.identity.subject_id === right.identity.subject_id;
  const pending = new Map<string, PendingWrite>();
  const identity = (): CSessionState => {
    const current = session.state.value;
    if (!current) throw new GatewayMessage("请先登录。");
    return current;
  };
  const key = () =>
    options.key?.() ??
    `m2:${Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
  async function call(
    path: string,
    options: { method?: "GET" | "POST"; body?: unknown; key?: string } = {},
    current = identity(),
  ) {
    try {
      return await requestJson(path, {
        method: options.method,
        body: options.body,
        headers: {
          Authorization: `Bearer ${current.accessToken}`,
          ...(options.key ? { "Idempotency-Key": options.key } : {}),
        },
      });
    } catch (cause) {
      if (cause instanceof M2HttpError && cause.status === 401)
        session.invalidate(current.accessToken);
      throw cause;
    }
  }
  const safeError = (cause: unknown): GatewayMessage => {
    if (cause instanceof GatewayMessage) return cause;
    if (cause instanceof M2HttpError) {
      if (cause.mayHaveWritten)
        return new GatewayMessage(
          "操作结果尚未确认，请先恢复上次操作；不要新建重复申请。",
        );
      const codes: Record<string, string> = {
        REASON_REQUIRED: "请填写处理理由。",
        STALE_VERSION: "记录已更新，请刷新后再操作。",
        INVALID_INTERVAL: "结束时间必须晚于开始时间。",
        DURATION_EXCEEDED: "时长超出服务端配置上限。",
        TIME_GRANULARITY: "时段不符合服务端配置粒度。",
        IDEMPOTENCY_CONFLICT: "恢复键与原请求不一致，请联系维护者核对。",
        START_TOO_EARLY: "开始时间不满足服务端提前量要求。",
      };
      if (cause.serverCode && codes[cause.serverCode])
        return new GatewayMessage(codes[cause.serverCode]);
      return new GatewayMessage(
        cause.status === 401
          ? "会话已失效，请重新登录。"
          : cause.status === 403
            ? "当前账号无权执行此操作。"
            : cause.status === 404
              ? "记录不存在或当前账号不可见。"
              : cause.status === 409
                ? "记录或操作已发生冲突，请刷新核对。"
                : cause.status === 422
                  ? "申请内容未通过服务端校验，请检查输入。"
                  : "服务暂不可用，请保留输入后重试。",
      );
    }
    return new GatewayMessage("服务返回异常，请稍后核对。");
  };
  async function roomOptions(
    query: RoomOptionsQuery = {},
  ): Promise<RoomOptionsPage> {
    const current = identity(),
      parameters = roomQuery(query),
      request = ++roomRequest;
    rooms = [];
    roomOwner = undefined;
    try {
      const search = new URLSearchParams({
        q: parameters.q,
        limit: String(parameters.limit),
        offset: String(parameters.offset),
      });
      const data = await call(
        `/api/v1/resources/room-options?${search}`,
        {},
        current,
      );
      const page = parseRoomOptions(data, parameters);
      if (request !== roomRequest || !sameSession(current, session.state.value))
        throw new GatewayMessage("查询或登录状态已变化，请重新查询教室。");
      rooms = [...page.items];
      roomOwner = current;
      return page;
    } catch (cause) {
      if (cause instanceof GatewayMessage) throw cause;
      if (cause instanceof M2HttpError) {
        const messages: Record<string, string> = {
          identity_unconfigured: "教室目录尚未配置，请联系维护者。",
          RESOURCE_IDENTITY_UNAVAILABLE:
            "暂时无法核对教室目录身份，请稍后重试。",
          audit_unavailable: "暂时无法记录目录访问结果，请稍后重试。",
        };
        throw new GatewayMessage(
          cause.serverCode && messages[cause.serverCode]
            ? messages[cause.serverCode]
            : cause.status === 401
              ? "会话已失效，请重新登录。"
              : cause.status === 403
                ? "当前账号没有选择教室的权限。"
                : cause.status === 422
                  ? "教室查询条件无效，请检查搜索内容。"
                  : "教室目录暂不可用，请重新查询；不会改用管理列表或演示教室。",
        );
      }
      throw new GatewayMessage("教室查询未完成，请重新查询。");
    }
  }
  async function execute(operation: PendingWrite) {
    const current = identity();
    if (current.identity.subject_id !== operation.owner)
      throw new GatewayMessage("请使用发起该操作的原账号恢复结果。");
    try {
      if (!operation.resultId) {
        const response = await call(
          operation.path,
          { method: "POST", body: operation.payload, key: operation.key },
          current,
        );
        operation.uncertain = true;
        operation.resultId = parseApplication(response).id;
      }
      const latest = parseApplication(
        await call(
          `/api/v1/m2/applications/${encodeURIComponent(operation.resultId)}`,
          {},
          current,
        ),
      );
      if (latest.id !== operation.resultId)
        throw new GatewayMessage("申请关联标识不一致，请联系维护者。");
      pending.delete(operation.owner);
      return toView(latest, rooms);
    } catch (cause) {
      if (
        !operation.uncertain &&
        cause instanceof M2HttpError &&
        (cause.delivery === "not_sent" ||
          (cause.delivery === "responded" &&
            cause.status &&
            cause.status < 500 &&
            cause.status !== 408))
      )
        pending.delete(operation.owner);
      else operation.uncertain = true;
      throw safeError(cause);
    }
  }
  async function write(path: string, payload: unknown, label: string) {
    const current = identity(),
      owner = current.identity.subject_id;
    if (pending.has(owner))
      throw new GatewayMessage("仍有未确认的操作，请先恢复结果。");
    const operation: PendingWrite = {
      owner,
      path,
      payload: structuredClone(payload),
      key: key(),
      label,
      uncertain: false,
    };
    if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(operation.key))
      throw new GatewayMessage("无法生成有效恢复键，尚未发送请求。");
    pending.set(owner, operation);
    return execute(operation);
  }
  return {
    mode: "live",
    async load(query: WorkspaceQuery = {}) {
      const current = identity(),
        limit = query.limit ?? 20,
        offset = query.offset ?? 0;
      try {
        const path = query.review
          ? "/api/v1/m2/review-tasks"
          : "/api/v1/m2/applications";
        const data = await call(
          `${path}?limit=${limit}&offset=${offset}`,
          {},
          current,
        );
        if (!Array.isArray(data))
          throw new GatewayMessage("申请列表响应格式不符合 C-v1。");
        // Only explicit synthetic test adapters preload rooms. Production directory
        // reads belong to the paged picker and never block application queries.
        if (options.loadRooms) {
          rooms = await options.loadRooms(current.accessToken);
          if (!sameSession(current, session.state.value))
            throw new GatewayMessage("登录状态已变化，请重新载入。");
          roomOwner = current;
        }
        return {
          rooms: sameSession(roomOwner, current) ? [...rooms] : [],
          applications: data.map((item) =>
            toView(
              parseApplication(item),
              sameSession(roomOwner, current) ? rooms : [],
            ),
          ),
          canSubmit: current.identity.permissions.includes("m2.submit"),
          canReview: current.identity.permissions.includes("m2.review"),
          pagination: { limit, offset, hasNext: data.length === limit },
        };
      } catch (cause) {
        throw safeError(cause);
      }
    },
    roomOptions,
    async submit(draft: ApplicationDraft) {
      const current = identity();
      if (
        !current.identity.permissions.includes("m2.submit") ||
        !sameSession(roomOwner, current) ||
        !rooms.some((room) => room.id === draft.roomId)
      )
        throw new GatewayMessage("申请权限或教室列表尚未就绪，不能提交。");
      const start = new Date(draft.startsAt),
        end = new Date(draft.endsAt);
      if (
        !Number.isFinite(+start) ||
        !(+end > +start) ||
        !draft.purpose.trim() ||
        draft.purpose.trim().length > 2000
      )
        throw new GatewayMessage("请检查时段和用途（1～2000 字符）。");
      return write(
        "/api/v1/m2/applications",
        {
          room_id: draft.roomId,
          starts_at: start.toISOString(),
          ends_at: end.toISOString(),
          purpose: draft.purpose.trim(),
        },
        "申请提交",
      );
    },
    async detail(id: string): Promise<ApplicationDetails> {
      if (!isUuid(id)) throw new GatewayMessage("申请编号格式无效。");
      try {
        const path = `/api/v1/m2/applications/${encodeURIComponent(id)}`;
        const [record, actions, history] = await Promise.all([
          call(path),
          call(`${path}/actions`),
          call(`${path}/history`),
        ]);
        const application = parseApplication(record);
        if (
          application.id !== id ||
          !isObject(actions) ||
          actions.application_id !== id ||
          actions.version !== application.version ||
          !Number.isSafeInteger(actions.version) ||
          Number(actions.version) < 1 ||
          !Array.isArray(actions.allowed_actions) ||
          !actions.allowed_actions.every((value) =>
            ["APPROVE", "REJECT", "REVOKE"].includes(String(value)),
          ) ||
          !Array.isArray(history)
        )
          throw new GatewayMessage("详情或允许操作响应不符合 C-v1。");
        const entries = history.map((item) => {
          if (
            !isObject(item) ||
            !isUuid(item.id) ||
            !isUuid(item.actor_id) ||
            typeof item.decision !== "string" ||
            typeof item.comment !== "string" ||
            !aware(item.occurred_at)
          )
            throw new GatewayMessage("审批历史响应格式异常。");
          return {
            id: item.id,
            actorId: item.actor_id,
            decision: item.decision,
            comment: item.comment,
            occurredAt: item.occurred_at,
          };
        });
        return {
          ...toView(application, rooms),
          version: Number(actions.version),
          allowedActions:
            actions.allowed_actions as ApplicationDetails["allowedActions"],
          history: entries,
        };
      } catch (cause) {
        throw safeError(cause);
      }
    },
    async integration(id: string) {
      if (!isUuid(id)) throw new GatewayMessage("申请编号格式无效。");
      try {
        const value = await call(
          `/api/v1/m2/applications/${encodeURIComponent(id)}/integration`,
        );
        const progress = parseIntegrationProgress(value);
        if (progress.applicationId !== id)
          throw new GatewayMessage("占用进度与当前申请不一致，请重新载入。");
        return progress;
      } catch (cause) {
        throw safeError(cause);
      }
    },
    async decide(id, action, comment, version) {
      if (
        !isUuid(id) ||
        !Number.isSafeInteger(version) ||
        version < 1 ||
        comment.length > 2000
      )
        throw new GatewayMessage("请刷新申请并检查审批意见。");
      return write(
        `/api/v1/m2/applications/${encodeURIComponent(id)}/decisions`,
        { decision: action, comment, expected_version: version },
        "节点决定",
      );
    },
    async revoke(id, version) {
      if (!isUuid(id) || !Number.isSafeInteger(version) || version < 1)
        throw new GatewayMessage("请刷新申请后再撤销。");
      return write(
        `/api/v1/m2/applications/${encodeURIComponent(id)}/revocations`,
        { expected_version: version },
        "撤销",
      );
    },
    pending() {
      const current = session.state.value;
      const operation = current
        ? pending.get(current.identity.subject_id)
        : undefined;
      return operation ? { label: operation.label } : undefined;
    },
    async recover() {
      const current = identity(),
        operation = pending.get(current.identity.subject_id);
      if (!operation) throw new GatewayMessage("当前账号没有待恢复操作。");
      return execute(operation);
    },
    hasAnyPending() {
      return pending.size > 0;
    },
  };
}
