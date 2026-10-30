<script setup lang="ts">
import CSessionFrame from "../../shared/CSessionFrame.vue";
import M2Workspace from "./M2Workspace.vue";
import type { CSession } from "./c-session";
import type { createCGateway } from "./c-gateway";
defineProps<{
  session: CSession;
  gateway: ReturnType<typeof createCGateway>;
}>();
</script>
<template>
  <CSessionFrame :session="session" v-slot="{ identity }">
    <M2Workspace :key="identity.subject_id" :gateway="gateway" />
  </CSessionFrame>
</template>
