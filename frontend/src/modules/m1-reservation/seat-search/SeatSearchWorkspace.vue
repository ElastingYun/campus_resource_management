<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import BookingPanel from "../booking/BookingPanel.vue";
import { createBookingFlow } from "../booking/flow";
import { createUnconfiguredBookingGateway } from "../booking/gateway";
import { createPrototypeBookingGateway } from "../booking/prototype";
import { BookingError, selectBooking } from "../booking/models";
import type { BookingGateway } from "../booking/models";
import type { BookingSession } from "../booking/session";
import {
  businessDate,
  outletLabels,
  reasonLabel,
  SearchError,
  validQuery,
} from "./models";
import type {
  SearchResult,
  SearchSettings,
  SearchSeat,
  SeatQuery,
  SeatSearchGateway,
} from "./models";

const props = defineProps<{
  gateway: SeatSearchGateway;
  bookingGateway?: BookingGateway;
  bookingSession?: BookingSession;
}>();
const emit = defineEmits<{ bookingPending: [pending: boolean] }>();
const requestedBooking =
  props.bookingGateway ??
  (props.gateway.mode === "prototype"
    ? createPrototypeBookingGateway()
    : createUnconfiguredBookingGateway());
const retainedSession =
  props.bookingSession?.mode === props.gateway.mode
    ? props.bookingSession
    : undefined;
const bookingGateway =
  !props.bookingSession &&
  requestedBooking.mode === "prototype" &&
  props.gateway.mode === "prototype"
    ? requestedBooking
    : createUnconfiguredBookingGateway();
const bookingMode = retainedSession?.mode ?? bookingGateway.mode;
const localBooking = createBookingFlow(bookingGateway);
const booking = computed(() => retainedSession?.current ?? localBooking);
watch(
  () => retainedSession?.pending ?? booking.value.pending,
  (pending) => emit("bookingPending", pending),
  { immediate: true, flush: "sync" },
);
const leavingWarning = ref(false);
const canBook = computed(
  () =>
    bookingMode !== "unconfigured" &&
    (!retainedSession || retainedSession.current !== null),
);
const settings = ref<SearchSettings>();
const loadingSettings = ref(false),
  searching = ref(false),
  error = ref("");
const result = ref<SearchResult>();
const rooms = ref<{ id: string; label: string }[]>([]);
const query = reactive<SeatQuery>({
  date: props.gateway.businessTimeZone
    ? businessDate(
        new Date(Date.now() + 86400000),
        props.gateway.businessTimeZone,
      )
    : "",
  hour: 9,
  hours: 1,
  outlet: "",
  roomId: "",
  onlyAvailable: false,
});
let generation = 0,
  settingsGeneration = 0;
let searchController: AbortController | undefined,
  settingsController: AbortController | undefined;
const disabled = computed(
  () =>
    props.gateway.mode === "unconfigured" ||
    !settings.value ||
    loadingSettings.value ||
    booking.value.active,
);
const availableCount = computed(
  () =>
    result.value?.seats.filter((seat) => seat.status === "available").length ??
    0,
);
function invalidate() {
  if (booking.value.active) return;
  generation++;
  searchController?.abort();
  searching.value = false;
  result.value = undefined;
  error.value = "";
}
function chooseSeat(seat: SearchSeat) {
  if (!result.value || booking.value.active || !canBook.value) return;
  try {
    if (!booking.value.open(selectBooking(seat, result.value)))
      error.value = "请先登录后预约。";
  } catch (cause) {
    error.value =
      cause instanceof BookingError ? cause.message : "请重新查询座位。";
  }
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (retainedSession?.pending ?? booking.value.pending) {
    event.preventDefault();
    event.returnValue = "";
  }
}
function guardNavigation(event: MouseEvent) {
  if (
    booking.value.pending &&
    event.target instanceof Element &&
    event.target.closest("a[href]") &&
    !(
      retainedSession &&
      event.target.closest("a[href]")!.getAttribute("href")?.startsWith("#")
    )
  ) {
    event.preventDefault();
    leavingWarning.value = true;
  }
}
function closeBooking() {
  leavingWarning.value = false;
  invalidate();
}
function message(cause: unknown) {
  return cause instanceof SearchError
    ? cause.message
    : "查询服务暂时不可用，请稍后重试。";
}
async function loadSettings() {
  invalidate();
  settings.value = undefined;
  rooms.value = [];
  query.roomId = "";
  const current = ++settingsGeneration;
  settingsController?.abort();
  settingsController = new AbortController();
  loadingSettings.value = true;
  try {
    const loaded = await props.gateway.loadSettings(settingsController.signal);
    if (current !== settingsGeneration) return;
    settings.value = loaded;
    query.hours = Math.min(query.hours || 1, loaded.maxHours);
  } catch (cause) {
    if (current === settingsGeneration) error.value = message(cause);
  } finally {
    if (current === settingsGeneration) loadingSettings.value = false;
  }
}
async function search() {
  if (disabled.value || searching.value) return;
  invalidate();
  if (!validQuery(query, settings.value!)) {
    error.value = `请填写有效日期、0–23 点的整点和 1–${settings.value!.maxHours} 小时的时长。`;
    return;
  }
  const current = generation;
  searchController = new AbortController();
  searching.value = true;
  try {
    const loaded = await props.gateway.search(
      { ...query },
      searchController.signal,
    );
    if (current !== generation) return;
    result.value = loaded;
    // Only build a room selector from results returned by the user's authorized search.
    if (!query.roomId)
      rooms.value = [
        ...new Map(
          loaded.seats.map((seat) => [
            seat.roomId,
            {
              id: seat.roomId,
              label: `${seat.roomCode} · ${seat.roomName}`,
            },
          ]),
        ).values(),
      ];
  } catch (cause) {
    if (current === generation) {
      error.value = message(cause);
      rooms.value = [];
      query.roomId = "";
    }
  } finally {
    if (current === generation) searching.value = false;
  }
}
function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: props.gateway.businessTimeZone!,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "shortOffset",
  }).format(new Date(value));
}
watch(
  () => retainedSession?.currentActorId,
  (actor) => {
    generation++;
    settingsGeneration++;
    searchController?.abort();
    settingsController?.abort();
    searching.value = false;
    loadingSettings.value = false;
    result.value = undefined;
    rooms.value = [];
    settings.value = undefined;
    error.value = "";
    if (actor) void loadSettings();
  },
  { flush: "sync" },
);
onMounted(() => {
  window.addEventListener("beforeunload", beforeUnload);
  if (props.gateway.mode !== "unconfigured") void loadSettings();
});
onUnmounted(() => {
  window.removeEventListener("beforeunload", beforeUnload);
  // The application-owned session, including requests in flight, survives route destruction.
  localBooking.dispose();
  generation++;
  settingsGeneration++;
  searchController?.abort();
  settingsController?.abort();
});
</script>

<template>
  <main class="seat-search" @click.capture="guardNavigation">
    <header class="search-heading">
      <div>
        <a href="#">← 返回首页</a>
        <p class="eyebrow">M1 · 自习座位</p>
        <h1>找一个适合学习的位置</h1>
        <p>选好时间，查看座位及当前不可用原因。</p>
      </div>
      <a class="manage-link" href="#resources">资源管理 →</a>
    </header>
    <aside
      v-if="gateway.mode === 'prototype'"
      class="search-banner"
      role="note"
    >
      <strong>合成数据演示</strong> ·
      座位状态为固定示例，不随时段计算；预约仅记录在页面内存，不修改真实数据。
    </aside>
    <aside
      v-else-if="gateway.mode === 'unconfigured'"
      class="search-banner"
      role="status"
    >
      <strong>座位查询尚未接入</strong> · 服务配置完成后开放查询。<a
        href="#seat-search-prototype"
        >查看合成演示</a
      >
    </aside>
    <form
      class="search-form"
      novalidate
      @submit.prevent="search"
      @input="invalidate"
      @change="invalidate"
    >
      <div class="form-heading">
        <h2>查询条件</h2>
        <span v-if="gateway.businessTimeZone"
          >业务时区：{{ gateway.businessTimeZone }}</span
        >
      </div>
      <fieldset :disabled="disabled">
        <div class="search-fields">
          <label for="search-date"
            >日期<input
              id="search-date"
              v-model="query.date"
              type="date"
              required
          /></label>
          <label for="search-hour"
            >开始整点<select id="search-hour" v-model.number="query.hour">
              <option v-for="hour in 24" :key="hour" :value="hour - 1">
                {{ String(hour - 1).padStart(2, "0") }}:00
              </option>
            </select></label
          >
          <label for="search-hours"
            >时长（小时）<input
              id="search-hours"
              v-model.number="query.hours"
              type="number"
              min="1"
              :max="settings?.maxHours"
              step="1"
              required
          /></label>
          <label for="search-outlet"
            >插座<select id="search-outlet" v-model="query.outlet">
              <option value="">不限插座</option>
              <option
                v-for="(label, value) in outletLabels"
                :key="value"
                :value="value"
              >
                {{ label }}
              </option>
            </select></label
          >
          <label for="search-room"
            >教室<select id="search-room" v-model="query.roomId">
              <option value="">全部查询结果中的教室</option>
              <option v-for="room in rooms" :key="room.id" :value="room.id">
                {{ room.label }}
              </option>
            </select></label
          >
        </div>
        <div class="search-actions">
          <label class="checkbox"
            ><input
              v-model="query.onlyAvailable"
              type="checkbox"
            />仅看可用座位</label
          ><button type="submit" :disabled="disabled || searching">
            {{ searching ? "查询中…" : "查询座位" }}
          </button>
        </div>
      </fieldset>
      <p v-if="settings" class="search-hint">
        {{
          gateway.mode === "prototype" ? "演示规则" : "服务当前规则"
        }}：单次最多 {{ settings.maxHours }} 小时，可预约
        {{ settings.bookingHorizonDays }}
        天内时段。日期、开放时间及准入由服务端最终校验。
      </p>
      <p class="search-hint">
        先查询全部教室，再按返回的教室筛选。查询结果仅代表该次响应，预约提交时需重新校验。
      </p>
    </form>
    <BookingPanel
      v-if="gateway.businessTimeZone"
      :flow="booking"
      :time-zone="gateway.businessTimeZone"
      :prototype="bookingMode === 'prototype'"
      :retained="!!retainedSession"
      @closed="closeBooking"
    />
    <p
      v-if="leavingWarning && booking.pending"
      class="search-error"
      role="alert"
    >
      请先核对原预约结果，再离开当前页面。
    </p>
    <div v-if="loadingSettings" class="search-state" role="status">
      正在读取预约规则…
    </div>
    <div v-if="error" class="search-error" role="alert">
      <p>{{ error }}</p>
      <button
        v-if="!settings && gateway.mode !== 'unconfigured'"
        :disabled="loadingSettings"
        @click="loadSettings"
      >
        重新读取规则
      </button>
    </div>
    <div v-if="searching" class="search-state" role="status">
      正在查询座位… <button @click="invalidate">取消查询</button>
    </div>
    <section
      v-else-if="result"
      class="search-results"
      aria-labelledby="search-result-title"
    >
      <div class="result-heading">
        <div>
          <h2 id="search-result-title">
            {{ result.seats.length }} 个座位 · {{ availableCount }} 个可用
          </h2>
          <p>
            {{ formatTime(result.startAt) }} → {{ formatTime(result.endAt) }} ·
            {{ result.hours }} 小时
          </p>
        </div>
        <span>{{
          canBook
            ? bookingMode === "prototype"
              ? "合成预约演示"
              : "选择可用座位继续预约"
            : "仅查询 · 预约提交待接入"
        }}</span>
      </div>
      <p v-if="result.seats.length === 0" class="search-state" role="status">
        没有符合条件的座位，请调整时间、教室或插座条件。
      </p>
      <div v-else class="seat-cards">
        <article
          v-for="seat in result.seats"
          :key="seat.id"
          class="seat-card"
          :data-status="seat.status"
        >
          <div class="seat-card-top">
            <span>{{ seat.roomCode }}</span
            ><strong class="seat-status">{{
              seat.status === "available"
                ? "可用"
                : seat.status === "unavailable"
                  ? "不可用"
                  : "状态未知"
            }}</strong>
          </div>
          <h3>{{ seat.code }} <small>号座位</small></h3>
          <p>{{ seat.roomName }}</p>
          <p class="outlet">{{ outletLabels[seat.outlet] }}</p>
          <ul v-if="seat.reasons.length">
            <li v-for="reason in seat.reasons" :key="reason">
              {{ reasonLabel(reason) }}
            </li>
          </ul>
          <p v-if="seat.status === 'unknown'" class="unknown-note">
            可用性未确认，不能据此预约。
          </p>
          <button
            :disabled="
              seat.status !== 'available' || !canBook || booking.active
            "
            :aria-label="`预约 ${seat.roomCode} ${seat.code} 号座位`"
            @click="chooseSeat(seat)"
          >
            选择此座位
          </button>
        </article>
      </div>
    </section>
    <div
      v-else-if="
        !searching &&
        !loadingSettings &&
        !error &&
        gateway.mode !== 'unconfigured'
      "
      class="search-state"
    >
      选择条件后点击“查询座位”。
    </div>
  </main>
</template>

<style scoped>
.seat-search {
  max-width: 1160px;
  margin: 0 auto;
  padding: 36px 24px 64px;
}
.search-heading,
.form-heading,
.search-actions,
.result-heading,
.seat-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
.search-heading {
  align-items: flex-start;
  margin-bottom: 26px;
}
.search-heading h1 {
  margin: 12px 0;
  font-size: clamp(26px, 4vw, 38px);
}
.search-heading p,
.result-heading p {
  color: #526661;
}
.manage-link {
  margin-top: 36px;
  white-space: nowrap;
}
.search-banner {
  background: #fff3d6;
  border: 1px solid #e5cb8a;
  border-radius: 12px;
  padding: 14px 18px;
  margin-bottom: 22px;
  color: #634c19;
}
.search-form {
  background: white;
  border: 1px solid #d9e2dc;
  border-radius: 18px;
  padding: 24px;
}
.form-heading h2,
.result-heading h2 {
  margin: 0 0 12px;
  font-size: 20px;
}
.form-heading span,
.result-heading span {
  font-size: 13px;
  color: #526661;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 12px 0;
  min-width: 0;
}
.search-fields {
  display: grid;
  grid-template-columns: 1.3fr 1fr 1fr 1.2fr 1.8fr;
  gap: 14px;
}
.search-fields label {
  display: grid;
  gap: 8px;
  color: #3a524a;
  font-size: 14px;
}
.search-fields input,
.search-fields select {
  width: 100%;
  min-width: 0;
  border: 1px solid #bccdc3;
  border-radius: 8px;
  padding: 10px 8px;
  background: #fff;
  color: #173d30;
  font: inherit;
}
.search-actions {
  margin-top: 20px;
}
.checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}
.checkbox input {
  width: 17px;
  height: 17px;
  accent-color: #245b42;
}
button {
  border: 1px solid #245b42;
  border-radius: 8px;
  background: #245b42;
  color: #fff;
  padding: 10px 18px;
  cursor: pointer;
  font: inherit;
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.search-hint {
  font-size: 13px;
  color: #65766b;
  line-height: 1.7;
  margin: 8px 0 0;
}
.search-error {
  background: #fff0ed;
  color: #8b3025;
  border-radius: 12px;
  padding: 16px 20px;
  margin-top: 20px;
}
.search-state {
  padding: 32px 12px;
  color: #526661;
  text-align: center;
}
.search-results {
  margin-top: 30px;
}
.result-heading {
  align-items: flex-start;
  margin-bottom: 20px;
}
.result-heading p {
  font-size: 14px;
  line-height: 1.6;
  margin: 0;
}
.seat-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.seat-card {
  background: white;
  border: 1px solid #d9e2dc;
  border-radius: 14px;
  padding: 20px;
  border-top: 4px solid #8e9b94;
}
.seat-card[data-status="available"] {
  border-top-color: #3b8758;
}
.seat-card[data-status="unavailable"] {
  border-top-color: #b08243;
}
.seat-card-top {
  font-size: 13px;
  color: #526661;
}
.seat-status {
  border-radius: 20px;
  background: #eef1ee;
  padding: 5px 10px;
}
[data-status="available"] .seat-status {
  background: #e2f2e5;
  color: #286039;
}
[data-status="unavailable"] .seat-status {
  background: #fbefdc;
  color: #856023;
}
.seat-card h3 {
  font-size: 28px;
  margin: 22px 0 12px;
}
.seat-card h3 small {
  font-size: 14px;
  font-weight: 400;
  color: #65766b;
}
.seat-card p {
  font-size: 14px;
  color: #526661;
}
.seat-card .outlet {
  display: inline-block;
  background: #f3f5ef;
  padding: 5px 9px;
  border-radius: 5px;
}
.seat-card ul {
  padding-left: 20px;
  font-size: 13px;
  color: #785324;
  line-height: 1.9;
}
.unknown-note {
  border-top: 1px solid #e3e8e2;
  padding-top: 12px;
}
@media (max-width: 900px) {
  .search-fields {
    grid-template-columns: repeat(2, 1fr);
  }
  .seat-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 560px) {
  .seat-search {
    padding: 22px 16px;
  }
  .search-heading,
  .form-heading,
  .result-heading {
    flex-direction: column;
    gap: 8px;
  }
  .manage-link {
    margin-top: 0;
  }
  .search-form {
    padding: 18px;
  }
  .search-fields,
  .seat-cards {
    grid-template-columns: 1fr;
  }
}
</style>
