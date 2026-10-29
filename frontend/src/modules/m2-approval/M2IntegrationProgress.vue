<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { GatewayMessage } from "./models";
import type { ApplicationDetails, IntegrationProgress } from "./models";
const props = defineProps<{
  application: ApplicationDetails;
  loadProgress: (id: string) => Promise<IntegrationProgress>;
}>();
const progress = ref<IntegrationProgress>(),
  loading = ref(false),
  error = ref("");
let request = 0;
const states = {
  PENDING: "等待后台处理",
  RUNNING: "后台处理中",
  UNKNOWN: "结果尚未确认",
  DONE: "该操作已确认",
  CONFLICT: "已确认占用冲突",
  ATTENTION: "自动重试已停止，需人工核查",
};
const diagnostic = (code: string | null) =>
  code === "RETRY_LIMIT"
    ? "已达到自动重试上限"
    : code === "REMOTE_UNCONFIRMED"
      ? "远端结果尚未确认"
      : code === null
        ? "暂无诊断码"
        : "未识别的诊断码，请联系维护者核查";
const needsAttention = computed(() =>
  progress.value?.operations.some(
    (operation) =>
      operation.generation === progress.value?.generation &&
      operation.state === "ATTENTION",
  ),
);
async function refresh() {
  const sequence = ++request,
    application = props.application;
  progress.value = undefined;
  loading.value = true;
  error.value = "";
  try {
    const value = await props.loadProgress(application.id);
    if (sequence !== request) return;
    if (
      value.applicationId !== application.id ||
      value.version !== application.version ||
      (application.integrationStatus !== undefined &&
        value.integrationStatus !== application.integrationStatus) ||
      (application.effective !== undefined &&
        value.effective !== application.effective)
    )
      throw new GatewayMessage(
        "申请与占用进度已发生变化，请重新载入申请后核对。",
      );
    progress.value = value;
  } catch (cause) {
    if (sequence === request)
      error.value =
        cause instanceof GatewayMessage
          ? cause.message
          : "暂时无法查询占用处理进度，请稍后刷新；当前未确认处理结果。";
  } finally {
    if (sequence === request) loading.value = false;
  }
}
watch(
  () => [
    props.application.id,
    props.application.version,
    props.application.integrationStatus,
    props.application.effective,
  ],
  refresh,
  { immediate: true },
);
onUnmounted(() => {
  request++;
});
</script>
<template>
  <section class="integration-progress" aria-label="占用处理进度">
    <div class="progress-heading">
      <h4>占用处理进度</h4>
      <button class="secondary" :disabled="loading" @click="refresh">
        刷新占用进度
      </button>
    </div>
    <p v-if="loading" role="status">正在查询占用处理进度…</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <template v-else-if="progress">
      <p class="muted">
        当前意图：第 {{ progress.generation }} 代 · 申请版本
        {{ progress.version }}
      </p>
      <p v-if="needsAttention" class="attention-note" role="note">
        当前操作的自动重试已停止，请联系维护者核查；刷新只查询进度。
      </p>
      <p v-if="!progress.operations.length">尚未产生占用或释放操作。</p>
      <ol v-else class="operation-list">
        <li v-for="operation in progress.operations" :key="operation.id">
          <strong
            >{{ operation.kind === "APPLY" ? "申请占用" : "释放本申请来源" }} ·
            {{
              operation.generation === progress.generation
                ? "当前意图"
                : "历史意图"
            }}（第 {{ operation.generation }} 代）</strong
          >
          <p>
            {{ states[operation.state] }} · 已领取 {{ operation.attempts }} 次
          </p>
          <p class="muted">{{ diagnostic(operation.errorCode) }}</p>
        </li>
      </ol>
      <p class="muted">
        领取次数不等于远端写入次数。历史操作完成不代表当前占用生效；释放只针对本申请来源。
      </p>
    </template>
  </section>
</template>
<style scoped>
.integration-progress {
  border-top: 1px solid #dce4e2;
  margin-top: 1.25rem;
  padding-top: 0.8rem;
}
.progress-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  flex-wrap: wrap;
}
h4 {
  margin: 0;
}
button {
  background: white;
  border: 1px solid #b8c8c3;
  border-radius: 7px;
  padding: 0.5rem 0.7rem;
  color: #28584d;
  cursor: pointer;
}
button:disabled {
  opacity: 0.6;
  cursor: wait;
}
.operation-list {
  padding-left: 1.3rem;
}
.operation-list li {
  margin: 0.9rem 0;
}
p {
  line-height: 1.6;
  margin: 0.35rem 0;
}
.muted {
  color: #536b64;
  font-size: 0.85rem;
}
.attention-note {
  background: #fff1d6;
  color: #76531e;
  padding: 0.7rem;
  border-radius: 7px;
}
</style>
