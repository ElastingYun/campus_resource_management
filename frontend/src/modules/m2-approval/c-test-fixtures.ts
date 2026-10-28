import type { CApplication } from "./c-gateway";
import type { CIdentity } from "./c-session";
export const actor = "00000000-0000-4000-8000-000000000001";
export const otherActor = "00000000-0000-4000-8000-000000000002";
export const applicationId = "00000000-0000-4000-8000-000000000010";
export const identity = (subject = actor): CIdentity => ({
  subject_id: subject,
  department_id: "synthetic-department",
  roles: ["synthetic-role"],
  permissions: ["m2.submit", "m2.review"],
  data_scopes: { room_ids: ["9007199254740993"], all_rooms: false },
});
export const application = (
  changes: Partial<CApplication> = {},
): CApplication => ({
  id: applicationId,
  applicant_id: actor,
  room_id: "9007199254740993",
  purpose: "合成接口用例",
  starts_at: "2030-01-02T01:00:00Z",
  ends_at: "2030-01-02T03:00:00Z",
  review_status: "REVIEWING",
  integration_status: "NONE",
  step_index: 0,
  step_count: 2,
  deadline: "2030-01-01T01:10:00Z",
  version: 1,
  revoked: false,
  effective: false,
  created_at: "2030-01-01T01:00:00Z",
  updated_at: "2030-01-01T01:00:00Z",
  ...changes,
});
export const room = {
  id: "9007199254740993",
  name: "合成教室",
  location: "合成测试楼",
};
export const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
