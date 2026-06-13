<script setup lang="ts">
defineProps<{ page: number; pageSize: number; total: number; hasMore: boolean }>()
const emit = defineEmits<{ (e: 'go', page: number): void }>()
</script>

<template>
  <div class="pager row" v-if="total > pageSize">
    <button :disabled="page <= 1" @click="emit('go', page - 1)">‹ prev</button>
    <span class="dim mono">page {{ page }} · {{ total }} rows</span>
    <button :disabled="!hasMore" @click="emit('go', page + 1)">next ›</button>
  </div>
</template>

<style scoped>
.pager { margin-top: 12px; }
</style>
