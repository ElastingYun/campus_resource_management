<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { reservationLabels } from "../booking/models";
import type { ReservationReceipt } from "../booking/models";
import type { CheckinSession } from "./checkin";
import { RecordsError } from "./models";
import type {
  RecordsGateway,
  RecordQuery,
  ReservationPage,
  Violation,
} from "./models";

const props = defineProps<{
  gateway: RecordsGateway;
  checkinSession?: CheckinSession;
  businessTimeZone?: string;
}>();
const session =
  props.checkinSession?.mode === props.gateway.mode
    ? props.checkinSession
    : undefined;
const actor = computed(() => {
  try {
    return props.gateway.currentActorId();
  } catch {
    return null;
  }
});
const flow = computed(() =>
  session?.currentActorId === actor.value ? (session?.current ?? null) : null,
);
const emit = defineEmits<{ pending: [value: boolean] }>();
watch(
  () => session?.pending ?? false,
  (value) => emit("pending", value),
  { immediate: true, flush: "sync" },
);
const query = reactive<RecordQuery>({ status: "", limit: 20, offset: 0 });
const page = ref<ReservationPage>();
const violations = ref<Violation[]>();
const loading = ref(false),
  loadingViolations = ref(false),
  error = ref(""),
  violationError = ref("");
const code = ref("");
let generation = 0,
  violationGeneration = 0;
let controller: AbortController | undefined,
  violationController: AbortController | undefined;
const enabled = computed(() => {
  if (
    props.gateway.mode === "unconfigured" ||
    !actor.value ||
    !props.businessTimeZone
  )
    return false;
  try {
    new Intl.DateTimeFormat("zh-CN", { timeZone: props.businessTimeZone });
    return true;
  } catch {
    return false;
  }
});
const canCheckin = computed(
  () =>
    enabled.value &&
    !!session?.current &&
    session.currentActorId === actor.value,
);
function message(cause: unknown) {
  return cause instanceof RecordsError
    ? cause.message
    : "服务暂时不可用，请稍后查询。";
}
function clear() {
  generation++;
  violationGeneration++;
  controller?.abort();
  violationController?.abort();
  page.value = undefined;
  violations.value = undefined;
  error.value = "";
  violationError.value = "";
  code.value = "";
  query.offset = 0;
  loading.value = false;
  loadingViolations.value = false;
}
async function load() {
  if (!enabled.value) return;
  const owner = actor.value!;
  const current = ++generation;
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = "";
  page.value = undefined;
  try {
    const result = await props.gateway.list(
      { ...query },
      owner,
      controller.signal,
    );
    if (current === generation && actor.value === owner) page.value = result;
  } catch (cause) {
    if (current === generation && actor.value === owner)
      error.value = message(cause);
  } finally {
    if (current === generation) loading.value = false;
  }
}
async function loadViolations() {
  if (!enabled.value) return;
  const owner = actor.value!,
    current = ++violationGeneration;
  violationController?.abort();
  violationController = new AbortController();
  loadingViolations.value = true;
  violationError.value = "";
  violations.value = undefined;
  try {
    const result = await props.gateway.violations(
      owner,
      violationController.signal,
    );
    if (current === violationGeneration && actor.value === owner)
      violations.value = result;
  } catch (cause) {
    if (current === violationGeneration && actor.value === owner)
      violationError.value = message(cause);
  } finally {
    if (current === violationGeneration) loadingViolations.value = false;
  }
}
function filter() {
  query.offset = 0;
  void load();
}
function move(delta: number) {
  query.offset = Math.max(0, query.offset + delta * query.limit);
  void load();
}
function select(item: ReservationReceipt) {
  code.value = "";
  flow.value?.open(item);
}
async function submit() {
  const entered = code.value;
  code.value = "";
  await flow.value?.submit(entered);
  if (flow.value?.state.phase === "resolved") void load();
}
async function recover() {
  await flow.value?.recover();
  if (flow.value?.state.phase === "resolved") void load();
}
function time(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: props.businessTimeZone!,
    dateStyle: "medium",
    timeStyle: "short",
    hourCycle: "h23",
  }).format(new Date(value));
}
watch(
  actor,
  () => {
    clear();
    if (enabled.value) {
      void load();
      void loadViolations();
    }
  },
  { flush: "sync" },
);
onMounted(() => {
  void load();
  void loadViolations();
});
onUnmounted(clear);
</script>

<template>
  <section class="my-reservations" aria-label="我的预约与签到">
    <header>
      <div>
        <h2>我的预约</h2>
        <p>查看本人记录，使用教室现场码签到。</p>
      </div>
      <button :disabled="!enabled || loading" @click="load">刷新预约</button>
    </header>
    <p v-if="gateway.mode === 'prototype'" class="notice">
      合成演示：仅显示本页演示预约，刷新后重置。演示签到码
      DEMO，不模拟真实签到时间规则。
    </p>
    <p v-if="!enabled" class="notice">
      预约记录尚未接入，或当前账号 / 业务时区未配置。请等待统一身份与接口接入。
    </p>
    <label class="filter"
      >预约状态
      <select v-model="query.status" :disabled="!enabled" @change="filter">
        <option value="">全部状态</option>
        <option
          v-for="(label, status) in reservationLabels"
          :key="status"
          :value="status"
        >
          {{ label }}
        </option>
      </select></label
    >
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="loading" role="status">正在读取本人预约…</p>
    <template v-if="page">
      <p v-if="!page.items.length" class="empty">本页没有符合条件的预约。</p>
      <div class="records-grid">
        <article v-for="item in page.items" :key="item.id" class="record">
          <div class="record-title">
            <strong>{{ item.roomCode }} · {{ item.seatCode }} 号座位</strong
            ><span>{{ reservationLabels[item.status] }}</span>
          </div>
          <p>{{ item.roomName }} · 预约 #{{ item.id }}</p>
          <p>{{ time(item.startAt) }} 至 {{ time(item.endAt) }}</p>
          <p v-if="item.checkedInAt">签到于 {{ time(item.checkedInAt) }}</p>
          <p v-if="item.cancelledAt">
            取消于 {{ time(item.cancelledAt)
            }}<span v-if="item.cancelReason">
              ·
              {{
                item.cancelReason === "no_show" ? "未签到" : "服务端已记录原因"
              }}</span
            >
          </p>
          <button
            v-if="item.status === 'booked'"
            :disabled="!canCheckin || flow?.state.phase !== 'idle'"
            :aria-label="`签到预约 ${item.id}`"
            @click="select(item)"
          >
            输入现场码
          </button>
        </article>
      </div>
      <nav class="pagination" aria-label="预约分页">
        <button :disabled="loading || query.offset === 0" @click="move(-1)">
          上一页</button
        ><span
          >第 {{ query.offset / query.limit + 1 }} 页 · 本页
          {{ page.items.length }} 条</span
        ><button
          :disabled="loading || page.items.length < query.limit"
          @click="move(1)"
        >
          下一页
        </button>
      </nav>
    </template>
    <section
      v-if="flow?.visibleReceipt && flow.state.phase !== 'idle'"
      class="checkin"
      aria-label="现场签到"
    >
      <h3>
        预约 #{{ flow.visibleReceipt.id }} ·
        {{ flow.visibleReceipt.roomCode }} / {{ flow.visibleReceipt.seatCode }}
      </h3>
      <p role="status">{{ flow.state.message }}</p>
      <form
        v-if="['ready', 'rejected'].includes(flow.state.phase)"
        @submit.prevent="submit"
      >
        <label
          >教室现场码
          <input
            v-model="code"
            name="checkin-code"
            type="password"
            autocomplete="off"
            maxlength="32"
            :disabled="flow.busy" /></label
        ><button type="submit" :disabled="!code.trim() || flow.busy">
          确认签到
        </button>
      </form>
      <button v-if="flow.state.phase === 'unknown'" @click="recover">
        查询原预约签到结果
      </button>
      <button
        v-if="!flow.pending"
        class="secondary"
        @click="
          code = '';
          flow.close();
        "
      >
        关闭签到面板
      </button>
    </section>
    <section class="violations" aria-label="本人违约记录">
      <header>
        <h3>本人违约记录</h3>
        <button
          :disabled="!enabled || loadingViolations"
          @click="loadViolations"
        >
          刷新违约记录
        </button>
      </header>
      <p>仅展示服务端已记录的结果；处罚及申诉规则以团队确认的政策为准。</p>
      <p v-if="violationError" role="alert" class="error">
        {{ violationError }}
      </p>
      <p v-if="loadingViolations" role="status">正在读取违约记录…</p>
      <p v-if="violations?.length === 0">暂无违约记录。</p>
      <ul v-if="violations?.length">
        <li v-for="item in violations" :key="item.id">
          预约 #{{ item.reservationId }} ·
          {{ item.reason === "no_show" ? "未签到记录" : "服务端违约记录" }} ·
          {{ time(item.occurredAt) }}
        </li>
      </ul>
    </section>
  </section>
</template>

<style scoped>
.my-reservations {
  margin-top: 28px;
  color: #173d30;
}
header,
.record-title,
.pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
h2,
h3 {
  margin: 0 0 10px;
}
p {
  line-height: 1.65;
  color: #526661;
}
button {
  background: #245b42;
  color: white;
  border: 1px solid #245b42;
  border-radius: 8px;
  padding: 10px 16px;
  font: inherit;
  cursor: pointer;
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.notice {
  background: #fff3d6;
  padding: 14px;
  border-radius: 10px;
}
.filter,
form label {
  display: flex;
  gap: 12px;
  align-items: center;
}
select,
input {
  padding: 10px;
  font: inherit;
  border: 1px solid #bccdc3;
  border-radius: 8px;
  max-width: 100%;
}
.records-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 20px 0;
}
.record,
.checkin,
.violations {
  background: white;
  border: 1px solid #d9e2dc;
  border-radius: 14px;
  padding: 20px;
}
.record-title {
  align-items: flex-start;
  flex-wrap: wrap;
}
.record-title span {
  font-size: 14px;
  background: #edf2e9;
  padding: 4px 8px;
  border-radius: 8px;
}
.record p {
  font-size: 14px;
}
.pagination {
  justify-content: center;
  margin: 20px 0;
  flex-wrap: wrap;
}
.checkin {
  margin: 24px 0;
  border-color: #9eb8a3;
}
form {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.secondary {
  background: white;
  color: #245b42;
  margin-top: 16px;
}
.violations {
  margin-top: 28px;
}
.error {
  color: #8b3025;
  background: #fff0ed;
  padding: 12px;
}
.empty {
  padding: 20px 0;
}
@media (max-width: 650px) {
  .records-grid {
    grid-template-columns: 1fr;
  }
  header {
    align-items: flex-start;
    flex-direction: column;
  }
  form label {
    flex-wrap: wrap;
  }
}
</style>
