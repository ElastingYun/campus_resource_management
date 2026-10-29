import { afterEach, describe, expect, it, vi } from "vitest";
import { M2HttpError, requestJson } from "./http";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("M2 JSON transport boundary without assumed business routes", () => {
  it("serializes JSON once and restricts credentials and redirects to the same origin", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ syntheticId: "fixture-1" }), {
        status: 201,
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const result = await requestJson("/test-contract-path", {
      method: "POST",
      body: { purpose: "合成请求" },
    });
    expect(result).toEqual({ syntheticId: "fixture-1" });
    expect(fetch).toHaveBeenCalledTimes(1);
    const [path, options] = fetch.mock.calls[0]!;
    expect(path).toBe("/test-contract-path");
    expect(options.credentials).toBe("same-origin");
    expect(options.redirect).toBe("error");
    expect(options.headers.get("Content-Type")).toBe("application/json");
    expect(options.body).toBe(JSON.stringify({ purpose: "合成请求" }));
  });

  it.each([
    "https://outside.invalid/path",
    "//outside.invalid/path",
    "/\\outside.invalid/path",
    "relative-path",
    "/path#fragment",
  ])("rejects unsafe or ambiguous path %s before fetch", async (path) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(requestJson(path)).rejects.toMatchObject({
      kind: "configuration",
      delivery: "not_sent",
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([401, 403, 409, 422])(
    "preserves HTTP %s without exposing raw error details",
    async (status) => {
      const fetch = vi
        .fn()
        .mockResolvedValue(
          new Response("private-debug-token-do-not-show", { status }),
        );
      vi.stubGlobal("fetch", fetch);
      const error = await requestJson("/test-contract-path", {
        method: "POST",
      }).catch((cause) => cause);
      expect(error).toBeInstanceOf(M2HttpError);
      expect(error).toMatchObject({
        kind: "http",
        status,
        delivery: "responded",
      });
      expect(String(error)).not.toContain("private-debug-token");
      expect(fetch).toHaveBeenCalledTimes(1);
    },
  );

  it("treats a server error after a write as unknown, with no automatic retry", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    await expect(
      requestJson("/test-contract-path", { method: "POST" }),
    ).rejects.toMatchObject({ kind: "http", status: 503, delivery: "unknown" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("does not report failure-to-save as certain after a network error on write", async () => {
    const fetch = vi
      .fn()
      .mockRejectedValue(new Error("internal host and secret"));
    vi.stubGlobal("fetch", fetch);
    const error = await requestJson("/test-contract-path", {
      method: "POST",
    }).catch((cause) => cause);
    expect(error).toMatchObject({ kind: "network", delivery: "unknown" });
    if (!(error instanceof M2HttpError)) throw error;
    expect(error.message).toContain("先查询结果");
    expect(error.message).not.toContain("secret");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("aborts a timed-out write once and preserves unknown outcome", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(
      (_path, options) =>
        new Promise((_resolve, reject) => {
          options.signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );
    vi.stubGlobal("fetch", fetch);
    const pending = requestJson("/test-contract-path", {
      method: "POST",
      timeoutMs: 20,
    });
    const assertion = expect(pending).rejects.toMatchObject({
      kind: "timeout",
      delivery: "unknown",
    });
    await vi.advanceTimersByTimeAsync(21);
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not send a pre-cancelled write", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    controller.abort();
    await expect(
      requestJson("/test-contract-path", {
        method: "POST",
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({ kind: "aborted", delivery: "not_sent" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not treat an invalid successful write response as confirmed application success", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("<html>gateway error</html>", { status: 200 }),
        ),
    );
    await expect(
      requestJson("/test-contract-path", { method: "POST" }),
    ).rejects.toMatchObject({ kind: "invalid_response", delivery: "unknown" });
  });

  it("supports empty 204 responses without inventing a business identifier", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );
    await expect(
      requestJson("/test-contract-path", { method: "DELETE" }),
    ).resolves.toBeUndefined();
  });

  it("rejects invalid timeout and unserializable payload before sending", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(
      requestJson("/test-contract-path", { timeoutMs: 0 }),
    ).rejects.toMatchObject({ kind: "configuration", delivery: "not_sent" });
    await expect(
      requestJson("/test-contract-path", { method: "POST", body: 1n }),
    ).rejects.toMatchObject({ kind: "configuration", delivery: "not_sent" });
    expect(fetch).not.toHaveBeenCalled();
  });
  it("distinguishes uncertain read delivery from a potentially completed write", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const error = await requestJson("/test-contract-path").catch(
      (cause) => cause,
    );
    if (!(error instanceof M2HttpError)) throw error;
    expect(error.delivery).toBe("unknown");
    expect(error.mayHaveWritten).toBe(false);
    expect(error.message).not.toContain("重复提交");
  });
  it("keeps the deadline active while reading a partial response body", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn((_path, options) => {
      let streamController!: ReadableStreamDefaultController<Uint8Array>;
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller;
          controller.enqueue(new TextEncoder().encode('{"partial":'));
        },
      });
      options.signal.addEventListener("abort", () =>
        streamController.error(new DOMException("Aborted", "AbortError")),
      );
      return Promise.resolve(new Response(stream, { status: 200 }));
    });
    vi.stubGlobal("fetch", fetch);
    const pending = requestJson("/test-contract-path", {
      method: "POST",
      timeoutMs: 20,
    });
    const assertion = expect(pending).rejects.toMatchObject({
      kind: "timeout",
      delivery: "unknown",
      mayHaveWritten: true,
    });
    await vi.advanceTimersByTimeAsync(21);
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});
