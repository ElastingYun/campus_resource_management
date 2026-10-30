<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import EngineeringHome from "./shared/EngineeringHome.vue";
import CSessionFrame from "./shared/CSessionFrame.vue";
import M2Workspace from "./modules/m2-approval/M2Workspace.vue";
import M2SessionWorkspace from "./modules/m2-approval/M2SessionWorkspace.vue";
import { createCSession } from "./modules/m2-approval/c-session";
import { createCGateway } from "./modules/m2-approval/c-gateway";
import ResourceWorkspace from "./modules/m1-reservation/resources/ResourceWorkspace.vue";
import SeatSearchWorkspace from "./modules/m1-reservation/seat-search/SeatSearchWorkspace.vue";
import { createPrototypeSeatSearchGateway } from "./modules/m1-reservation/seat-search/prototype";
import { createUnconfiguredSeatSearchGateway } from "./modules/m1-reservation/seat-search/gateway";
import { createPrototypeResourceGateway } from "./modules/m1-reservation/resources/prototype";
import { createUnconfiguredResourceGateway } from "./modules/m1-reservation/resources/gateway";
import {
  createCResourceAccess,
  parseResourcePermissions,
} from "./modules/m1-reservation/resources/host";
import { protectResourceSession } from "./modules/m1-reservation/resources/session";
import {
  createPrototypeGateway,
  createUnconfiguredGateway,
} from "./modules/m2-approval/gateways";

const cSession = createCSession();
const cGateway = createCGateway(cSession);
const resourcePermissions = parseResourcePermissions(
  import.meta.env.VITE_RESOURCE_PERMISSIONS,
);
const resourceAccess = resourcePermissions
  ? createCResourceAccess(cSession, resourcePermissions)
  : null;
let stopResourceProtection = () => {};
const warnPending = (event: BeforeUnloadEvent) => {
  if (cGateway.hasAnyPending()) {
    event.preventDefault();
    event.returnValue = "";
  }
};
const screen = ref(window.location.hash);
const updateScreen = () => {
  screen.value = window.location.hash;
};
const isM2 = computed(() => ["#m2", "#m2-prototype"].includes(screen.value));
const isSeatSearch = computed(() =>
  ["#seat-search", "#seat-search-prototype"].includes(screen.value),
);
const seatSearchGateway = computed(() =>
  screen.value === "#seat-search-prototype"
    ? createPrototypeSeatSearchGateway()
    : createUnconfiguredSeatSearchGateway(),
);
const isResources = computed(() =>
  ["#resources", "#resources-prototype"].includes(screen.value),
);
const resourceGateway = computed(() =>
  screen.value === "#resources-prototype"
    ? createPrototypeResourceGateway()
    : createUnconfiguredResourceGateway(),
);
const gateway = computed(() =>
  screen.value === "#m2-prototype"
    ? createPrototypeGateway()
    : createUnconfiguredGateway(),
);
onMounted(() => {
  if (resourceAccess)
    stopResourceProtection = protectResourceSession(resourceAccess.session);
  window.addEventListener("hashchange", updateScreen);
  window.addEventListener("beforeunload", warnPending);
});
onUnmounted(() => {
  stopResourceProtection();
  window.removeEventListener("hashchange", updateScreen);
  window.removeEventListener("beforeunload", warnPending);
});
</script>

<template>
  <nav
    v-if="screen === '#m2' || screen === '#resources'"
    class="workspace-nav"
    aria-label="业务导航"
  >
    <a href="#">平台首页</a>
    <a href="#m2">整教室申请与审批</a>
    <a href="#resources">资源管理</a>
  </nav>
  <M2SessionWorkspace
    v-if="screen === '#m2'"
    :session="cSession"
    :gateway="cGateway"
  />
  <M2Workspace v-else-if="isM2" :key="screen" :gateway="gateway" />
  <SeatSearchWorkspace
    v-else-if="isSeatSearch"
    :key="screen"
    :gateway="seatSearchGateway"
  />
  <CSessionFrame
    v-else-if="screen === '#resources' && resourceAccess"
    :session="cSession"
    title="教室与座位管理"
    heading="登录资源管理"
    prototype-href="#resources-prototype"
  >
    <ResourceWorkspace
      :gateway="resourceAccess.gateway"
      :resource-session="resourceAccess.session"
    />
  </CSessionFrame>
  <ResourceWorkspace
    v-else-if="isResources"
    :key="screen"
    :gateway="resourceGateway"
  />
  <EngineeringHome v-else />
</template>

<style scoped>
.workspace-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding: 12px 24px;
  background: #f3f7f4;
}
.workspace-nav a {
  color: #315e4c;
  font-size: 14px;
}
</style>
