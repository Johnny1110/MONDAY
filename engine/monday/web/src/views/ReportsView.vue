<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON } from '../lib/api'
import { md } from '../lib/md'

const daily = ref<any>(null)   // the structured 6-section report (A7)
const r = ref<any>(null)       // the generic feed (back-compat)
const err = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    daily.value = await getJSON('/api/reports/daily')
    r.value = await getJSON('/api/reports?page_size=50')
  } catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <template v-else>
    <!-- 2.0 structured 6-section daily report (A7) -->
    <div class="card" v-if="daily && daily.data">
      <div class="card-h">
        <h2>每日報告 — {{ daily.as_of }}</h2>
        <span>
          <span class="badge long" v-if="daily.regime">{{ daily.regime }}</span>
          <span class="badge long" v-if="daily.risk_state" style="margin-left:6px">{{ daily.risk_state }}</span>
        </span>
      </div>
      <div class="disclaimer">⚠ {{ daily.data.disclaimer }}</div>
      <div class="md" v-html="md(daily.summary_text || '')"></div>
    </div>
    <div class="card" v-else>
      <div class="card-h"><h2>每日報告</h2></div>
      <div class="muted">{{ daily?.note || 'no daily report yet — morgan posts it at the end of the round' }}</div>
    </div>

    <!-- generic notice feed (back-compat) -->
    <div class="card-h" style="margin-top:8px"><h2 class="dim" style="font-size:14px">Notices</h2></div>
    <div v-if="!r.items.length" class="muted">no notices yet</div>
    <div v-for="rep in r.items" :key="rep.id" class="card">
      <div class="card-h">
        <h2>{{ rep.title }}</h2>
        <span class="dim mono">{{ rep.kind }} · {{ (rep.ts || '').slice(0, 10) }}</span>
      </div>
      <div class="md" v-html="md(rep.body)"></div>
    </div>
  </template>
</template>

<style scoped>
.disclaimer {
  font-size: 12px; color: #caa46a; background: rgba(212, 175, 55, .08);
  border-radius: 6px; padding: 7px 10px; margin-bottom: 12px;
}
</style>
