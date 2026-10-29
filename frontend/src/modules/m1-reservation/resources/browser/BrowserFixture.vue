<script setup lang="ts">
import { onUnmounted, ref } from "vue";
import { createCSession } from "../../../m2-approval/c-session";
import { createAuthenticatedResourceAccess } from "../access";
import { protectResourceSession } from "../session";
import ResourceWorkspace from "../ResourceWorkspace.vue";

// Isolated acceptance host; reuses D's public C client instead of adding login.
const c = createCSession();
const account = ref(""),
  password = ref(""),
  error = ref(""),
  busy = ref(false);
const screen = ref<"resources" | "placeholder">("resources");
const transport: typeof fetch = async (input, init) => {
  const response = await fetch(input, init);
  if (response.status === 401) {
    const authorization = new Headers(init?.headers).get("Authorization");
    if (authorization?.startsWith("Bearer "))
      c.invalidate(authorization.slice(7));
  }
  return response;
};
const access = createAuthenticatedResourceAccess({
  getSession: () => {
    const current = c.state.value;
    if (!current) return null;
    return {
      subjectId: current.identity.subject_id,
      accessToken: current.accessToken,
      permissions: current.identity.permissions,
      dataScopes: {
        allRooms: current.identity.data_scopes.all_rooms,
        roomIds: current.identity.data_scopes.room_ids,
      },
    };
  },
  permissions: {
    read: "synthetic.resource.read",
    manage: "synthetic.resource.manage",
    createRooms: "synthetic.resource.create",
  },
  request: transport,
});
const unprotect = protectResourceSession(access.session);
onUnmounted(unprotect);
async function login() {
  if (busy.value) return;
  error.value = "";
  if (!["b-manager", "b-reader", "b-scoped"].includes(account.value)) {
    password.value = "";
    error.value = "此隔离夹具只接受已准备的合成账号。";
    return;
  }
  busy.value = true;
  try {
    await c.login(account.value, password.value);
    screen.value = "resources";
  } catch {
    error.value = "合成账号登录未完成，请检查测试服务。";
  } finally {
    password.value = "";
    busy.value = false;
  }
}
async function logout() {
  await c.logout();
}
</script>
<template>
  <div class="fixture">
    <header class="fixture-header">
      <strong>资源管理 · 隔离浏览器验收</strong>
      <span>仅合成账号和临时数据</span>
      <template v-if="c.state.value">
        <button type="button" @click="screen = 'resources'">资源管理</button>
        <button type="button" @click="screen = 'placeholder'">
          切到验收占位页
        </button>
        <button type="button" @click="logout">退出登录</button>
      </template>
    </header>
    <section v-if="!c.state.value" class="fixture-login">
      <h1>登录隔离资源验收</h1>
      <form @submit.prevent="login">
        <label for="b-test-account">账号</label>
        <input
          id="b-test-account"
          v-model="account"
          autocomplete="off"
          :disabled="busy"
        />
        <label for="b-test-password">密码</label>
        <input
          id="b-test-password"
          v-model="password"
          type="password"
          autocomplete="off"
          :disabled="busy"
        />
        <button :disabled="busy">登录</button>
      </form>
      <p v-if="error" role="alert">{{ error }}</p>
    </section>
    <template v-else>
      <ResourceWorkspace
        v-if="screen === 'resources'"
        :gateway="access.gateway"
        :resource-session="access.session"
      />
      <section v-else class="fixture-placeholder">
        <h1>验收占位页</h1>
        <p>资源组件已卸载，宿主持有原会话。</p>
      </section>
    </template>
    <p v-if="c.notice.value" role="status">{{ c.notice.value }}</p>
  </div>
</template>
<style scoped>
.fixture {
  color: #203c32;
  font-family: system-ui, sans-serif;
  background: #f5f8f5;
  min-height: 100vh;
}
.fixture-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid #cddbd1;
}
.fixture-header span {
  font-size: 13px;
}
button {
  cursor: pointer;
  padding: 8px 12px;
}
.fixture-login {
  max-width: 340px;
  padding: 24px;
  margin: auto;
}
.fixture-login form {
  display: grid;
  gap: 12px;
}
.fixture-login input {
  padding: 8px;
  min-width: 0;
}
.fixture-placeholder {
  padding: 24px;
}
</style>
