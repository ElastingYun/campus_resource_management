import { afterEach, describe, expect, it, vi } from "vitest";
import { parseIntegrationProgress } from "./integration-progress";
import { createCGateway } from "./c-gateway";
import { createCSession } from "./c-session";
import {
  applicationId,
  identity,
  integrationProgress,
  json,
} from "./c-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
const operation = () => integrationProgress().operations[0]!;

describe("C integration progress boundary", () => {
  it("parses an empty intent and strips private fields", () => {
    expect(
      parseIntegrationProgress(
        integrationProgress({
          generation: 0,
          integration_status: "NONE",
          operations: [],
          payload: "must not escape",
        }),
      ),
    ).toEqual({
      applicationId,
      version: 1,
      generation: 0,
      integrationStatus: "NONE",
      effective: false,
      operations: [],
    });
    const value = integrationProgress();
    expect(
      parseIntegrationProgress({
        ...value,
        operations: [{ ...operation(), payload: "secret" }],
      }).operations[0],
    ).not.toHaveProperty("payload");
  });
  it.each([
    { application_id: "not-uuid" },
    { version: 0 },
    { version: 1.5 },
    { generation: -1 },
    { integration_status: "FUTURE" },
    { effective: "true" },
    { effective: true },
    { operations: {} },
    { operations: [{ ...operation(), generation: 2 }] },
    { operations: [{ ...operation(), generation: -1 }] },
    { operations: [{ ...operation(), attempts: -1 }] },
    { operations: [{ ...operation(), attempts: Number.MAX_SAFE_INTEGER + 1 }] },
    { operations: [{ ...operation(), kind: ["APPLY"] }] },
    { operations: [{ ...operation(), state: ["DONE"] }] },
    { operations: [{ ...operation(), state: "FUTURE" }] },
    {
      operations: [
        { ...operation(), error_code: "<script>private error</script>" },
      ],
    },
    { operations: [operation(), operation()] },
  ])("rejects an invalid progress response %j", (changes) => {
    expect(() =>
      parseIntegrationProgress(integrationProgress(changes)),
    ).toThrow("响应异常");
  });
  it("retains historical generations and unknown safe machine codes without inferring effectiveness", () => {
    const data = integrationProgress({
      generation: 2,
      integration_status: "RELEASE_UNKNOWN",
      operations: [
        { ...operation(), state: "DONE", error_code: null },
        {
          ...operation(),
          id: "00000000-0000-4000-8000-000000000021",
          generation: 2,
          kind: "RELEASE",
          state: "ATTENTION",
          error_code: "FUTURE_CODE",
        },
      ],
    });
    const result = parseIntegrationProgress(data);
    expect(result.operations).toHaveLength(2);
    expect(result.operations[0]?.generation).toBe(1);
    expect(result.operations[1]?.state).toBe("ATTENTION");
    expect(result.effective).toBe(false);
  });
  it("performs a fresh authorized GET every time even when version does not change", async () => {
    const session = createCSession();
    session.state.value = {
      accessToken: "synthetic-progress-token",
      expiresAt: "2030-01-01Z",
      identity: identity(),
    };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(integrationProgress()))
      .mockResolvedValueOnce(
        json(
          integrationProgress({
            operations: [
              {
                ...operation(),
                state: "ATTENTION",
                attempts: 3,
                error_code: "RETRY_LIMIT",
              },
            ],
          }),
        ),
      );
    vi.stubGlobal("fetch", fetch);
    const gateway = createCGateway(session);
    const first = await gateway.integration!(applicationId);
    const second = await gateway.integration!(applicationId);
    expect(first.version).toBe(second.version);
    expect(second.operations[0]?.state).toBe("ATTENTION");
    expect(fetch).toHaveBeenCalledTimes(2);
    for (const [path, options] of fetch.mock.calls) {
      expect(path).toBe(`/api/v1/m2/applications/${applicationId}/integration`);
      expect(options.method).toBe("GET");
      expect(options.cache).toBe("no-store");
      expect(new Headers(options.headers).get("Authorization")).toBe(
        "Bearer synthetic-progress-token",
      );
      expect(new Headers(options.headers).get("Idempotency-Key")).toBeNull();
    }
  });
  it("rejects a different application's response", async () => {
    const session = createCSession();
    session.state.value = {
      accessToken: "synthetic-token",
      expiresAt: "2030-01-01Z",
      identity: identity(),
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          json(
            integrationProgress({
              application_id: "00000000-0000-4000-8000-000000000099",
            }),
          ),
        ),
    );
    await expect(
      createCGateway(session).integration!(applicationId),
    ).rejects.toThrow("当前申请不一致");
  });
  it("invalidates the corresponding session on 401 without displaying the server error body", async () => {
    const session = createCSession();
    session.state.value = {
      accessToken: "synthetic-token",
      expiresAt: "2030-01-01Z",
      identity: identity(),
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          json(
            {
              error: {
                code: "INVALID_SESSION",
                message: "private service diagnostic",
              },
            },
            401,
          ),
        ),
    );
    await expect(
      createCGateway(session).integration!(applicationId),
    ).rejects.toThrow("会话已失效");
    expect(session.state.value).toBeNull();
  });
});
