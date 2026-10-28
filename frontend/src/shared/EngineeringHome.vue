<script setup lang="ts">
import { onMounted, ref } from "vue";

type HealthState = "checking" | "ready" | "not_ready" | "unreachable";
const state = ref<HealthState>("checking");
const labels: Record<HealthState, string> = {
  checking: "正在检查工程服务…",
  ready: "工程后端与数据库连接正常",
  not_ready: "后端已响应，数据库尚未就绪",
  unreachable: "暂时无法获取工程状态，请检查后端或代理后重试",
};

async function checkHealth() {
  state.value = "checking";
  try {
    const response = await fetch("/health/ready", {
      signal: AbortSignal.timeout(5000),
    });
    const data: unknown = await response.json();
    if (typeof data !== "object" || data === null || !("status" in data)) {
      throw new Error("Unexpected health response");
    }
    if (response.ok && data.status === "ready") state.value = "ready";
    else if (response.status === 503 && data.status === "not_ready")
      state.value = "not_ready";
    else throw new Error("Unexpected health status");
  } catch {
    state.value = "unreachable";
  }
}

onMounted(checkHealth);
</script>

<template>
  <main>
    <p class="eyebrow">校园资源服务平台 · 工程初始化</p>
    <h1>让校园资源使用有序可查</h1>
    <p class="intro">
      统一工程已经有了入口。预约、审批与报修将由各模块成员逐步接入。
    </p>
    <section class="health" aria-labelledby="health-heading">
      <div>
        <h2 id="health-heading">工程状态</h2>
        <p role="status" aria-live="polite">{{ labels[state] }}</p>
        <p class="hint">此状态仅检查基础服务，不代表业务功能已完成。</p>
      </div>
      <button :disabled="state === 'checking'" @click="checkHealth">
        重新检查
      </button>
    </section>
    <div class="modules">
      <section>
        <span>M1</span>
        <h2>自习座位预约</h2>
        <p>搜索座位、预约、签到与使用记录。</p>
        <small>业务未接入</small>
        <p><a href="#resources-prototype">教室与座位管理演示 →</a></p>
        <a href="#resources">打开资源管理</a>
      </section>
      <section>
        <span>M2</span>
        <h2>整教室申请与审批</h2>
        <p>提交教室申请，跟踪审批与占用结果。</p>
        <small>业务未接入 · D 负责前端</small>
        <p><a href="#m2-prototype">查看交互原型 →</a></p>
        <a href="#m2">打开申请工作台</a>
      </section>
      <section>
        <span>M3</span>
        <h2>物业报修工单</h2>
        <p>故障上报、维修进度与验收评价。</p>
        <small>业务未接入</small>
      </section>
    </div>
    <footer>开发与演示使用合成数据。业务规则和接口由团队评审确认。</footer>
  </main>
</template>
