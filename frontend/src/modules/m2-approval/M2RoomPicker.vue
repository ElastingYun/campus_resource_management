<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { GatewayMessage } from "./models";
import type { RoomOption, RoomOptionsPage, RoomOptionsQuery } from "./models";
const props = defineProps<{
  loadPage: (query?: RoomOptionsQuery) => Promise<RoomOptionsPage>;
  disabled: boolean;
}>();
const emit = defineEmits<{ select: [room: RoomOption | undefined] }>();
const query = ref(""),
  appliedQuery = ref(""),
  selected = ref(""),
  loading = ref(false),
  error = ref("");
const page = ref<RoomOptionsPage>();
let request = 0;
async function load(offset = 0, q = appliedQuery.value) {
  if (props.disabled) return;
  const sequence = ++request;
  selected.value = "";
  emit("select", undefined);
  page.value = undefined;
  loading.value = true;
  error.value = "";
  try {
    const value = await props.loadPage({ q, limit: 20, offset });
    if (sequence !== request) return;
    page.value = value;
    appliedQuery.value = q;
  } catch (cause) {
    if (sequence === request)
      error.value =
        cause instanceof GatewayMessage
          ? cause.message
          : "暂时无法查询教室，请重新查询。";
  } finally {
    if (sequence === request) loading.value = false;
  }
}
function select() {
  emit(
    "select",
    page.value?.items.find((room) => room.id === selected.value),
  );
}
onMounted(() => load(0, ""));
onUnmounted(() => {
  request++;
});
</script>
<template>
  <section class="room-picker" aria-label="授权教室目录">
    <label for="m2-room-query">搜索教室</label>
    <div class="room-query">
      <input
        id="m2-room-query"
        v-model="query"
        maxlength="100"
        :disabled="disabled"
        placeholder="教室编号、名称或位置"
        @keydown.enter.prevent="load(0, query.trim())"
      /><button
        type="button"
        :disabled="disabled"
        @click="load(0, query.trim())"
      >
        查询教室
      </button>
    </div>
    <p v-if="loading" role="status">正在查询授权教室…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="page && !page.items.length" class="muted">
      没有符合条件的授权教室，请调整搜索条件。
    </p>
    <label for="m2-room">选择教室</label>
    <select
      id="m2-room"
      v-model="selected"
      :disabled="disabled || loading || !page?.items.length"
      @change="select"
    >
      <option value="">请选择本页教室</option>
      <option v-for="room in page?.items" :key="room.id" :value="room.id">
        {{ room.code }} · {{ room.name }} · {{ room.location }}
      </option>
    </select>
    <nav v-if="page" aria-label="教室目录分页">
      <button
        type="button"
        :disabled="disabled || loading || page.offset === 0"
        @click="load(Math.max(0, page.offset - page.limit))"
      >
        上一页教室
      </button>
      <span
        >第 {{ Math.floor(page.offset / page.limit) + 1 }} 页 · 共
        {{ Math.max(1, Math.ceil(page.total / page.limit)) }} 页 · 符合范围
        {{ page.total }} 间</span
      >
      <button
        type="button"
        :disabled="
          disabled || loading || page.offset + page.limit >= page.total
        "
        @click="load(page.offset + page.limit)"
      >
        下一页教室
      </button>
    </nav>
    <p class="muted">
      目录由服务端按权限过滤；查询或翻页后请重新选择。可选择不代表时段可用，提交仍由服务端重新校验。
    </p>
  </section>
</template>
<style scoped>
.room-picker {
  margin: 1rem 0;
  border: 1px solid #d6e2dc;
  border-radius: 9px;
  padding: 1rem;
}
label {
  display: block;
  font-weight: 600;
  margin: 0.65rem 0 0.4rem;
}
.room-query {
  display: flex;
  gap: 0.6rem;
}
input,
select {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 0.7rem;
  border: 1px solid #bccdc5;
  border-radius: 7px;
  font: inherit;
}
button {
  padding: 0.55rem 0.8rem;
  border: 1px solid #b6cbc0;
  color: #28584d;
  background: white;
  border-radius: 7px;
  cursor: pointer;
  white-space: nowrap;
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
nav {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.7rem;
  margin: 0.8rem 0;
}
nav span,
.muted {
  font-size: 0.85rem;
  color: #526b61;
  line-height: 1.6;
}
[role="alert"] {
  color: #9c3c24;
}
@media (max-width: 480px) {
  .room-query {
    flex-wrap: wrap;
  }
}
</style>
