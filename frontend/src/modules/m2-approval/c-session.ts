import { shallowRef } from "vue";
import { GatewayMessage } from "./models";
import { M2HttpError, requestJson } from "./http";

export interface CIdentity {
  subject_id: string;
  department_id: string;
  roles: string[];
  permissions: string[];
  data_scopes: { room_ids: string[]; all_rooms: boolean };
}
export interface CSessionState {
  accessToken: string;
  expiresAt: string;
  identity: CIdentity;
}
export const isUuid = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
export const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");
export function parseIdentity(value: unknown): CIdentity {
  if (
    !isObject(value) ||
    !isUuid(value.subject_id) ||
    typeof value.department_id !== "string" ||
    !strings(value.roles) ||
    !strings(value.permissions) ||
    !isObject(value.data_scopes) ||
    !strings(value.data_scopes.room_ids) ||
    typeof value.data_scopes.all_rooms !== "boolean"
  )
    throw new GatewayMessage("身份响应格式不符合 C-v1，请联系服务维护者。");
  return {
    subject_id: value.subject_id,
    department_id: value.department_id,
    roles: [...value.roles],
    permissions: [...value.permissions],
    data_scopes: {
      room_ids: [...value.data_scopes.room_ids],
      all_rooms: value.data_scopes.all_rooms,
    },
  };
}
export function createCSession() {
  const state = shallowRef<CSessionState | null>(null);
  const notice = shallowRef("");
  let generation = 0;
  function invalidate(token: string) {
    if (state.value?.accessToken === token) {
      state.value = null;
      notice.value = "会话已失效，请重新登录。";
      generation++;
    }
  }
  async function login(username: string, password: string) {
    const attempt = ++generation;
    notice.value = "";
    try {
      const value = await requestJson("/api/v1/auth/sessions", {
        method: "POST",
        body: { username: username.trim(), password },
      });
      if (
        !isObject(value) ||
        typeof value.access_token !== "string" ||
        !/^[!-~]{1,4096}$/.test(value.access_token) ||
        value.token_type !== "bearer" ||
        typeof value.expires_at !== "string" ||
        !Number.isFinite(Date.parse(value.expires_at))
      )
        throw new GatewayMessage("登录响应格式无效，请联系服务维护者。");
      const identity = parseIdentity(
        await requestJson("/api/v1/auth/me", {
          headers: { Authorization: `Bearer ${value.access_token}` },
        }),
      );
      if (attempt !== generation)
        throw new GatewayMessage("登录操作已取消，请重新登录。");
      state.value = {
        accessToken: value.access_token,
        expiresAt: value.expires_at,
        identity,
      };
    } catch (cause) {
      if (cause instanceof GatewayMessage) throw cause;
      if (cause instanceof M2HttpError && cause.status === 429)
        throw new GatewayMessage("登录尝试过于频繁，请稍后再试。");
      if (cause instanceof M2HttpError && cause.status === 401)
        throw new GatewayMessage("账号或密码不正确，或账号已停用。");
      throw new GatewayMessage("暂时无法完成登录，请检查服务状态后重试。");
    }
  }
  async function logout() {
    const token = state.value?.accessToken;
    state.value = null;
    generation++;
    notice.value = "";
    if (!token) return;
    try {
      await requestJson("/api/v1/auth/sessions/current", {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      notice.value = "本页会话已清除，服务端退出未确认；请留意会话有效期。";
    }
  }
  return { state, notice, login, logout, invalidate };
}
export type CSession = ReturnType<typeof createCSession>;
