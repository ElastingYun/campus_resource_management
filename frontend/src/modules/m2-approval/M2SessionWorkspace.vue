<script setup lang="ts">
import { computed, ref } from "vue";
import M2Workspace from "./M2Workspace.vue";
import type { CSession } from "./c-session";
import type { createCGateway } from "./c-gateway";
import { GatewayMessage } from "./models";
const props = defineProps<{
  session: CSession;
  gateway: ReturnType<typeof createCGateway>;
}>();
const identity = computed(() => props.session.state.value?.identity);
const username = ref(""),
  password = ref(""),
  busy = ref(false),
  error = ref("");
async function login() {
  if (busy.value) return;
  if (!username.value.trim() || !password.value) {
    error.value = "请输入账号和密码。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await props.session.login(username.value, password.value);
  } catch (cause) {
    error.value =
      cause instanceof GatewayMessage ? cause.message : "登录暂不可用。";
  } finally {
    password.value = "";
    busy.value = false;
  }
}
async function logout() {
  if (busy.value) return;
  busy.value = true;
  await props.session.logout();
  busy.value = false;
}
</script>
<template>
  <template v-if="identity"
    ><div class="session-bar">
      <span
        >当前院系：{{ identity.department_id }} · 账号
        {{ identity.subject_id.slice(0, 8) }}…</span
      ><button :disabled="busy" @click="logout">退出登录</button>
    </div>
    <M2Workspace :key="identity.subject_id" :gateway="gateway"
  /></template>
  <main v-else class="sign-in">
    <a href="#">← 平台首页</a>
    <section class="login-card">
      <p>整教室申请与审批</p>
      <h1>登录申请工作台</h1>
      <p>使用由管理员配置的账号。登录后仅展示服务端授权的数据和操作。</p>
      <p v-if="session.notice.value" role="status">
        {{ session.notice.value }}
      </p>
      <p v-if="error" class="login-error" role="alert">{{ error }}</p>
      <form @submit.prevent="login">
        <label for="m2-username">账号</label
        ><input
          id="m2-username"
          v-model="username"
          autocomplete="username"
          :disabled="busy"
          required
        /><label for="m2-password">密码</label
        ><input
          id="m2-password"
          v-model="password"
          type="password"
          autocomplete="off"
          :disabled="busy"
          required
        /><button type="submit" :disabled="busy">
          {{ busy ? "正在登录…" : "登录" }}
        </button>
      </form>
      <p class="session-hint">会话仅保存在本页内存中，刷新后需要重新登录。</p>
      <a href="#m2-prototype">查看合成数据交互原型 →</a>
    </section>
  </main>
</template>
<style scoped>
.session-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 10px 28px;
  background: #dfece5;
  font-size: 13px;
}
.session-bar button {
  padding: 6px 12px;
  font-size: 13px;
}
.sign-in {
  max-width: 560px;
  padding: 36px 20px;
  margin: auto;
}
.sign-in a {
  color: #315e4c;
}
.login-card {
  margin-top: 30px;
  background: white;
  padding: 32px;
  border: 1px solid #d4e0d5;
  border-radius: 14px;
}
.login-card h1 {
  font-size: 30px;
}
.login-card p {
  font-size: 14px;
  color: #63786b;
}
.login-card label {
  display: block;
  margin: 20px 0 7px;
}
.login-card input {
  width: 100%;
  padding: 12px;
  border: 1px solid #c0d2c5;
  border-radius: 6px;
  font: inherit;
}
.login-card button {
  margin-top: 26px;
  width: 100%;
}
.login-error {
  background: #fbe8e1;
  padding: 12px;
  color: #953b2e !important;
}
.session-hint {
  font-size: 12px !important;
}
@media (max-width: 600px) {
  .session-bar {
    padding: 10px 16px;
    font-size: 12px;
  }
  .login-card {
    padding: 24px;
  }
}
</style>
