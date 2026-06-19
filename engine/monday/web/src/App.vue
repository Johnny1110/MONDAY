<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NAV } from './router'
import { getJSON } from './lib/api'

const status = ref<any>(null)
const rounding = ref(false)
const round = ref<{ state: string; msg: string } | null>(null)

async function load() {
  try { status.value = await getJSON('/api/system/status') } catch { /* topbar stays blank */ }
}

// "Run today's round" (A8): wakes morgan, idempotent — 409 means already requested today.
async function runRound() {
  rounding.value = true; round.value = null
  try {
    const r = await fetch('/api/system/run-round', { method: 'POST' })
    const body: any = await r.json().catch(() => ({}))
    if (r.ok) round.value = { state: 'ok', msg: `round requested · ${body.as_of || ''}` }
    else if (r.status === 409) round.value = { state: 'warn', msg: 'already requested today' }
    else round.value = { state: 'err', msg: `HTTP ${r.status}` }
    await load()
  } catch (e: any) {
    round.value = { state: 'err', msg: String(e.message || e) }
  } finally {
    rounding.value = false
  }
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
        <div class="dim">TW-equity lab · 2.0</div>
        <div class="mono dim" v-if="status">as_of {{ status.last_as_of || '—' }}</div>
        <div class="mono dim" v-if="status?.last_round_requested">
          round {{ status.last_round_requested.as_of }}
        </div>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <div class="crumbs">{{ $route.path.slice(1) || 'today' }}</div>
        <div class="top-actions">
          <span v-if="round" class="round-msg" :class="round.state">{{ round.msg }}</span>
          <button class="gold" :disabled="rounding" @click="runRound" title="Wake morgan to run today's round (does not place orders)">
            {{ rounding ? 'requesting…' : '▶ Run today\'s round' }}
          </button>
          <div class="top-right mono dim" v-if="status">
            {{ status.open_positions }} open · {{ status.settled_outcomes }} settled
          </div>
        </div>
      </header>
      <section class="view"><RouterView /></section>
    </main>
  </div>
</template>

<style scoped>
.top-actions { display: flex; align-items: center; gap: 12px; }
.round-msg { font-size: 12px; padding: 3px 8px; border-radius: 6px; }
.round-msg.ok { color: #7fd1a3; background: rgba(127, 209, 163, .1); }
.round-msg.warn { color: #d4af37; background: rgba(212, 175, 55, .1); }
.round-msg.err { color: #e0796f; background: rgba(224, 121, 111, .1); }
</style>
