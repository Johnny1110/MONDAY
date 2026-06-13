<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON } from '../lib/api'
import { fmtNum2, fmtPct, fmtSignedPct, signCls } from '../lib/format'
import Reliability from '../components/Reliability.vue'

const d = ref<any>(null)
const err = ref('')
const loading = ref(true)

onMounted(async () => {
  try { d.value = await getJSON('/api/calibration') }
  catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
})

function rows(obj: any) {
  return obj
    ? Object.entries(obj).map(([k, v]: any) => ({ k, mean: v.mean, n: v.n }))
        .sort((a, b) => b.mean - a.mean)
    : []
}
</script>

<template>
  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <template v-else>
    <div class="stats" style="margin-bottom:16px">
      <div class="stat"><div class="k">rank IC</div><div class="v" :class="signCls(d.ic)">{{ d.ic == null ? '—' : fmtNum2(d.ic) }}</div></div>
      <div class="stat"><div class="k">hit rate</div><div class="v">{{ fmtPct(d.hit_rate, 0) }}</div></div>
      <div class="stat"><div class="k">avg win</div><div class="v pos">{{ fmtSignedPct(d.avg_win) }}</div></div>
      <div class="stat"><div class="k">avg loss</div><div class="v neg">{{ fmtSignedPct(d.avg_loss) }}</div></div>
      <div class="stat"><div class="k">sample n</div><div class="v">{{ d.n }}</div></div>
    </div>
    <div class="grid cols2">
      <div class="card">
        <div class="card-h"><h2>Reliability</h2><span class="dim mono">predicted P(tp) vs observed</span></div>
        <Reliability :curve="d.calibration_curve || []" />
      </div>
      <div class="card">
        <div class="card-h"><h2>Attribution by factor</h2><span class="dim mono">mean realized return</span></div>
        <table v-if="rows(d.attribution_by_factor).length">
          <thead><tr><th>factor</th><th>mean</th><th>n</th></tr></thead>
          <tbody>
            <tr v-for="r in rows(d.attribution_by_factor)" :key="r.k">
              <td class="sym">{{ r.k }}</td>
              <td :class="signCls(r.mean)">{{ fmtSignedPct(r.mean) }}</td>
              <td class="dim">{{ r.n }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="muted">no attribution yet</div>
      </div>
    </div>
    <div class="card"><div class="dim" style="font-size:12px">{{ d.note }}</div></div>
  </template>
</template>
