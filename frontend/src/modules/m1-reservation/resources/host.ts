import type { CSession } from "../../m2-approval/c-session";
import { createAuthenticatedResourceAccess } from "./access";
import type { ResourcePermissionMapping } from "./access";

/** Public build configuration only; it grants no server-side roles or permissions. */
export function parseResourcePermissions(
  value: unknown,
): ResourcePermissionMapping | null {
  if (typeof value !== "string" || value.length > 1024) return null;
  try {
    const data: unknown = JSON.parse(value);
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const mapping = data as Record<string, unknown>;
    if (Object.keys(mapping).sort().join(",") !== "create_rooms,manage,read")
      return null;
    const names = [mapping.read, mapping.manage, mapping.create_rooms];
    if (
      !names.every(
        (name) =>
          typeof name === "string" &&
          /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(name),
      )
    )
      return null;
    return {
      read: mapping.read as string,
      manage: mapping.manage as string,
      createRooms: mapping.create_rooms as string,
    };
  } catch {
    return null;
  }
}

/** App owns this once, outside route components, sharing D's existing CSession. */
export function createCResourceAccess(
  c: CSession,
  permissions: ResourcePermissionMapping,
  request: typeof fetch = globalThis.fetch.bind(globalThis),
) {
  return createAuthenticatedResourceAccess({
    getSession: () => {
      const current = c.state.value;
      return current
        ? {
            subjectId: current.identity.subject_id,
            accessToken: current.accessToken,
            permissions: current.identity.permissions,
            dataScopes: {
              allRooms: current.identity.data_scopes.all_rooms,
              roomIds: current.identity.data_scopes.room_ids,
            },
          }
        : null;
    },
    permissions,
    request: async (input, init) => {
      const response = await request(input, init);
      if (response.status === 401) {
        const authorization = new Headers(init?.headers).get("Authorization");
        if (authorization?.startsWith("Bearer "))
          c.invalidate(authorization.slice(7));
      }
      return response;
    },
  });
}
