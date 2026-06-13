<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON } from '../lib/api'
import { fmtNum, fmtSignedPct, signCls } from '../lib/format'
import Pager from '../components/Pager.vue'

const outcomes = ref<any>(null)
const marks = ref<any>(null)
const page = ref(1)
const err = ref('')
const loading = ref(true)

async function loadMarks(p: number) {
  marks.value = await getJSON(`/api/ledger/marks?page=${p}&page_size=20`)
  page.value = p
}
onMounted(async () => {
  try {
    outcomes.value = await getJSON('/api/ledger/outcomes?page_size=100')
    await loadMarks(1)
  } catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <template v-else>
    <div class="card">
      <div class="card-h"><h2>Settled outcomes</h2><span class="dim mono">{{ outcomes.total }} closed</span></div>
      <div v-if="!outcomes.items.length" class="muted">none settled yet</div>
      <table v-else>
        <thead><tr><th>rec</th><th>exit</th><th>price</th><th>realized</th><th>reason</th><th>error</th></tr></thead>
        <tbody>
          <tr v-for="o in outcomes.items" :key="o.rec_id">
            <td class="sym">{{ o.rec_id }}</td>
            <td class="mono dim">{{ o.exit_date }}</td>
            <td>{{ fmtNum(o.exit_price) }}</td>
            <td :class="signCls(o.realized_return)">{{ fmtSignedPct(o.realized_return) }}</td>
            <td><span class="pill">{{ o.exit_reason }}</span></td>
            <td class="dim" :class="signCls(o.error)">{{ fmtSignedPct(o.error) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-h"><h2>Daily marks</h2><span class="dim mono">mark-to-market ledger</span></div>
      <table>
        <thead><tr><th>rec</th><th>date</th><th>close</th><th>mtm</th><th>days held</th></tr></thead>
        <tbody>
          <tr v-for="m in marks.items" :key="m.rec_id + m.mark_date">
            <td class="sym">{{ m.rec_id }}</td>
            <td class="mono dim">{{ m.mark_date }}</td>
            <td>{{ fmtNum(m.close_price) }}</td>
            <td :class="signCls(m.mtm_return)">{{ fmtSignedPct(m.mtm_return) }}</td>
            <td class="dim">{{ m.days_held }}</td>
          </tr>
        </tbody>
      </table>
      <Pager :page="page" :page-size="20" :total="marks.total" :has-more="marks.has_more" @go="loadMarks" />
    </div>
  </template>
</template>
