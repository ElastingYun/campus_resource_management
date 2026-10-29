<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { businessDate } from "../seat-search/models";
import { reservationLabels } from "../booking/models";
import { OperationsError } from "./models";
import type {
  OperationsGateway,
  UsageReport,
  SeatEvent,
  RoomCode,
} from "./models";
const props = defineProps<{
  gateway: OperationsGateway;
  businessTimeZone?: string;
}>();
const actor = computed(() => {
  try {
    return props.gateway.currentActorId();
  } catch {
    return null;
  }
});
const capabilities = computed(() => {
  try {
    return props.gateway.capabilities();
  } catch {
    return { operations: false, roomCode: false };
  }
});
const zone = computed(() => {
  try {
    if (props.businessTimeZone) {
      new Intl.DateTimeFormat("zh-CN", { timeZone: props.businessTimeZone });
      return props.businessTimeZone;
    }
  } catch {
    /* Stay closed for invalid host configuration. */
  }
  return null;
});
const enabled = computed(
  () => props.gateway.mode !== "unconfigured" && !!actor.value && !!zone.value,
);
const date = ref(zone.value ? businessDate(new Date(), zone.value) : ""),
  roomId = ref(""),
  seatId = ref("");
const report = ref<UsageReport>(),
  events = ref<SeatEvent[]>(),
  code = ref<RoomCode>();
type Task = "usage" | "events" | "code";
const loading = reactive({ usage: false, events: false, code: false }),
  errors = reactive({ usage: "", events: "", code: "" });
const generations = { usage: 0, events: 0, code: 0 };
const controllers: Partial<Record<Task, AbortController>> = {};
let timer: ReturnType<typeof setInterval> | undefined;
function clear() {
  for (const task of ["usage", "events", "code"] as const) {
    generations[task]++;
    controllers[task]?.abort();
    loading[task] = false;
    errors[task] = "";
  }
  report.value = undefined;
  events.value = undefined;
  code.value = undefined;
}
async function run<T>(
  task: Task,
  operation: (owner: string, signal: AbortSignal) => Promise<T>,
  accept: (result: T) => void,
) {
  if (
    !enabled.value ||
    !(task === "code"
      ? capabilities.value.roomCode
      : capabilities.value.operations)
  )
    return;
  const owner = actor.value!,
    generation = ++generations[task];
  controllers[task]?.abort();
  const controller = (controllers[task] = new AbortController());
  loading[task] = true;
  errors[task] = "";
  try {
    const result = await operation(owner, controller.signal);
    if (generation === generations[task] && actor.value === owner)
      accept(result);
  } catch (error) {
    if (generation === generations[task] && actor.value === owner)
      errors[task] =
        error instanceof OperationsError
          ? error.message
          : "服务暂不可用，请稍后查询。";
  } finally {
    if (generation === generations[task]) loading[task] = false;
  }
}
function loadUsage() {
  report.value = undefined;
  return run(
    "usage",
    (owner, signal) => props.gateway.usage(date.value, owner, signal),
    (result) => {
      report.value = result;
    },
  );
}
function loadEvents() {
  events.value = undefined;
  return run(
    "events",
    (owner, signal) =>
      props.gateway.events(
        { roomId: roomId.value, seatId: seatId.value, limit: 50 },
        owner,
        signal,
      ),
    (result) => {
      events.value = result;
    },
  );
}
function loadCode() {
  code.value = undefined;
  return run(
    "code",
    (owner, signal) => props.gateway.roomCode(roomId.value, owner, signal),
    (result) => {
      if (Date.parse(result.validUntil) <= Date.now()) {
        errors.code = "教室码已过期，请重新获取。";
        return;
      }
      code.value = result;
    },
  );
}
function time(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: zone.value!,
    dateStyle: "medium",
    timeStyle: "short",
    hourCycle: "h23",
  }).format(new Date(value));
}
function source(value: string) {
  return (
    (
      {
        m1_reservation: "个人预约",
        m2_approval: "整室审批",
        m3_repair: "物业报修",
      } as Record<string, string>
    )[value] ?? "其他服务端来源"
  );
}
watch(
  () => JSON.stringify([actor.value, capabilities.value, zone.value]),
  clear,
  { flush: "sync" },
);
watch([date, roomId, seatId], clear, { flush: "sync" });
onMounted(() => {
  timer = setInterval(() => {
    if (code.value && Date.parse(code.value.validUntil) <= Date.now()) {
      code.value = undefined;
      errors.code = "教室码已过期，请重新获取。";
    }
  }, 1000);
});
onUnmounted(() => {
  clear();
  clearInterval(timer);
});
</script>

<template>
  <section class="operations" aria-label="运营与教室终端">
    <h2>运营查看与教室终端</h2>
    <p v-if="gateway.mode === 'prototype'" class="notice">
      合成运营演示：指标、来源事件和教室码均为示例，不代表真实运营结果或终端授权；演示码60秒后隐藏。
    </p>
    <p v-if="!enabled" class="notice">运营接口、可信身份或业务时区尚未接入。</p>
    <section class="panel" aria-label="每日运营汇总">
      <h3>每日运营汇总</h3>
      <p>按服务端口径展示当日汇总，前端不重新计算容量或利用率。</p>
      <p v-if="!capabilities.operations">当前账号没有运营查看权限。</p>
      <form @submit.prevent="loadUsage">
        <label
          >汇总日期
          <input
            v-model="date"
            type="date"
            :disabled="!enabled || !capabilities.operations" /></label
        ><button
          :disabled="!enabled || !capabilities.operations || loading.usage"
        >
          查询汇总
        </button>
      </form>
      <p v-if="loading.usage" role="status">正在读取汇总…</p>
      <p v-if="errors.usage" role="alert" class="error">{{ errors.usage }}</p>
      <div v-if="report" class="table-scroll">
        <p>{{ report.date }} · 服务端返回 {{ report.rooms.length }} 个教室</p>
        <p v-if="!report.rooms.length">当日没有运营数据。</p>
        <table v-else>
          <thead>
            <tr>
              <th>教室 / 稳定ID</th>
              <th>启用座位</th>
              <th v-for="(label, status) in reservationLabels" :key="status">
                {{ label }}
              </th>
              <th>已签到座位小时</th>
              <th>容量座位小时</th>
              <th>服务端利用率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="room in report.rooms" :key="room.id">
              <th>{{ room.code }} / {{ room.id }}</th>
              <td>{{ room.seats }}</td>
              <td v-for="(_, status) in reservationLabels" :key="status">
                {{ room.reservations[status] }}
              </td>
              <td>{{ room.checkedInHours }}</td>
              <td>{{ room.capacityHours }}</td>
              <td>{{ (room.utilization * 100).toFixed(2) }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <section class="panel" aria-label="来源与教室码">
      <h3>教室来源轨迹 / 授权终端</h3>
      <p>
        仅使用已知的稳定编号查询；来源轨迹不表示当前可预约，座位留空时查询全室。
      </p>
      <div class="identifiers">
        <label
          >教室稳定ID
          <input
            v-model="roomId"
            inputmode="numeric"
            :disabled="!enabled" /></label
        ><label
          >座位稳定ID（可选）
          <input
            v-model="seatId"
            inputmode="numeric"
            :disabled="!enabled || !capabilities.operations"
        /></label>
      </div>
      <button
        :disabled="
          !enabled || !capabilities.operations || !roomId || loading.events
        "
        @click="loadEvents"
      >
        查询来源轨迹
      </button>
      <p v-if="loading.events" role="status">正在读取来源…</p>
      <p v-if="errors.events" role="alert" class="error">{{ errors.events }}</p>
      <template v-if="events"
        ><p v-if="!events.length">未返回来源事件。</p>
        <ul class="events">
          <li v-for="(event, index) in events" :key="index">
            <strong>{{ source(event.sourceType) }}</strong> ·
            {{ event.seatId ? `座位 ${event.seatId}` : "整室范围" }}<br />记录于
            {{ time(event.occurredAt) }}；影响时段 {{ time(event.startAt) }} →
            {{ event.endAt ? time(event.endAt) : "未提供结束时间" }}
          </li>
        </ul>
        <p>仅展示最近最多50条；服务端未提供历史总数。</p></template
      >
      <section class="room-code" aria-label="授权教室码">
        <h4>当前日教室码</h4>
        <p>
          仅供获授权的教室终端或管理员现场展示。学生请在“我的预约”输入现场码，页面不会自动获取。
        </p>
        <p v-if="!capabilities.roomCode">当前账号没有教室码查看权限。</p>
        <button
          :disabled="
            !enabled || !capabilities.roomCode || !roomId || loading.code
          "
          @click="loadCode"
        >
          获取当前教室码
        </button>
        <p v-if="loading.code" role="status">正在获取教室码…</p>
        <p v-if="errors.code" role="alert" class="error">{{ errors.code }}</p>
        <div v-if="code" class="code-display">
          <p>教室 {{ code.roomId }} · {{ code.date }}</p>
          <strong>{{ code.code }}</strong>
          <p>服务端有效截止 {{ time(code.validUntil) }}（{{ zone }}）</p>
          <button @click="code = undefined">隐藏教室码</button>
        </div>
      </section>
    </section>
  </section>
</template>

<style scoped>
.operations {
  color: #173d30;
  margin-top: 28px;
}
h2,
h3,
h4 {
  margin: 0 0 14px;
}
p {
  line-height: 1.7;
  color: #526661;
}
.panel {
  background: white;
  border: 1px solid #d9e2dc;
  padding: 24px;
  border-radius: 14px;
  margin: 20px 0;
}
.notice {
  background: #fff3d6;
  padding: 16px;
  border-radius: 10px;
}
form,
.identifiers {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin: 16px 0;
}
label {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
input {
  border: 1px solid #bccdc3;
  padding: 10px;
  border-radius: 8px;
  font: inherit;
  max-width: 100%;
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
.table-scroll {
  overflow-x: auto;
}
table {
  border-collapse: collapse;
  width: 100%;
  font-size: 14px;
}
th,
td {
  padding: 12px;
  border-bottom: 1px solid #d9e2dc;
  text-align: left;
  white-space: nowrap;
}
.events {
  padding-left: 22px;
  line-height: 1.8;
}
.events li {
  margin: 12px 0;
}
.room-code {
  margin-top: 28px;
  padding-top: 24px;
  border-top: 1px solid #d9e2dc;
}
.code-display {
  padding: 20px;
  background: #f0f5ec;
  border-radius: 12px;
  margin-top: 16px;
}
.code-display strong {
  font-size: 42px;
  letter-spacing: 0.18em;
}
.error {
  color: #8b3025;
  background: #fff0ed;
  padding: 12px;
}
@media (max-width: 650px) {
  .panel {
    padding: 16px;
  }
  form,
  .identifiers {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
