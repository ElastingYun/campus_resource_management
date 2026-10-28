<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { GatewayMessage } from "./models";
import type {
  ApplicationDraft,
  ApplicationView,
  M2Gateway,
  RoomOption,
} from "./models";

const props = defineProps<{ gateway: M2Gateway }>();
const page = ref<"list" | "new" | "review">("list");
const rooms = ref<RoomOption[]>([]);
const applications = ref<ApplicationView[]>([]);
const selectedId = ref("");
const search = ref("");
const loading = ref(false);
const writing = ref(false);
const error = ref("");
const notice = ref("");
const loaded = ref(false);
const draft = reactive<ApplicationDraft>({
  roomId: "",
  purpose: "",
  startsAt: "",
  endsAt: "",
});
const prototype = computed(() => props.gateway.mode === "prototype");
const canWrite = computed(
  () => loaded.value && props.gateway.mode !== "unconfigured",
);
const filtered = computed(() => {
  const query = search.value.trim().toLowerCase();
  return applications.value.filter((item) =>
    `${item.id} ${item.roomName} ${item.purpose}`.toLowerCase().includes(query),
  );
});
const selected = computed(
  () =>
    filtered.value.find((item) => item.id === selectedId.value) ??
    filtered.value[0],
);
const messageFor = (cause: unknown) =>
  cause instanceof GatewayMessage
    ? cause.message
    : "暂时无法完成操作，请保留输入后重试。";

async function reload() {
  if (loading.value || writing.value) return;
  loading.value = true;
  loaded.value = false;
  error.value = "";
  notice.value = "";
  try {
    const data = await props.gateway.load();
    rooms.value = data.rooms;
    applications.value = data.applications;
    loaded.value = true;
  } catch (cause) {
    rooms.value = [];
    applications.value = [];
    error.value = messageFor(cause);
  } finally {
    loading.value = false;
  }
}

async function submit() {
  if (writing.value || !canWrite.value) return;
  error.value = "";
  notice.value = "";
  if (
    !draft.roomId ||
    !draft.purpose.trim() ||
    !draft.startsAt ||
    !draft.endsAt
  ) {
    error.value = "请选择教室，并填写用途和完整时段。";
    return;
  }
  if (
    !(new Date(draft.endsAt).getTime() > new Date(draft.startsAt).getTime())
  ) {
    error.value = "结束时间需要晚于开始时间。";
    return;
  }
  writing.value = true;
  try {
    const record = await props.gateway.submit({
      ...draft,
      purpose: draft.purpose.trim(),
    });
    applications.value = [
      record,
      ...applications.value.filter((item) => item.id !== record.id),
    ];
    selectedId.value = record.id;
    search.value = "";
    page.value = "list";
    notice.value = prototype.value
      ? "已添加演示记录；没有发送真实申请，刷新后重置。"
      : "申请已提交，请以服务端返回结果为准。";
  } catch (cause) {
    error.value = messageFor(cause);
  } finally {
    writing.value = false;
  }
}

async function simulate(decision: "accept" | "return") {
  if (
    !prototype.value ||
    !props.gateway.simulateDecision ||
    !selected.value ||
    writing.value
  )
    return;
  writing.value = true;
  error.value = "";
  notice.value = "";
  try {
    const record = await props.gateway.simulateDecision(
      selected.value.id,
      decision,
    );
    applications.value = applications.value.map((item) =>
      item.id === record.id ? record : item,
    );
    notice.value = "已更新本页演示状态；没有执行真实审批或改变座位占用。";
  } catch (cause) {
    error.value = messageFor(cause);
  } finally {
    writing.value = false;
  }
}

function navigate(next: "list" | "new" | "review") {
  if (writing.value) return;
  page.value = next;
  error.value = "";
  notice.value = "";
}
const formatTime = (value: string) => value.replace("T", " ");
onMounted(reload);
</script>

<template>
  <div class="m2-workspace">
    <header class="topbar">
      <a href="#">← 平台首页</a><span>校园资源服务平台 / M2</span>
    </header>
    <div class="workspace-layout">
      <aside class="sidebar">
        <p class="section-label">教室资源</p>
        <h1>申请与审批</h1>
        <nav aria-label="M2 页面">
          <button
            :aria-pressed="page === 'list'"
            :disabled="writing"
            @click="navigate('list')"
          >
            我的申请
          </button>
          <button
            :aria-pressed="page === 'new'"
            :disabled="writing"
            @click="navigate('new')"
          >
            新建申请
          </button>
          <button
            v-if="prototype"
            :aria-pressed="page === 'review'"
            :disabled="writing"
            @click="navigate('review')"
          >
            审批预览
          </button>
        </nav>
        <p class="sidebar-note">
          记录申请与处理进度，让每一次资源使用有迹可循。
        </p>
        <a v-if="!prototype" href="#m2-prototype">查看交互原型 →</a>
      </aside>
      <main class="workspace-main">
        <div v-if="prototype" class="prototype-banner" role="note">
          <strong>交互原型 · 合成数据</strong
          ><span>操作只在本页演示，刷新后重置，不提交真实申请。</span>
        </div>
        <p v-if="gateway.mode === 'unconfigured'" class="integration-pending">
          申请服务尚未接入，当前不能提交真实申请。
        </p>
        <div class="page-heading">
          <div>
            <p class="section-label">教室使用安排</p>
            <h2>
              {{
                page === "new"
                  ? "新建教室申请"
                  : page === "review"
                    ? "审批交互预览"
                    : "我的教室申请"
              }}
            </h2>
          </div>
          <button
            class="secondary"
            :disabled="loading || writing"
            @click="reload"
          >
            重新载入
          </button>
        </div>
        <p v-if="notice" class="notice" role="status">{{ notice }}</p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <p v-if="loading" class="empty" role="status">正在载入申请与教室…</p>
        <form
          v-else-if="page === 'new'"
          class="request-form panel"
          @submit.prevent="submit"
          novalidate
        >
          <p class="form-intro">填写教室用途与时段，预览申请过程。</p>
          <fieldset :disabled="!canWrite || writing">
            <label for="m2-room">选择教室</label
            ><select id="m2-room" v-model="draft.roomId" required>
              <option value="">请选择教室</option>
              <option v-for="room in rooms" :key="room.id" :value="room.id">
                {{ room.name }} · {{ room.location }}
              </option>
            </select>
            <label for="m2-purpose">申请用途</label
            ><textarea
              id="m2-purpose"
              v-model="draft.purpose"
              required
              rows="3"
              placeholder="例如：课程小组讨论"
            ></textarea>
            <div class="time-fields">
              <div>
                <label for="m2-start">开始时间</label
                ><input
                  id="m2-start"
                  v-model="draft.startsAt"
                  required
                  type="datetime-local"
                />
              </div>
              <div>
                <label for="m2-end">结束时间</label
                ><input
                  id="m2-end"
                  v-model="draft.endsAt"
                  required
                  type="datetime-local"
                />
              </div>
            </div>
          </fieldset>
          <p v-if="prototype" class="muted">
            原型字段与流程供讨论，正式规则以团队确认的契约为准。
          </p>
          <button
            class="primary"
            type="submit"
            :disabled="!canWrite || writing"
          >
            {{ writing ? "正在处理…" : prototype ? "演示提交" : "提交申请" }}
          </button>
        </form>
        <template v-else-if="loaded">
          <div class="summary">
            <div>
              <span>当前记录</span><strong>{{ applications.length }}</strong>
            </div>
            <div>
              <span>可选教室</span><strong>{{ rooms.length }}</strong>
            </div>
            <p>
              {{
                page === "review"
                  ? "演示审批视角，不代表当前账号拥有审批权限。"
                  : "选择一条申请查看时段、用途和处理信息。"
              }}
            </p>
          </div>
          <label class="search-label" for="m2-search">查询申请</label
          ><input
            id="m2-search"
            v-model="search"
            type="search"
            placeholder="按教室、用途或申请编号查询"
          />
          <p v-if="!filtered.length" class="empty">没有符合条件的申请。</p>
          <div v-else class="records-layout">
            <section aria-label="申请列表" class="records-list">
              <button
                v-for="item in filtered"
                :key="item.id"
                class="record-card"
                :aria-pressed="selected?.id === item.id"
                @click="selectedId = item.id"
              >
                <span class="record-top"
                  ><span>{{ item.id }}</span
                  ><span class="badge" :class="item.statusTone">{{
                    item.statusLabel
                  }}</span></span
                ><strong>{{ item.roomName }}</strong
                ><span>{{ item.purpose }}</span
                ><small
                  >{{ formatTime(item.startsAt) }} —
                  {{ formatTime(item.endsAt) }}</small
                >
              </button>
            </section>
            <section v-if="selected" class="panel detail" aria-label="申请详情">
              <p class="section-label">申请详情</p>
              <h3>{{ selected.roomName }}</h3>
              <dl>
                <dt>申请编号</dt>
                <dd>{{ selected.id }}</dd>
                <dt>申请用途</dt>
                <dd>{{ selected.purpose }}</dd>
                <dt>使用时段</dt>
                <dd>
                  {{ formatTime(selected.startsAt) }}<br />至
                  {{ formatTime(selected.endsAt) }}
                </dd>
                <dt>当前展示状态</dt>
                <dd>
                  <span class="badge" :class="selected.statusTone">{{
                    selected.statusLabel
                  }}</span>
                </dd>
              </dl>
              <p class="detail-note">{{ selected.note }}</p>
              <div
                v-if="page === 'review' && prototype"
                class="decision-actions"
              >
                <button
                  class="primary"
                  :disabled="writing"
                  @click="simulate('accept')"
                >
                  演示处理完成</button
                ><button
                  class="secondary"
                  :disabled="writing"
                  @click="simulate('return')"
                >
                  演示需补充
                </button>
              </div>
            </section>
          </div>
        </template>
        <div v-else-if="!loading" class="empty">
          <p>申请服务准备好后，这里会显示真实记录。</p>
          <a href="#m2-prototype">先查看合成数据原型 →</a>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.m2-workspace {
  min-height: 100vh;
  color: #213a35;
  background: #f6f7f3;
}
.topbar {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 20px 36px;
  border-bottom: 1px solid #dce3de;
  background: white;
  font-size: 14px;
}
a {
  color: #275d4d;
  text-underline-offset: 4px;
}
.workspace-layout {
  max-width: 1440px;
  margin: auto;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
}
.sidebar {
  padding: 40px 28px;
  border-right: 1px solid #dce3de;
}
h1 {
  font-size: 26px;
  margin: 8px 0 30px;
}
.section-label {
  font-size: 12px;
  color: #6b7b73;
  letter-spacing: 1px;
  margin: 0 0 6px;
}
nav {
  display: grid;
  gap: 8px;
}
nav button {
  width: 100%;
  text-align: left;
  background: transparent;
  color: #36594c;
  border: 0;
}
nav button[aria-pressed="true"] {
  background: #dfece4;
  color: #184d38;
  font-weight: 650;
}
.sidebar-note {
  color: #738077;
  font-size: 13px;
  margin: 36px 0 20px;
}
.workspace-main {
  margin: 0;
  max-width: none;
  min-width: 0;
  padding: 32px;
}
.prototype-banner {
  padding: 12px 18px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  background: #fff1d3;
  border: 1px solid #e7d4ab;
  border-radius: 8px;
  font-size: 13px;
  color: #715d2c;
}
.page-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin: 28px 0 24px;
}
h2 {
  font-size: 27px;
  margin: 0;
}
h3 {
  font-size: 23px;
  margin: 10px 0 22px;
}
button {
  font-size: 14px;
}
.secondary {
  color: #315b4b;
  background: white;
  border: 1px solid #b8cbbf;
}
button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.summary {
  display: flex;
  gap: 32px;
  align-items: center;
  padding: 22px 26px;
  background: #e8eee8;
  border-radius: 10px;
  margin-bottom: 24px;
}
.summary div {
  display: grid;
  gap: 2px;
  min-width: 70px;
}
.summary span {
  font-size: 12px;
  color: #617166;
}
.summary strong {
  font-size: 28px;
}
.summary p {
  color: #607064;
  font-size: 13px;
  margin-left: auto;
  max-width: 270px;
}
label {
  display: block;
  font-size: 14px;
  margin-bottom: 8px;
  color: #38584a;
}
input,
select,
textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid #c9d4cb;
  border-radius: 7px;
  background: white;
  color: #263f33;
  font: inherit;
  font-size: 14px;
}
input:focus-visible,
select:focus-visible,
textarea:focus-visible {
  outline: 3px solid #a2c8b2;
  outline-offset: 2px;
}
#m2-search {
  margin-bottom: 20px;
}
.records-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(270px, 0.85fr);
  gap: 20px;
  margin-top: 20px;
  align-items: start;
}
.records-list {
  display: grid;
  gap: 12px;
}
.record-card {
  display: grid;
  width: 100%;
  gap: 8px;
  color: #27463a;
  background: white;
  border: 1px solid #d4ddd5;
  text-align: left;
  white-space: normal;
  padding: 20px;
  border-radius: 10px;
}
.record-card[aria-pressed="true"] {
  border-color: #4f896a;
  box-shadow: inset 3px 0 #4f896a;
}
.record-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #687e70;
}
.record-card strong {
  font-size: 18px;
}
.record-card small {
  color: #6c7e71;
  font-size: 12px;
}
.badge {
  display: inline-block;
  border-radius: 5px;
  padding: 3px 7px;
  background: #edf0ec;
  color: #576957;
  font-size: 12px;
}
.badge.positive {
  background: #e1f0e5;
  color: #2a6545;
}
.badge.attention {
  background: #fff0d5;
  color: #88662b;
}
.panel {
  background: white;
  padding: 26px;
  border: 1px solid #dce3dc;
  border-radius: 10px;
}
dl {
  margin: 0;
}
dt {
  color: #7a867e;
  font-size: 12px;
  margin: 18px 0 4px;
}
dd {
  margin: 0;
  font-size: 14px;
  overflow-wrap: anywhere;
}
.detail-note {
  margin-top: 26px;
  padding-top: 20px;
  border-top: 1px solid #e8ece7;
  font-size: 13px;
  color: #6e7c72;
}
.decision-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 20px;
}
.request-form {
  max-width: 720px;
}
.form-intro {
  margin-top: 0;
  color: #647a6d;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 20px 0;
}
fieldset label {
  margin-top: 18px;
}
.time-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.muted {
  color: #7a7f73;
  font-size: 12px;
}
.error,
.notice {
  padding: 14px 18px;
  border-radius: 8px;
  font-size: 14px;
}
.error {
  background: #fae9e4;
  color: #9a4634;
}
.notice {
  background: #e0eee4;
  color: #2e6547;
}
.empty {
  padding: 35px 24px;
  text-align: center;
  border: 1px dashed #bdcdc0;
  border-radius: 9px;
  color: #6c7f70;
  margin: 22px 0;
}
@media (max-width: 1000px) {
  .workspace-layout {
    grid-template-columns: 190px minmax(0, 1fr);
  }
  .sidebar {
    padding: 30px 18px;
  }
  .workspace-main {
    padding: 24px;
  }
  .records-layout {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 650px) {
  .topbar {
    padding: 16px;
    font-size: 12px;
  }
  .topbar span {
    display: none;
  }
  .workspace-layout {
    display: block;
  }
  .sidebar {
    border: 0;
    padding: 20px 16px 0;
  }
  h1 {
    margin: 0 0 12px;
    font-size: 24px;
  }
  nav {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 4px;
  }
  nav button {
    padding: 9px;
    text-align: center;
    font-size: 13px;
  }
  .sidebar-note,
  .sidebar > a {
    display: none;
  }
  .workspace-main {
    padding: 20px 16px;
  }
  h2 {
    font-size: 23px;
  }
  .page-heading {
    align-items: start;
  }
  .summary {
    flex-wrap: wrap;
    gap: 20px;
    padding: 18px;
  }
  .summary p {
    max-width: none;
    margin: 0;
  }
  .time-fields {
    grid-template-columns: 1fr;
    gap: 0;
  }
  .panel {
    padding: 20px;
  }
}
</style>
