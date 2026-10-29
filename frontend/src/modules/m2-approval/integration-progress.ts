import { GatewayMessage } from "./models";
import type { IntegrationProgress } from "./models";
import { isObject, isUuid } from "./c-session";

const statuses = [
  "NONE",
  "APPLY_PENDING",
  "APPLY_UNKNOWN",
  "APPLIED",
  "APPLY_CONFLICT",
  "RELEASE_PENDING",
  "RELEASE_UNKNOWN",
  "RELEASED",
];
const states = [
  "PENDING",
  "RUNNING",
  "UNKNOWN",
  "DONE",
  "CONFLICT",
  "ATTENTION",
];
const integer = (value: unknown, minimum: number): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
const invalid = () =>
  new GatewayMessage("占用处理进度响应异常，请重新载入或联系维护者核查。");
export function parseIntegrationProgress(value: unknown): IntegrationProgress {
  if (
    !isObject(value) ||
    !isUuid(value.application_id) ||
    !integer(value.version, 1) ||
    !integer(value.generation, 0) ||
    typeof value.integration_status !== "string" ||
    !statuses.includes(value.integration_status) ||
    typeof value.effective !== "boolean" ||
    (value.effective && value.integration_status !== "APPLIED") ||
    !Array.isArray(value.operations)
  )
    throw invalid();
  const generation = value.generation;
  const seen = new Set<string>();
  const operations = value.operations.map((operation) => {
    if (
      !isObject(operation) ||
      !isUuid(operation.id) ||
      seen.has(operation.id.toLowerCase()) ||
      !integer(operation.generation, 1) ||
      operation.generation > generation ||
      typeof operation.kind !== "string" ||
      !["APPLY", "RELEASE"].includes(operation.kind) ||
      typeof operation.state !== "string" ||
      !states.includes(operation.state) ||
      !integer(operation.attempts, 0) ||
      !(
        operation.error_code === null ||
        (typeof operation.error_code === "string" &&
          /^[A-Z0-9_]{1,64}$/.test(operation.error_code))
      )
    )
      throw invalid();
    seen.add(operation.id.toLowerCase());
    return {
      id: operation.id,
      generation: operation.generation,
      kind: operation.kind as "APPLY" | "RELEASE",
      state:
        operation.state as IntegrationProgress["operations"][number]["state"],
      attempts: operation.attempts,
      errorCode: operation.error_code as string | null,
    };
  });
  return {
    applicationId: value.application_id,
    version: value.version,
    generation: value.generation,
    integrationStatus: value.integration_status,
    effective: value.effective,
    operations,
  };
}
