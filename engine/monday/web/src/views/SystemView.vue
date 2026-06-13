<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../lib/api'
import { fmtNum2 } from '../lib/format'

const status = ref<any>(null)
const factors = ref<any>(null)
const models = ref<any>(null)
const err = ref('')
const running = ref(false)
const result = ref<any>(null)
const days = ref(180)
const source = ref('synthetic')

async function load() {
  status.value = await getJSON('/api/system/status')
  factors.value = await getJSON('/api/factors')
  models.value = await getJSON('/api/models')
}
async function run() {
  running.value = true; result.value = null; err.value = ''
  try {
    result.value = await postJSON(`/api/system/run-pipeline?days=${days.value}&source=${source.value}`)
    await load()
  } catch (e: any) { err.value = String(e.message || e) }
  finally { running.value = false }
}
onMounted(load)
</script>

<template>
  <div class="card">
    <div class="card-h"><h2>Run pipeline</h2><span class="dim mono">one full chain → writes recs + marks</span></div>
    <div class="row">
      <label class="dim">source</label>
      <select v-model="source"><option>synthetic</option><option>finmind</option><option>twse</option></select>
      <label class="dim">days</label>
      <input v-model.number="days" type="number" style="width:88px" />
      <button class="gold" :disabled="running" @click="run">{{ running ? 'running…' : 'Run pipeline' }}</button>
      <span class="dim" style="font-size:12px">finmind/twse fetch live TW prices (cached)</span>
    </div>
    <div v-if="err" class="err" style="margin-top:12px">{{ err }}</div>
    <pre v-if="result" class="md" style="margin-top:12px"><code>{{ JSON.stringify(result, null, 2) }}</code></pre>
  </div>

  <div class="card" v-if="status">
    <div class="card-h"><h2>Status</h2></div>
    <div class="stats">
      <div class="stat"><div class="k">last as_of</div><div class="v mono" style="font-size:16px">{{ status.last_as_of || '—' }}</div></div>
      <div class="stat"><div class="k">model</div><div class="v mono" style="font-size:15px">{{ status.model || '—' }}</div></div>
      <div class="stat"><div class="k">recs</div><div class="v">{{ status.recommendations }}</div></div>
      <div class="stat"><div class="k">open</div><div class="v">{{ status.open_positions }}</div></div>
      <div class="stat"><div class="k">settled</div><div class="v">{{ status.settled_outcomes }}</div></div>
    </div>
  </div>

  <div class="grid cols2">
    <div class="card" v-if="factors">
      <div class="card-h"><h2>Factor catalog</h2><span class="dim mono">{{ factors.total }} factors</span></div>
      <table>
        <thead><tr><th>factor</th><th>group</th><th>description</th></tr></thead>
        <tbody>
          <tr v-for="f in factors.items" :key="f.name">
            <td class="sym">{{ f.name }}</td><td class="dim">{{ f.group }}</td><td class="dim">{{ f.desc }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="card" v-if="models">
      <div class="card-h"><h2>Model registry</h2></div>
      <div v-if="!models.items.length" class="muted">no models yet</div>
      <table v-else>
        <thead><tr><th>version</th><th>cv IC</th><th>trained</th></tr></thead>
        <tbody>
          <tr v-for="m in models.items" :key="m.model_version">
            <td class="sym">{{ m.model_version }}</td>
            <td>{{ m.cv_ic == null ? '—' : fmtNum2(m.cv_ic) }}</td>
            <td class="mono dim">{{ (m.trained_at || '').slice(0, 10) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
