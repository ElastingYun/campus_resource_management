/** Transport only. Routes, authentication and payload mapping require the owners' contract. */
export type HttpMethod = "GET" | "HEAD" | "POST" | "PUT" | "PATCH" | "DELETE";
export type Delivery = "not_sent" | "responded" | "unknown";
export type FailureKind =
  | "configuration"
  | "http"
  | "network"
  | "timeout"
  | "aborted"
  | "invalid_response";
export class M2HttpError extends Error {
  constructor(
    readonly kind: FailureKind,
    readonly delivery: Delivery,
    readonly status?: number,
    readonly mayHaveWritten = false,
  ) {
    super(
      mayHaveWritten
        ? "请求结果尚不确定，请先查询结果，避免重复提交。"
        : "请求未能完成，请检查服务状态或权限后重试。",
    );
    this.name = "M2HttpError";
  }
}
export interface JsonRequestOptions {
  method?: HttpMethod;
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export async function requestJson(
  path: string,
  options: JsonRequestOptions = {},
): Promise<unknown> {
  const method = options.method ?? "GET";
  const writing = method !== "GET" && method !== "HEAD";
  const timeoutMs = options.timeoutMs ?? 8000;
  let normalizedPath: string;
  let headers: Headers;
  let body: string | undefined;
  try {
    const url = new URL(path, "https://frontend.invalid");
    if (
      !path.startsWith("/") ||
      path.startsWith("//") ||
      url.origin !== "https://frontend.invalid" ||
      url.hash
    ) {
      throw new Error("Only same-origin absolute paths are supported");
    }
    if (
      !Number.isFinite(timeoutMs) ||
      timeoutMs <= 0 ||
      timeoutMs > 2147483647 ||
      (!writing && options.body !== undefined)
    ) {
      throw new Error("Invalid request configuration");
    }
    normalizedPath = url.pathname + url.search;
    headers = new Headers(options.headers);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    if (options.body !== undefined) {
      body = JSON.stringify(options.body);
      if (body === undefined)
        throw new Error("Payload cannot be represented as JSON");
      if (!headers.has("Content-Type"))
        headers.set("Content-Type", "application/json");
    }
  } catch {
    throw new M2HttpError("configuration", "not_sent");
  }
  if (options.signal?.aborted) throw new M2HttpError("aborted", "not_sent");

  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  options.signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetch(normalizedPath, {
      method,
      headers,
      body,
      signal: controller.signal,
      credentials: "same-origin",
      redirect: "error",
    });
    if (!response.ok) {
      const uncertain =
        writing && (response.status >= 500 || response.status === 408);
      // Preserve status, not raw server error bodies; the approved adapter owns field mapping.
      throw new M2HttpError(
        "http",
        uncertain ? "unknown" : "responded",
        response.status,
        uncertain,
      );
    }
    if (method === "HEAD" || response.status === 204 || response.status === 205)
      return undefined;
    try {
      return await response.json();
    } catch (cause) {
      if (controller.signal.aborted) throw cause;
      throw new M2HttpError(
        "invalid_response",
        writing ? "unknown" : "responded",
        response.status,
        writing,
      );
    }
  } catch (cause) {
    if (cause instanceof M2HttpError) throw cause;
    const kind = timedOut
      ? "timeout"
      : controller.signal.aborted
        ? "aborted"
        : "network";
    throw new M2HttpError(kind, "unknown", undefined, writing);
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", cancel);
  }
}
