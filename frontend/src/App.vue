<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import EngineeringHome from "./shared/EngineeringHome.vue";
import M2Workspace from "./modules/m2-approval/M2Workspace.vue";
import M2SessionWorkspace from "./modules/m2-approval/M2SessionWorkspace.vue";
import { createCSession } from "./modules/m2-approval/c-session";
import { createCGateway } from "./modules/m2-approval/c-gateway";
import ResourceWorkspace from "./modules/m1-reservation/resources/ResourceWorkspace.vue";
import { createPrototypeResourceGateway } from "./modules/m1-reservation/resources/prototype";
import { createUnconfiguredResourceGateway } from "./modules/m1-reservation/resources/gateway";
import {
  createPrototypeGateway,
  createUnconfiguredGateway,
} from "./modules/m2-approval/gateways";

const cSession = createCSession();
const cGateway = createCGateway(cSession);
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
  window.addEventListener("hashchange", updateScreen);
  window.addEventListener("beforeunload", warnPending);
});
onUnmounted(() => {
  window.removeEventListener("hashchange", updateScreen);
  window.removeEventListener("beforeunload", warnPending);
});
</script>

<template>
  <M2SessionWorkspace
    v-if="screen === '#m2'"
    :session="cSession"
    :gateway="cGateway"
  />
  <M2Workspace v-else-if="isM2" :key="screen" :gateway="gateway" />
  <ResourceWorkspace
    v-else-if="isResources"
    :key="screen"
    :gateway="resourceGateway"
  />
  <EngineeringHome v-else />
</template>
