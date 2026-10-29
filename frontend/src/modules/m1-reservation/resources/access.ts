import { createHttpResourceGateway } from "./gateway";
import { ResourceMessage } from "./models";
import type { ResourceGateway } from "./models";
import { createResourceSession } from "./session";

/** Supplied in memory by C's host after login + /auth/me; never persisted here. */
export interface TrustedResourceSession {
  subjectId: string;
  accessToken: string;
  permissions: readonly string[];
  dataScopes: { allRooms: boolean; roomIds: readonly string[] };
}
export interface ResourcePermissionMapping {
  read: string;
  manage: string;
  createRooms: string;
}
type Capability = keyof ResourcePermissionMapping;
const permissionPattern = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const validId = (id: unknown): id is string =>
  typeof id === "string" &&
  /^[1-9]\d{0,18}$/.test(id) &&
  BigInt(id) <= 9223372036854775807n;

/** Creates the transport and retained editor together; the host owns their lifetime. */
export function createAuthenticatedResourceAccess(options: {
  getSession(): TrustedResourceSession | null;
  permissions: ResourcePermissionMapping;
  request?: typeof fetch;
}) {
  const permissions = Object.freeze({ ...options.permissions });
  if (
    ![permissions.read, permissions.manage, permissions.createRooms].every(
      (name) => typeof name === "string" && permissionPattern.test(name),
    )
  )
    throw new Error("请显式配置 C 的资源读取、管理和新建权限名。");
  const request = options.request ?? globalThis.fetch.bind(globalThis);
  let previous = "",
    version = 0;
  function snapshot() {
    try {
      const value = options.getSession();
      if (
        !value ||
        typeof value.subjectId !== "string" ||
        !value.subjectId.trim() ||
        typeof value.accessToken !== "string" ||
        !/^[\x21-\x7e]+$/.test(value.accessToken) ||
        !Array.isArray(value.permissions) ||
        !value.permissions.every(
          (name) => typeof name === "string" && permissionPattern.test(name),
        ) ||
        typeof value.dataScopes?.allRooms !== "boolean" ||
        !Array.isArray(value.dataScopes.roomIds) ||
        !value.dataScopes.roomIds.every(validId)
      )
        return null;
      return {
        subjectId: value.subjectId,
        accessToken: value.accessToken,
        permissions: [...new Set(value.permissions)].sort(),
        dataScopes: {
          allRooms: value.dataScopes.allRooms,
          roomIds: [...new Set(value.dataScopes.roomIds)].sort(),
        },
      };
    } catch {
      return null;
    }
  }
  function context() {
    const value = snapshot(),
      key = JSON.stringify(value);
    if (key !== previous) {
      previous = key;
      version++;
    }
    return { value, version };
  }
  function allowed(
    value: ReturnType<typeof snapshot>,
    capability: Capability,
  ): boolean {
    return (
      !!value &&
      value.permissions.includes(permissions.read) &&
      (capability === "read" ||
        value.permissions.includes(permissions.manage)) &&
      (capability !== "createRooms" ||
        (value.permissions.includes(permissions.createRooms) &&
          value.dataScopes.allRooms))
    );
  }
  async function call<T>(
    capability: Capability,
    write: boolean,
    operation: (gateway: ResourceGateway) => Promise<T>,
  ): Promise<T> {
    const before = context();
    // Preflight is outside the fetch adapter: a denied, unsent write is definite.
    if (!allowed(before.value, capability))
      throw new ResourceMessage(
        "当前登录或资源权限不足，请重新确认会话。",
        false,
      );
    const owner = before.value!;
    const transport: typeof fetch = (input, init) => {
      const headers = new Headers(init?.headers);
      headers.set("Accept", "application/json");
      headers.set("Authorization", `Bearer ${owner.accessToken}`);
      return request(input, { ...init, headers });
    };
    const result = await operation(createHttpResourceGateway(transport));
    const after = context();
    if (before.version !== after.version || !allowed(after.value, capability))
      throw new ResourceMessage(
        write
          ? "会话或权限已变化，请使用原账号核对原资源操作。"
          : "会话或权限已变化，请重新查询资源。",
        write,
      );
    return result;
  }
  const gateway: ResourceGateway = {
    mode: "live",
    listRooms: (query, signal) =>
      call("read", false, (g) => g.listRooms(query, signal)),
    listSeats: (id, query, signal) =>
      call("read", false, (g) => g.listSeats(id, query, signal)),
    createRoom: (draft) =>
      call("createRooms", true, (g) => g.createRoom(draft)),
    updateRoom: (id, draft, revision) =>
      call("manage", true, (g) => g.updateRoom(id, draft, revision)),
    createSeat: (id, draft) =>
      call("manage", true, (g) => g.createSeat(id, draft)),
    updateSeat: (id, draft, revision) =>
      call("manage", true, (g) => g.updateSeat(id, draft, revision)),
  };
  const session = createResourceSession(gateway, {
    currentActorId: () => {
      const value = context().value;
      return allowed(value, "read") ? value!.subjectId : null;
    },
    canManage: () => allowed(context().value, "manage"),
    canCreateRooms: () => allowed(context().value, "createRooms"),
    contextVersion: () => context().version,
  });
  return { gateway, session };
}
