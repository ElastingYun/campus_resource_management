<script setup lang="ts">
import { computed } from "vue";
import type { BookingFlow } from "./flow";
import { reservationLabels } from "./models";
const props = defineProps<{
  flow: BookingFlow;
  timeZone: string;
  prototype: boolean;
  retained?: boolean;
}>();
const emit = defineEmits<{ closed: [] }>();
const receipt = computed(() => props.flow.visibleReceipt);
const titles = {
  idle: "预约",
  confirming: "确认预约",
  submitting: "正在提交预约",
  checking: "正在核对预约",
  unknown: "预约结果待核对",
  rejected: "预约未完成",
  resolved: "预约核对结果",
};
function time(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: props.timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "shortOffset",
  }).format(new Date(value));
}
function close() {
  if (props.flow.close()) emit("closed");
}
</script>
<template>
  <section
    v-if="flow.active"
    class="booking-panel"
    aria-labelledby="booking-title"
  >
    <p v-if="prototype" class="demo-note">
      合成预约演示 · 数据仅保存在页面内存，刷新清空
    </p>
    <h2 id="booking-title">{{ titles[flow.state.phase] }}</h2>
    <template v-if="flow.actorMatches && flow.state.selection">
      <dl>
        <div>
          <dt>教室与座位</dt>
          <dd>
            {{ flow.state.selection.seat.roomName }} ·
            {{ flow.state.selection.seat.code }} 号座位
          </dd>
        </div>
        <div>
          <dt>预约时段</dt>
          <dd>
            {{ time(flow.state.selection.startAt) }} →
            {{ time(flow.state.selection.endAt) }}
          </dd>
        </div>
        <div>
          <dt>时长</dt>
          <dd>{{ flow.state.selection.hours }} 小时</dd>
        </div>
      </dl>
      <p v-if="flow.state.phase === 'confirming'" class="hint">
        查询结果是当时的快照。确认后服务端会再次检查座位、时段和预约资格。
      </p>
      <p
        v-if="receipt"
        class="receipt"
        :data-status="receipt.status"
        role="status"
      >
        {{ prototype ? "合成预约" : "预约" }} #{{ receipt.id }} ·
        {{ reservationLabels[receipt.status] }}
        <span>{{
          receipt.status === "booked" || receipt.status === "checked_in"
            ? "预约状态已核对。"
            : "已找到原预约，请以当前状态为准。"
        }}</span>
      </p>
    </template>
    <p v-else role="alert">账号已变化，原预约信息已隐藏。请切回原账号核对。</p>
    <p
      v-if="flow.state.message && flow.actorMatches"
      class="booking-message"
      role="alert"
    >
      {{ flow.state.message }}
    </p>
    <p v-if="flow.busy" role="status">
      {{
        flow.state.phase === "submitting"
          ? "请求处理中，请勿重复提交…"
          : "正在读取服务端最新状态…"
      }}
    </p>
    <p v-if="flow.pending" class="hint">
      {{
        retained
          ? "应用内切页会保留原请求；刷新前请先核对结果。"
          : "请先核对结果再离开，刷新会丢失本页恢复信息。"
      }}
      离开应用后请使用原账号核对服务端预约记录，必要时联系管理员。
    </p>
    <div class="booking-actions">
      <button
        v-if="flow.state.phase === 'confirming'"
        :disabled="!flow.actorMatches"
        @click="flow.confirm()"
      >
        确认预约
      </button>
      <button
        v-if="flow.state.phase === 'unknown'"
        :disabled="!flow.actorMatches || flow.busy"
        @click="flow.recover()"
      >
        核对原预约结果
      </button>
      <button class="secondary" :disabled="flow.pending" @click="close">
        返回查询
      </button>
    </div>
  </section>
</template>
<style scoped>
.booking-panel {
  margin: 26px 0;
  padding: 24px;
  border: 2px solid #427958;
  border-radius: 16px;
  background: #fff;
}
h2 {
  margin: 10px 0 20px;
  font-size: 22px;
}
.demo-note {
  margin: 0;
  color: #856023;
  font-size: 13px;
}
dl {
  margin: 0;
  display: grid;
  gap: 14px;
}
dl div {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 12px;
}
dt {
  color: #65766b;
  font-size: 14px;
}
dd {
  margin: 0;
  line-height: 1.7;
}
.hint {
  font-size: 13px;
  color: #65766b;
  line-height: 1.8;
}
.receipt {
  background: #e6f2e6;
  border-radius: 9px;
  padding: 16px;
  font-weight: 600;
}
.receipt span {
  display: block;
  margin-top: 6px;
  font-size: 13px;
  font-weight: 400;
}
.receipt[data-status="cancelled"],
.receipt[data-status="no_show"] {
  background: #f6eddc;
  color: #735a2f;
}
.booking-message {
  color: #8b3025;
  line-height: 1.8;
}
.booking-actions {
  display: flex;
  gap: 12px;
  margin-top: 20px;
}
button {
  padding: 10px 18px;
  background: #245b42;
  border: 1px solid #245b42;
  border-radius: 8px;
  color: white;
  font: inherit;
  cursor: pointer;
}
button.secondary {
  background: white;
  color: #245b42;
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
@media (max-width: 560px) {
  dl div {
    grid-template-columns: 1fr;
    gap: 4px;
  }
  .booking-panel {
    padding: 18px;
  }
}
</style>
