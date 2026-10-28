import { afterAll, expect, test } from "vitest";
import { env } from "node:process";
import { createCSession, isObject } from "../src/modules/m2-approval/c-session";
import { createCGateway } from "../src/modules/m2-approval/c-gateway";
const origin = env.CAMPUS_M2_LIVE_ORIGIN;
if (env.CI === "true" && !origin)
  throw new Error(
    "CI requires the real C service origin; do not silently skip",
  );
const nativeFetch = globalThis.fetch.bind(globalThis);
afterAll(() => {
  globalThis.fetch = nativeFetch;
});

test.skipIf(!origin)(
  "real C-v1 HTTP and PostgreSQL: authentication, response-loss recovery, decisions and persistent query",
  async () => {
    const password = env.CAMPUS_BOOTSTRAP_PASSWORD;
    const resourceOrigin = env.CAMPUS_M2_RESOURCE_FIXTURE_ORIGIN;
    const resourceToken = env.CAMPUS_RESOURCES_SERVICE_TOKEN;
    if (!password || !resourceOrigin || !resourceToken)
      throw new Error("Explicit synthetic CI configuration is required");
    let dropFirstSubmission = true;
    const discardedResponses: { status: number; id: unknown }[] = [];
    const submissions: { key: string | null; body: string }[] = [];
    globalThis.fetch = async (input, init) => {
      const path = String(input);
      const response = await nativeFetch(new URL(path, origin), init);
      if (path === "/api/v1/m2/applications" && init?.method === "POST") {
        submissions.push({
          key: new Headers(init.headers).get("Idempotency-Key"),
          body: String(init.body),
        });
        if (dropFirstSubmission) {
          dropFirstSubmission = false;
          expect(response.status).toBe(201);
          await response.arrayBuffer();
          throw new TypeError(
            "Synthetic client-side response loss after real C commit",
          );
        }
      }
      return response;
    };
    const student = createCSession();
    await student.login("m2-live-student", password);
    expect(student.state.value?.identity.permissions).toContain("m2.submit");
    const productionDefault = createCGateway(student);
    const notIntegrated = await productionDefault.load();
    expect(notIntegrated.canSubmit).toBe(false);
    expect(notIntegrated.roomWarning).toBeTruthy();

    // Explicit test-only room directory. This does not assert real B authorization or eligibility.
    const loadRooms = async () => {
      const response = await nativeFetch(
        new URL("/api/v1/resources/rooms", resourceOrigin),
        { headers: { Authorization: `Bearer ${resourceToken}` } },
      );
      expect(response.status).toBe(200);
      const data = (await response.json()) as {
        items: { id: string; name: string; location: string }[];
      };
      return data.items.map((room) => ({
        id: room.id,
        name: room.name,
        location: room.location,
      }));
    };
    const gateway = createCGateway(student, { loadRooms });
    expect((await gateway.load()).canSubmit).toBe(true);
    const starts = new Date(Date.now() + 86400000),
      ends = new Date(starts.getTime() + 3600000);
    const draft = {
      roomId: "1",
      purpose: `Synthetic D-C network ${crypto.randomUUID()}`,
      startsAt: starts.toISOString(),
      endsAt: ends.toISOString(),
    };
    await expect(gateway.submit(draft)).rejects.toThrow("结果尚未确认");
    expect(submissions).toHaveLength(1);
    expect(discardedResponses[0]?.status).toBe(201);
    expect(typeof discardedResponses[0]?.id).toBe("string");
    await expect(gateway.submit(draft)).rejects.toThrow("先恢复结果");
    const record = await gateway.recover!();
    expect(submissions).toHaveLength(2);
    expect(record.id).toBe(discardedResponses[0]?.id);
    expect(submissions[1]).toEqual(submissions[0]);
    expect(record.effective).toBe(false);
    expect(gateway.pending?.()).toBeUndefined();
    expect(
      (await gateway.load()).applications.filter(
        (item) => item.id === record.id,
      ),
    ).toHaveLength(1);
    const studentDetail = await gateway.detail!(record.id);
    expect(studentDetail.allowedActions).toEqual([]);
    await expect(
      gateway.decide!(
        record.id,
        "APPROVE",
        "Synthetic forbidden action",
        studentDetail.version,
      ),
    ).rejects.toThrow("无权");

    for (const username of ["m2-live-reviewer-one", "m2-live-reviewer-two"]) {
      const session = createCSession();
      await session.login(username, password);
      const reviewer = createCGateway(session);
      const detail = await reviewer.detail!(record.id);
      expect(detail.allowedActions).toContain("APPROVE");
      await reviewer.decide!(
        record.id,
        "APPROVE",
        "Synthetic network acceptance",
        detail.version,
      );
      await session.logout();
    }
    const final = await gateway.detail!(record.id);
    expect(final.reviewLabel).toBe("审批已通过");
    expect(final.effective).toBe(false);
    expect(final.integrationLabel).toBe("正在确认占用");
    expect(final.history).toHaveLength(2);
    const oldToken = student.state.value!.accessToken;
    await student.logout();
    const revoked = await nativeFetch(new URL("/api/v1/auth/me", origin), {
      headers: { Authorization: `Bearer ${oldToken}` },
    });
    expect(revoked.status).toBe(401);
    await student.login("m2-live-student", password);
    const reloaded = await createCGateway(student).load();
    expect(
      reloaded.applications.find((item) => item.id === record.id)?.purpose,
    ).toBe(draft.purpose);
    expect(
      reloaded.applications.find((item) => item.id === record.id)?.effective,
    ).toBe(false);
    await student.logout();
  },
);
