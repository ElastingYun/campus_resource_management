<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import EngineeringHome from "./shared/EngineeringHome.vue";
import M2Workspace from "./modules/m2-approval/M2Workspace.vue";
import {
  createPrototypeGateway,
  createUnconfiguredGateway,
} from "./modules/m2-approval/gateways";

const screen = ref(window.location.hash);
const updateScreen = () => {
  screen.value = window.location.hash;
};
const isM2 = computed(() => ["#m2", "#m2-prototype"].includes(screen.value));
const gateway = computed(() =>
  screen.value === "#m2-prototype"
    ? createPrototypeGateway()
    : createUnconfiguredGateway(),
);
onMounted(() => window.addEventListener("hashchange", updateScreen));
onUnmounted(() => window.removeEventListener("hashchange", updateScreen));
</script>

<template>
  <M2Workspace v-if="isM2" :key="screen" :gateway="gateway" />
  <EngineeringHome v-else />
</template>
