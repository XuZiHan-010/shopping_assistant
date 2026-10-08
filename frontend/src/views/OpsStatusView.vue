<script setup lang="ts">
/**
 * 只读运维看板页（N5 B Task 3 步骤 3；PRD §10.4、§14，D-N5-1）。
 *
 * 放在「管理」分组。内容区 `OpsStatusPanel` 挂在 `AdminGate` 的插槽里：没有令牌时它不挂载，
 * 不发任何 `/api/admin/*` 请求；令牌验证通过后才挂载并加载。
 */
import OpsStatusPanel from '@/components/ops/OpsStatusPanel.vue'
import AdminGate from '@/components/shell/AdminGate.vue'
</script>

<template>
  <AdminGate>
    <OpsStatusPanel />
  </AdminGate>
</template>
