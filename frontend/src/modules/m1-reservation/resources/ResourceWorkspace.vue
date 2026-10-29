<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ResourceMessage } from "./models";
import { createResourceSession } from "./session";
import type { ResourceSession } from "./session";
import { createUnconfiguredResourceGateway } from "./gateway";
import type { OutletType, ResourceGateway, Room, Seat } from "./models";

const props = defineProps<{
  gateway: ResourceGateway;
  allowManage?: boolean;
  resourceSession?: ResourceSession;
}>();
const emit = defineEmits<{ resourcePending: [pending: boolean] }>();
const retained =
  props.resourceSession?.gateway === props.gateway
    ? props.resourceSession
    : undefined;
const localGateway =
  !props.resourceSession && props.gateway.mode === "prototype"
    ? props.gateway
    : createUnconfiguredResourceGateway();
const local = createResourceSession(localGateway, {
  currentActorId: () => "local-prototype",
  canManage: () => localGateway.mode === "prototype",
});
const session = retained ?? local;
const editing = computed(() => retained?.current ?? local.current!);
const canManage = computed(() => session.canManage && !editing.value.pending);
const canCreateRooms = computed(
  () => session.canCreateRooms && !editing.value.pending,
);
const canEditForm = computed(
  () =>
    session.canManage &&
    !(form.value?.kind === "room" && !form.value.id && !session.canCreateRooms),
);
const form = computed({
  get: () => editing.value.state.form,
  set: (value) => {
    if (value === null) editing.value.closeEditor();
  },
});
const draft = computed(() => editing.value.state.draft);
const saving = computed(() => editing.value.state.saving),
  uncertain = computed(() => editing.value.state.uncertain);
const saveError = computed(() => editing.value.state.saveError),
  notice = computed(() => editing.value.state.notice);
watch(
  () => session.pending,
  (value) => emit("resourcePending", value),
  { immediate: true, flush: "sync" },
);
const roomList = ref<Room[]>([]);
const seatList = ref<Seat[]>([]);
const selected = ref<Room | null>(null);
const roomSearch = ref("");
const seatSearch = ref("");
const outlet = ref<OutletType | "">("");
const roomOffset = ref(0);
const seatOffset = ref(0);
const roomTotal = ref(0);
const seatTotal = ref(0);
const roomLoading = ref(false);
const seatLoading = ref(false);
const roomError = ref("");
const seatError = ref("");
let roomRequest = 0;
let seatRequest = 0;
let roomController: AbortController | undefined;
let seatController: AbortController | undefined;
let disposed = false;
const outletLabel: Record<OutletType, string> = {
  none: "无插座",
  fixed: "固定插座",
  rail: "导轨插座",
};
const message = (error: unknown) =>
  error instanceof ResourceMessage ? error.message : "操作未完成，请稍后重试。";

async function loadRooms(reset = false) {
  if (reset) roomOffset.value = 0;
  const request = ++roomRequest;
  roomController?.abort();
  roomController = new AbortController();
  roomLoading.value = true;
  roomError.value = "";
  try {
    const result = await session.listRooms(
      { q: roomSearch.value.trim(), limit: 20, offset: roomOffset.value },
      roomController.signal,
    );
    if (disposed || request !== roomRequest) return;
    roomList.value = result.items;
    roomTotal.value = result.total;
    roomLoading.value = false;
    const room =
      result.items.find((item) => item.id === selected.value?.id) ??
      result.items[0] ??
      null;
    if (room) await selectRoom(room);
    else {
      selected.value = null;
      seatList.value = [];
      seatTotal.value = 0;
      ++seatRequest;
      seatController?.abort();
    }
  } catch (error) {
    if (!disposed && request === roomRequest) roomError.value = message(error);
  } finally {
    if (!disposed && request === roomRequest) roomLoading.value = false;
  }
}
async function selectRoom(room: Room) {
  selected.value = room;
  seatOffset.value = 0;
  seatSearch.value = "";
  outlet.value = "";
  seatList.value = [];
  await loadSeats();
}
async function loadSeats(reset = false) {
  if (reset) seatOffset.value = 0;
  const roomId = selected.value?.id;
  if (!roomId) return;
  const request = ++seatRequest;
  seatController?.abort();
  seatController = new AbortController();
  seatLoading.value = true;
  seatError.value = "";
  try {
    const result = await session.listSeats(
      roomId,
      {
        q: seatSearch.value.trim(),
        outlet_type: outlet.value || undefined,
        limit: 20,
        offset: seatOffset.value,
      },
      seatController.signal,
    );
    if (disposed || request !== seatRequest || selected.value?.id !== roomId)
      return;
    seatList.value = result.items;
    seatTotal.value = result.total;
  } catch (error) {
    if (!disposed && request === seatRequest) seatError.value = message(error);
  } finally {
    if (!disposed && request === seatRequest) seatLoading.value = false;
  }
}
function openForm(kind: "room" | "seat", item?: Room | Seat) {
  editing.value.open(kind, item, selected.value?.id);
}
async function save() {
  const flow = editing.value;
  await flow.save();
  if (
    disposed ||
    flow !== editing.value ||
    !flow.state.result ||
    flow.state.form
  )
    return;
  if (flow.state.savedKind === "room") {
    roomSearch.value = flow.state.result.code;
    await loadRooms(true);
  } else await loadSeats(true);
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (session.pending) {
    event.preventDefault();
    event.returnValue = "";
  }
}
function guardNavigation(event: MouseEvent) {
  const anchor =
    event.target instanceof Element ? event.target.closest("a[href]") : null;
  if (
    session.pending &&
    anchor &&
    !(retained && anchor.getAttribute("href")?.startsWith("#"))
  )
    event.preventDefault();
}
function clearVisible() {
  ++roomRequest;
  ++seatRequest;
  roomController?.abort();
  seatController?.abort();
  roomList.value = [];
  seatList.value = [];
  selected.value = null;
  roomTotal.value = 0;
  seatTotal.value = 0;
  roomOffset.value = 0;
  seatOffset.value = 0;
  roomSearch.value = "";
  seatSearch.value = "";
  outlet.value = "";
  roomLoading.value = false;
  seatLoading.value = false;
  roomError.value = "";
  seatError.value = "";
}
watch(
  () => [
    retained?.currentActorId,
    retained?.canManage,
    retained?.canCreateRooms,
    retained?.contextVersion,
  ],
  () => {
    clearVisible();
    if (retained?.currentActorId) void loadRooms();
  },
  { flush: "sync" },
);
async function roomPage(step: number) {
  roomOffset.value += step * 20;
  await loadRooms();
}
async function seatPage(step: number) {
  seatOffset.value += step * 20;
  await loadSeats();
}
onMounted(() => {
  window.addEventListener("beforeunload", beforeUnload);
  void loadRooms();
});
onUnmounted(() => {
  disposed = true;
  window.removeEventListener("beforeunload", beforeUnload);
  roomController?.abort();
  seatController?.abort();
});
</script>

<template>
  <main class="resource-workspace" @click.capture="guardNavigation">
    <a class="back" href="#">← 返回工程首页</a>
    <header class="workspace-heading">
      <div>
        <p class="eyebrow">校园资源 · 基础资料</p>
        <h1>教室与座位管理</h1>
        <p>维护资源资料，让每个座位有据可查。</p>
      </div>
      <button
        :disabled="!canCreateRooms || saving || roomLoading || !!form"
        @click="openForm('room')"
      >
        新增教室
      </button>
    </header>
    <p v-if="gateway.mode === 'prototype'" class="banner" role="note">
      合成数据演示：操作仅保存在内存，刷新后重置，不会写入真实资源。演示开放时间不代表正式默认规则。
    </p>
    <p v-else-if="session.mode === 'unconfigured'" class="banner" role="note">
      真实资源服务尚未接入，当前禁止新增和编辑。<a href="#resources-prototype"
        >查看交互演示</a
      >
    </p>
    <p class="hint">
      启用状态仅为基础配置，不代表某个时段可以预约。此处暂不提供停用、删除或开放规则修改。
    </p>
    <p v-if="uncertain" class="banner" role="alert">
      原资源操作仍待核对：{{
        editing.state.pendingTarget
      }}。关闭表单仅允许查看列表，不会清除未知状态或恢复新写入。请使用原账号核对或联系管理员；不要重复提交。
    </p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <section
      v-if="form && session.canManage"
      class="editor"
      aria-labelledby="editor-title"
    >
      <h2 id="editor-title">
        {{ form.id ? "编辑" : "新增"
        }}{{ form.kind === "room" ? "教室" : "座位" }}
      </h2>
      <p v-if="form.kind === 'seat'" class="hint">
        所属教室稳定ID：{{ form.roomId }}；保存目标在打开表单时确定。
      </p>
      <p v-if="!canEditForm" class="hint" role="status">
        新建教室权限已变化，草稿已保留。请取消或确认权限后再保存。
      </p>
      <form @submit.prevent="save">
        <label for="resource-code">{{
          form.kind === "room" ? "教室编号" : "座位编号"
        }}</label>
        <input
          id="resource-code"
          v-model="draft.code"
          required
          maxlength="32"
          :disabled="saving || uncertain || !canEditForm"
          autocomplete="off"
        />
        <template v-if="form.kind === 'room'">
          <label for="room-name">教室名称</label
          ><input
            id="room-name"
            v-model="draft.name"
            required
            maxlength="100"
            :disabled="saving || uncertain || !canEditForm"
          />
          <label for="room-location">位置</label
          ><input
            id="room-location"
            v-model="draft.location"
            required
            maxlength="200"
            :disabled="saving || uncertain || !canEditForm"
          />
        </template>
        <template v-else>
          <label for="seat-outlet">插座类型</label
          ><select
            id="seat-outlet"
            v-model="draft.outlet_type"
            :disabled="saving || uncertain || !canEditForm"
          >
            <option value="none">无插座</option>
            <option value="fixed">固定插座</option>
            <option value="rail">导轨插座</option>
          </select>
        </template>
        <p v-if="saveError" role="alert">{{ saveError }}</p>
        <div class="actions">
          <button type="submit" :disabled="saving || uncertain || !canEditForm">
            {{ saving ? "正在保存…" : "保存" }}</button
          ><button
            type="button"
            class="secondary"
            :disabled="saving"
            @click="form = null"
          >
            {{ uncertain ? "关闭表单并核对列表" : "取消" }}
          </button>
        </div>
      </form>
    </section>
    <div class="resource-columns">
      <section class="room-panel" aria-labelledby="room-list-title">
        <div class="section-heading">
          <h2 id="room-list-title">教室</h2>
          <span>{{ roomTotal }} 间</span>
        </div>
        <form class="filters" @submit.prevent="loadRooms(true)">
          <label class="sr-only" for="room-search">搜索教室</label
          ><input
            id="room-search"
            v-model="roomSearch"
            :disabled="!!form"
            placeholder="编号、名称或位置"
            maxlength="100"
          /><button :disabled="roomLoading || !!form">查询</button>
        </form>
        <p v-if="roomLoading" role="status">正在读取教室…</p>
        <div v-else-if="roomError" role="alert">
          <p>{{ roomError }}</p>
          <button class="secondary" @click="loadRooms()">重试读取教室</button>
        </div>
        <p v-else-if="!roomList.length" class="empty">没有符合条件的教室。</p>
        <ul v-else class="room-list">
          <li v-for="room in roomList" :key="room.id">
            <button
              class="room-choice"
              :class="{ selected: selected?.id === room.id }"
              :aria-pressed="selected?.id === room.id"
              :disabled="saving || !!form"
              @click="selectRoom(room)"
            >
              <span class="room-code">{{ room.code }}</span
              ><strong>{{ room.name }}</strong
              ><span>{{ room.location || "位置未填写" }}</span>
            </button>
          </li>
        </ul>
        <div class="pagination">
          <button
            class="secondary"
            :disabled="roomLoading || roomOffset === 0 || !!form"
            @click="roomPage(-1)"
          >
            上一页</button
          ><span>{{ Math.floor(roomOffset / 20) + 1 }}</span
          ><button
            class="secondary"
            :disabled="roomLoading || roomOffset + 20 >= roomTotal || !!form"
            @click="roomPage(1)"
          >
            下一页
          </button>
        </div>
      </section>
      <section class="seat-panel" aria-labelledby="seat-list-title">
        <template v-if="selected">
          <div class="section-heading">
            <div>
              <p class="eyebrow">{{ selected.code }}</p>
              <h2 id="seat-list-title">{{ selected.name }}</h2>
            </div>
            <button
              class="secondary"
              :disabled="!canManage || saving || roomLoading || !!form"
              @click="openForm('room', selected)"
            >
              编辑教室
            </button>
          </div>
          <dl class="room-facts">
            <div>
              <dt>开放时段</dt>
              <dd>
                {{ selected.open_time.slice(0, 5) }}–{{
                  selected.close_time.slice(0, 5)
                }}
              </dd>
            </div>
            <div>
              <dt>开放范围</dt>
              <dd>
                {{ selected.access_scope === "campus" ? "全校" : "所属院系" }}
              </dd>
            </div>
            <div>
              <dt>静态配置</dt>
              <dd>{{ selected.enabled ? "已启用" : "已停用" }}</dd>
            </div>
          </dl>
          <div class="section-heading">
            <h3>
              座位 <span class="hint">{{ seatTotal }} 个</span>
            </h3>
            <button
              :disabled="!canManage || saving || roomLoading || !!form"
              @click="openForm('seat')"
            >
              新增座位
            </button>
          </div>
          <form class="filters seat-filters" @submit.prevent="loadSeats(true)">
            <label class="sr-only" for="seat-search">搜索座位编号</label
            ><input
              id="seat-search"
              v-model="seatSearch"
              :disabled="!!form"
              placeholder="座位编号"
              maxlength="100"
            /><label class="sr-only" for="outlet-filter">按插座筛选</label
            ><select id="outlet-filter" v-model="outlet" :disabled="!!form">
              <option value="">全部插座类型</option>
              <option value="none">无插座</option>
              <option value="fixed">固定插座</option>
              <option value="rail">导轨插座</option></select
            ><button :disabled="seatLoading || !!form">筛选</button>
          </form>
          <p v-if="seatLoading" role="status">正在读取座位…</p>
          <div v-else-if="seatError" role="alert">
            <p>{{ seatError }}</p>
            <button class="secondary" @click="loadSeats()">重试读取座位</button>
          </div>
          <p v-else-if="!seatList.length" class="empty">没有符合条件的座位。</p>
          <div v-else class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>座位编号</th>
                  <th>插座</th>
                  <th>静态配置</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="seat in seatList" :key="seat.id">
                  <td>
                    <strong>{{ seat.code }}</strong>
                  </td>
                  <td>{{ outletLabel[seat.outlet_type] }}</td>
                  <td>{{ seat.enabled ? "已启用" : "已停用" }}</td>
                  <td>
                    <button
                      class="secondary"
                      :aria-label="`编辑座位 ${seat.code}`"
                      :disabled="!canManage || saving || roomLoading || !!form"
                      @click="openForm('seat', seat)"
                    >
                      编辑
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="pagination">
            <button
              class="secondary"
              :disabled="seatLoading || seatOffset === 0 || !!form"
              @click="seatPage(-1)"
            >
              上一页</button
            ><span>{{ Math.floor(seatOffset / 20) + 1 }}</span
            ><button
              class="secondary"
              :disabled="seatLoading || seatOffset + 20 >= seatTotal || !!form"
              @click="seatPage(1)"
            >
              下一页
            </button>
          </div>
        </template>
        <div v-else class="empty">
          <h2 id="seat-list-title">选择一间教室</h2>
          <p>在左侧选择教室后管理其中的座位。</p>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.workspace-heading,
.section-heading,
.actions,
.filters,
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.workspace-heading {
  margin: 24px 0;
}
.workspace-heading h1 {
  margin: 8px 0;
  font-size: 32px;
}
.workspace-heading p {
  margin: 0;
  color: #53685f;
}
.banner {
  padding: 16px 20px;
  border: 1px solid #cfbc86;
  background: #fff9e9;
  border-radius: 10px;
}
.notice {
  padding: 12px 18px;
  background: #e3efe6;
  border-radius: 8px;
}
.resource-columns {
  display: grid;
  grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
  gap: 24px;
  margin-top: 26px;
}
.room-panel,
.seat-panel,
.editor {
  padding: 24px;
  border: 1px solid #dce3dc;
  background: white;
  border-radius: 12px;
}
.editor {
  margin: 24px 0;
}
.editor form {
  display: grid;
  gap: 8px;
  max-width: 600px;
}
.editor label {
  font-weight: 600;
  margin-top: 8px;
}
.editor .actions {
  justify-content: flex-start;
  margin-top: 12px;
}
.editor [role="alert"],
[role="alert"] {
  color: #8d3429;
}
.section-heading h2,
.section-heading h3,
.section-heading p {
  margin: 0;
}
.filters {
  margin: 20px 0;
}
.filters input {
  min-width: 0;
  flex: 1;
}
input,
select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #aebeb5;
  border-radius: 6px;
  color: inherit;
  background: white;
  font: inherit;
}
input:focus-visible,
select:focus-visible,
a:focus-visible {
  outline: 3px solid #b7801d;
  outline-offset: 2px;
}
.secondary {
  background: white;
  color: #214e3d;
}
.room-list {
  list-style: none;
  padding: 0;
  margin: 12px 0;
}
.room-list li + li {
  margin-top: 10px;
}
.room-choice {
  display: grid;
  gap: 4px;
  width: 100%;
  text-align: left;
  white-space: normal;
  background: #fff;
  color: #17352d;
  border-color: #dce3dc;
  padding: 14px;
}
.room-choice.selected {
  background: #e8f0e9;
  border-color: #36594a;
}
.room-choice span {
  font-size: 13px;
  color: #53685f;
}
.room-code {
  letter-spacing: 0.04em;
}
.room-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  padding: 18px 0;
  border-bottom: 1px solid #e2e8e2;
  margin-bottom: 22px;
}
.room-facts dt {
  color: #53685f;
  font-size: 13px;
}
.room-facts dd {
  margin: 0;
  font-weight: 600;
}
.seat-filters select {
  max-width: 170px;
}
.table-scroll {
  overflow: auto;
}
table {
  border-collapse: collapse;
  width: 100%;
  text-align: left;
}
th,
td {
  padding: 12px;
  border-bottom: 1px solid #e3e8e3;
}
th {
  font-size: 13px;
  color: #53685f;
}
.pagination {
  justify-content: center;
  margin-top: 22px;
}
.pagination button {
  font-size: 13px;
  padding: 6px 12px;
}
.empty {
  padding: 28px 0;
  color: #53685f;
}
.back {
  color: #36594a;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
button:disabled {
  cursor: not-allowed;
}
@media (max-width: 760px) {
  .resource-columns {
    grid-template-columns: 1fr;
  }
  .workspace-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .room-panel,
  .seat-panel,
  .editor {
    padding: 18px;
  }
  .seat-filters {
    flex-wrap: wrap;
  }
  .seat-filters select {
    max-width: none;
    flex: 1;
  }
  .room-facts {
    gap: 18px;
  }
  .section-heading {
    flex-wrap: wrap;
  }
  .resource-workspace {
    padding-top: 28px;
  }
}
</style>
