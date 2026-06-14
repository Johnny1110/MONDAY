<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON } from '../lib/api'
import { fmtNum, fmtPct, fmtSignedPct, signCls } from '../lib/format'
import Sparkline from '../components/Sparkline.vue'

const pf = ref<any>(null)
const eq = ref<any[]>([])
const risk = ref<any>(null)
const err = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    pf.value = await getJSON('/api/portfolio?page_size=200')
    eq.value = await getJSON('/api/portfolio/equity')
    risk.value = await getJSON('/api/portfolio/risk')
  } catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <template v-else>
    <div class="stats" style="margin-bottom:16px">
      <div class="stat"><div class="k">open</div><div class="v">{{ pf.summary.open }}</div></div>
      <div class="stat"><div class="k">closed</div><div class="v">{{ pf.summary.closed }}</div></div>
      <div class="stat"><div class="k">win rate</div><div class="v">{{ fmtPct(pf.summary.win_rate, 0) }}</div></div>
      <div class="stat">
        <div class="k">avg realized</div>
        <div class="v" :class="signCls(pf.summary.avg_realized)">{{ fmtSignedPct(pf.summary.avg_realized) }}</div>
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h2>Equity curve</h2><span class="dim mono">1 + mean mtm per mark date</span></div>
      <Sparkline :points="eq.map((e) => e.equity)" :baseline="1" />
    </div>
    <div class="card" v-if="risk">
      <div class="card-h">
        <h2>Risk gate</h2>
        <span class="badge" :class="risk.passed ? 'long' : 'short'">{{ risk.passed ? 'PASS' : 'FLAGGED' }}</span>
      </div>
      <div class="row" style="flex-wrap:wrap">
        <span v-for="(c, s) in risk.by_sector" :key="s" class="pill">{{ s }} · {{ c }}</span>
      </div>
      <ul v-if="risk.violations.length" style="margin:8px 0 0; padding-left:18px; font-size:12.5px">
        <li v-for="(v, i) in risk.violations" :key="i" class="neg">⚠ {{ v.type }} — {{ v.detail }}</li>
      </ul>
      <div v-else class="dim" style="font-size:12px; margin-top:6px">no concentration / liquidity flags</div>
    </div>
    <div class="card">
      <div class="card-h"><h2>Positions</h2><span class="dim mono">{{ pf.total }} total</span></div>
      <table>
        <thead><tr><th>symbol</th><th>dir</th><th>entry</th><th>entry date</th><th>status</th></tr></thead>
        <tbody>
          <tr v-for="p in pf.items" :key="p.rec_id">
            <td class="sym">{{ p.symbol }}</td>
            <td><span class="badge" :class="p.direction">{{ p.direction }}</span></td>
            <td>{{ fmtNum(p.entry_price) }}</td>
            <td class="mono dim">{{ p.entry_date }}</td>
            <td :class="p.status === 'open' ? '' : 'dim'">{{ p.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>
