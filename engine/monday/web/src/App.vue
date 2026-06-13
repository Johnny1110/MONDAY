<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NAV } from './router'
import { getJSON } from './lib/api'

const status = ref<any>(null)

async function load() {
  try { status.value = await getJSON('/api/system/status') } catch { /* topbar stays blank */ }
}
onMounted(load)
</script>

<template>
  <div class="app">
    <aside class="side">
      <div class="brand">📈 <span>Monday</span></div>
      <nav class="nav">
        <RouterLink v-for="n in NAV" :key="n.path" :to="n.path">
          <span class="ic">{{ n.icon }}</span><span>{{ n.title }}</span>
        </RouterLink>
      </nav>
      <div class="side-foot">
        <div class="dim">TW-equity lab · P0</div>
        <div class="mono dim" v-if="status">as_of {{ status.last_as_of || '—' }}</div>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <div class="crumbs">{{ $route.path.slice(1) || 'today' }}</div>
        <div class="top-right mono dim" v-if="status">
          model {{ status.model || '—' }} · {{ status.recommendations }} recs ·
          {{ status.open_positions }} open · {{ status.settled_outcomes }} settled
        </div>
      </header>
      <section class="view"><RouterView /></section>
    </main>
  </div>
</template>
