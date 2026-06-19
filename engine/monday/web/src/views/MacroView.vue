<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON } from '../lib/api'
import { signCls } from '../lib/format'

const m = ref<any>(null)
const err = ref('')
const loading = ref(true)
const asOf = ref('')   // empty = latest

// chg_pct is already a percent number (1.8 = +1.8%), not a fraction
function sp(x: number | null | undefined): string {
  return x === null || x === undefined ? '—' : `${x >= 0 ? '+' : ''}${x.toFixed(2)}%`
}

async function load() {
  loading.value = true; err.value = ''
  try {
    m.value = await getJSON('/api/macro' + (asOf.value ? `?as_of=${asOf.value}` : ''))
  } catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="card-h">
    <h2>Macro — 由上而下定調 <span class="dim mono" style="font-size:13px" v-if="m">{{ m.as_of || '—' }}</span></h2>
    <div class="row">
      <label class="dim">as_of</label>
      <input v-model="asOf" type="date" />
      <button class="gold" @click="load">load</button>
    </div>
  </div>

  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <div v-else-if="!m.indices?.length" class="muted">{{ m.note || 'no macro snapshot yet — POST /api/macro/refresh' }}</div>
  <template v-else>
    <!-- risk-proxy banner -->
    <div class="card" v-if="m.overnight?.risk_proxies && Object.keys(m.overnight.risk_proxies).length">
      <div class="card-h"><h2>隔夜風向</h2><span class="dim mono">risk proxies + biggest movers</span></div>
      <div class="row" style="flex-wrap:wrap; gap:10px">
        <span v-for="(v, s) in m.overnight.risk_proxies" :key="s" class="pill">
          {{ s }} <b :class="signCls(v)">{{ sp(v as number) }}</b>
        </span>
      </div>
      <div class="row" style="flex-wrap:wrap; gap:8px; margin-top:10px; font-size:12px">
        <span class="dim">leaders:</span>
        <span v-for="l in m.overnight.leaders" :key="l.symbol" class="pos">{{ l.name || l.symbol }} {{ sp(l.chg_pct) }}</span>
        <span class="dim" style="margin-left:8px">laggards:</span>
        <span v-for="l in m.overnight.laggards" :key="l.symbol" class="neg">{{ l.name || l.symbol }} {{ sp(l.chg_pct) }}</span>
      </div>
    </div>

    <!-- index grid -->
    <div class="card">
      <div class="card-h"><h2>世界指數</h2><span class="dim mono">{{ m.indices.length }} markets</span></div>
      <table>
        <thead><tr><th>index</th><th>class</th><th>close</th><th>prev</th><th>chg%</th><th>date</th></tr></thead>
        <tbody>
          <tr v-for="r in m.indices" :key="r.symbol">
            <td><span class="sym">{{ r.symbol }}</span> <span class="dim">{{ r.name }}</span></td>
            <td><span class="pill">{{ r.asset_class }}</span></td>
            <td class="mono">{{ r.close == null ? '—' : r.close }}</td>
            <td class="mono dim">{{ r.prev_close == null ? '—' : r.prev_close }}</td>
            <td class="mono" :class="signCls(r.chg_pct)">{{ sp(r.chg_pct) }}</td>
            <td class="mono dim">{{ r.date || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>
