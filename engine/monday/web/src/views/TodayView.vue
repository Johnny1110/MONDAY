<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON } from '../lib/api'
import { fmtNum, fmtPct } from '../lib/format'

const data = ref<any>(null)
const err = ref('')
const loading = ref(true)

onMounted(async () => {
  try { data.value = await getJSON('/api/recommendations/today') }
  catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <template v-else>
    <div class="card-h">
      <h2>Daily ideas — {{ data.as_of_date || '—' }}</h2>
      <span class="dim mono">model {{ data.model_version || '—' }} · regime {{ data.regime || '—' }}</span>
    </div>
    <div v-if="!data.recommendations?.length" class="muted">
      {{ data.note || 'No ideas yet — run the pipeline on the System page.' }}
    </div>
    <div v-else class="grid ideas">
      <div v-for="r in data.recommendations" :key="r.symbol" class="card idea">
        <div class="idea-h">
          <div><span class="sym">{{ r.symbol }}</span> <span class="dim">{{ r.name }}</span></div>
          <span class="badge" :class="r.direction">{{ r.direction }}</span>
        </div>
        <div class="prices">
          <div><div class="k">entry</div><div class="v">{{ fmtNum(r.entry_ref) }}</div></div>
          <div><div class="k">TP</div><div class="v pos">{{ fmtNum(r.take_profit) }}</div><div class="kk pos">+{{ r.tp_pct }}%</div></div>
          <div><div class="k">SL</div><div class="v neg">{{ fmtNum(r.stop_loss) }}</div></div>
        </div>
        <div>
          <div class="row" style="justify-content:space-between">
            <span class="dim">conviction</span><span class="mono">{{ fmtPct(r.conviction, 0) }}</span>
          </div>
          <div class="bar"><i :style="{ width: (r.conviction * 100) + '%' }"></i></div>
        </div>
        <div class="facts"><span v-for="f in r.factors" :key="f" class="pill">{{ f }}</span></div>
        <div class="rat dim">{{ r.rationale }}</div>
        <div class="risk">⚠ {{ r.risk_notes }}</div>
      </div>
    </div>
  </template>
</template>

<style scoped>
.idea { display: flex; flex-direction: column; gap: 11px; }
.idea-h { display: flex; justify-content: space-between; align-items: center; }
.sym { font-family: ui-monospace, Menlo, monospace; color: var(--gold2); font-weight: 700; font-size: 16px; }
.prices { display: flex; gap: 16px; }
.prices .k { color: var(--dim); font-size: 11px; }
.prices .v { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
.prices .kk { font-size: 11px; }
.facts { display: flex; flex-wrap: wrap; }
.rat { font-size: 12.5px; }
.risk { font-size: 11.5px; color: #caa46a; background: rgba(212, 175, 55, .07); border-radius: 6px; padding: 6px 8px; }
</style>
