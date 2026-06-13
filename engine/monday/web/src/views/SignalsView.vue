<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON } from '../lib/api'
import { fmtNum, fmtPct, fmtSignedPct, signCls } from '../lib/format'

const d = ref<any>(null)
const err = ref('')
const loading = ref(true)

onMounted(async () => {
  try { d.value = await getJSON('/api/signals/today') }
  catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <div v-else class="card">
    <div class="card-h">
      <h2>Candidate ranking — {{ d.as_of_date || '—' }}</h2>
      <span class="dim mono">{{ d.candidate_count }} candidates · model {{ d.model_version }}</span>
    </div>
    <div v-if="!d.candidates?.length" class="muted">{{ d.note || 'No signals yet.' }}</div>
    <table v-else>
      <thead>
        <tr><th>#</th><th>symbol</th><th>name</th><th>score</th><th>E[ret]</th><th>P(tp)</th>
          <th>mom 20d</th><th>mom 60d</th><th>RSI</th></tr>
      </thead>
      <tbody>
        <tr v-for="c in d.candidates" :key="c.symbol">
          <td class="dim">{{ c.rank }}</td>
          <td class="sym">{{ c.symbol }}</td>
          <td>{{ c.name }}</td>
          <td>{{ fmtNum(c.score) }}</td>
          <td :class="signCls(c.predicted_return)">{{ fmtSignedPct(c.predicted_return) }}</td>
          <td>{{ fmtPct(c.predicted_prob_tp, 0) }}</td>
          <td :class="signCls(c.factors?.mom_20d)">{{ fmtSignedPct(c.factors?.mom_20d) }}</td>
          <td :class="signCls(c.factors?.mom_60d)">{{ fmtSignedPct(c.factors?.mom_60d) }}</td>
          <td>{{ fmtNum(c.factors?.rsi_14, 0) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
