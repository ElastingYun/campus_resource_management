import {
  M3ClientError,
  isObject,
  isUuid,
  parsePage,
  parseTicket,
  prepareDraft,
  type M3Session,
  type ReportDraft,
  type RepairTicket,
} from "./models";

export interface M3AccessOptions {
  getSession: () => M3Session | null;
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
  createKey?: () => string;
  /** Host must clear only the matching session. A stale 401 never calls this. */
  onUnauthorized?: (subjectId: string, accessToken: string) => void;
}

export interface PendingReport {
  readonly subjectId: string;
  readonly key: string;
  readonly draft: Readonly<ReportDraft>;
  readonly phase: "sending" | "unknown";
}

/** Keep this instance outside page mounts. It never uses browser storage. */
export function createM3TicketAccess(options: M3AccessOptions) {
  const timeoutMs = options.timeoutMs ?? 8000;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000)
    throw new M3ClientError("configuration");
  const pending = new Map<string, PendingReport>();
  const busy = new Set<string>();
  const path = "/api/v1/m3/tickets";

  function session(): Readonly<M3Session> {
    let value: M3Session | null;
    try {
      value = options.getSession();
    } catch {
      throw new M3ClientError("configuration");
    }
    if (value === null) throw new M3ClientError("session");
    if (
      !isObject(value) ||
      !isUuid(value.subjectId) ||
      typeof value.accessToken !== "string" ||
      !/^[!-~]{1,4096}$/.test(value.accessToken) ||
      typeof value.canCreate !== "boolean" ||
      typeof value.canReadOwn !== "boolean"
    )
      throw new M3ClientError("configuration");
    return Object.freeze({
      subjectId: value.subjectId,
      accessToken: value.accessToken,
      canCreate: value.canCreate,
      canReadOwn: value.canReadOwn,
    });
  }

  function current(snapshot: Readonly<M3Session>): boolean {
    try {
      const value = session();
      return (
        value.subjectId === snapshot.subjectId &&
        value.accessToken === snapshot.accessToken &&
        value.canCreate === snapshot.canCreate &&
        value.canReadOwn === snapshot.canReadOwn
      );
    } catch {
      return false;
    }
  }

  async function request<T>(
    snapshot: Readonly<M3Session>,
    url: string,
    writing: boolean,
    parse: (value: unknown) => T,
    report?: PendingReport,
  ): Promise<T> {
    // Key factories/host callbacks may change the session before dispatch.
    if (!current(snapshot)) throw new M3ClientError("session_changed");
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        reject(new M3ClientError("timeout", writing));
      }, timeoutMs);
    });
    const ensureCurrent = () => {
      if (controller.signal.aborted)
        throw new M3ClientError("timeout", writing);
      if (!current(snapshot))
        throw new M3ClientError("session_changed", writing);
    };
    const perform = async () => {
      const headers = new Headers({
        Accept: "application/json",
        Authorization: `Bearer ${snapshot.accessToken}`,
      });
      if (report) {
        headers.set("Content-Type", "application/json");
        headers.set("Idempotency-Key", report.key);
      }
      const response = await (options.fetch ?? globalThis.fetch)(url, {
        method: writing ? "POST" : "GET",
        headers,
        body: report
          ? JSON.stringify({
              room_id: report.draft.roomId,
              description: report.draft.description,
            })
          : undefined,
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        signal: controller.signal,
      });
      ensureCurrent();
      if (!response.ok) {
        let code: string | undefined;
        try {
          const value: unknown = await response.json();
          const detail = isObject(value)
            ? isObject(value.detail)
              ? value.detail
              : isObject(value.error)
                ? value.error
                : null
            : null;
          if (
            detail &&
            typeof detail.code === "string" &&
            /^[A-Za-z0-9_]{1,80}$/.test(detail.code)
          )
            code = detail.code;
        } catch {
          // Only the HTTP status and bounded code survive; no raw server text.
        }
        ensureCurrent();
        if (response.status === 401) {
          try {
            options.onUnauthorized?.(snapshot.subjectId, snapshot.accessToken);
          } catch {
            throw new M3ClientError("configuration");
          }
        }
        throw new M3ClientError(
          "http",
          writing && (response.status >= 500 || response.status === 408),
          response.status,
          code,
        );
      }
      if (
        (writing && response.status !== 200 && response.status !== 201) ||
        (!writing && response.status !== 200)
      )
        throw new M3ClientError("invalid_response", writing, response.status);
      let value: unknown;
      try { value = await response.json(); } catch {
        ensureCurrent();
        throw new M3ClientError("invalid_response", writing, response.status);
      }
      ensureCurrent();
      try {
        return parse(value);
      } catch {
        throw new M3ClientError("invalid_response", writing, response.status);
      }
    };
    try {
      return await Promise.race([perform(), deadline]);
    } catch (cause) {
      if (cause instanceof M3ClientError) throw cause;
      throw new M3ClientError("network", writing);
    } finally {
      clearTimeout(timer);
    }
  }

  async function send(
    snapshot: Readonly<M3Session>,
    report: PendingReport,
    recovering: boolean,
  ): Promise<RepairTicket> {
    busy.add(snapshot.subjectId);
    pending.set(snapshot.subjectId, { ...report, phase: "sending" });
    try {
      const ticket = await request(
        snapshot,
        path,
        true,
        (value) => {
          const result = parseTicket(value);
          if (
            result.roomId !== report.draft.roomId ||
            result.description !== report.draft.description
          )
            throw new M3ClientError("invalid_response");
          return result;
        },
        report,
      );
      pending.delete(snapshot.subjectId);
      return ticket;
    } catch (cause) {
      if (
        recovering ||
        !(cause instanceof M3ClientError) ||
        cause.mayHaveWritten
      )
        pending.set(snapshot.subjectId, { ...report, phase: "unknown" });
      else pending.delete(snapshot.subjectId);
      throw cause;
    } finally {
      busy.delete(snapshot.subjectId);
    }
  }

  return {
    async listOwn(limit = 20, offset = 0) {
      const snapshot = session();
      if (!snapshot.canReadOwn) throw new M3ClientError("permission");
      if (
        !Number.isSafeInteger(limit) ||
        limit < 1 ||
        limit > 100 ||
        !Number.isSafeInteger(offset) ||
        offset < 0
      )
        throw new M3ClientError("validation");
      return request(
        snapshot,
        `${path}?limit=${limit}&offset=${offset}`,
        false,
        (value) => parsePage(value, limit, offset),
      );
    },
    async getOwn(id: string) {
      const snapshot = session();
      if (!snapshot.canReadOwn) throw new M3ClientError("permission");
      if (!isUuid(id)) throw new M3ClientError("validation");
      return request(snapshot, `${path}/${id.toLowerCase()}`, false, (value) => {
        const ticket = parseTicket(value);
        if (ticket.id !== id.toLowerCase())
          throw new M3ClientError("invalid_response");
        return ticket;
      });
    },
    async submit(draft: ReportDraft) {
      const snapshot = session();
      if (!snapshot.canCreate) throw new M3ClientError("permission");
      if (busy.has(snapshot.subjectId)) throw new M3ClientError("busy");
      if (pending.has(snapshot.subjectId))
        throw new M3ClientError("recovery_required");
      const prepared = prepareDraft(draft);
      let key: string;
      try {
        key = (options.createKey ?? (() => crypto.randomUUID()))();
      } catch {
        throw new M3ClientError("configuration");
      }
      if (typeof key !== "string" || !/^[!-~]{1,128}$/.test(key))
        throw new M3ClientError("configuration");
      return send(
        snapshot,
        { subjectId: snapshot.subjectId, key, draft: prepared, phase: "sending" },
        false,
      );
    },
    async recover() {
      const snapshot = session();
      if (!snapshot.canCreate) throw new M3ClientError("permission");
      if (busy.has(snapshot.subjectId)) throw new M3ClientError("busy");
      const report = pending.get(snapshot.subjectId);
      if (!report) throw new M3ClientError("validation");
      return send(snapshot, report, true);
    },
    getPending(): PendingReport | null {
      let subject: string;
      try {
        subject = session().subjectId;
      } catch {
        return null;
      }
      const report = pending.get(subject);
      return report
        ? Object.freeze({ ...report, draft: Object.freeze({ ...report.draft }) })
        : null;
    },
    hasUnresolvedReports: () => pending.size > 0,
  };
}

export type M3TicketAccess = ReturnType<typeof createM3TicketAccess>;
