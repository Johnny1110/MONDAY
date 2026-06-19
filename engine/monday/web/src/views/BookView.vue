<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON } from '../lib/api'
import { fmtNum, fmtInt, signCls } from '../lib/format'

const bk = ref<any>(null)
const actions = ref<any>(null)
const err = ref('')
const loading = ref(true)
const book = ref('')   // empty = engine default (book_mode)

const money = (x: number | null | undefined) =>
  x === null || x === undefined ? '—' : Math.round(x).toLocaleString()

async function load() {
  loading.value = true; err.value = ''
  const q = book.value ? `&book=${book.value}` : ''
  try {
    bk.value = await getJSON(`/api/book?status=open&page_size=200${q}`)
    actions.value = await getJSON('/api/book/actions?page_size=50')
  } catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="card-h">
    <h2>Book — 真實/紙上倉位 <span class="dim mono" style="font-size:13px" v-if="bk">{{ bk.book }}</span></h2>
    <div class="row">
      <label class="dim">book</label>
      <select v-model="book" @change="load"><option value="">default</option><option>paper</option><option>real</option></select>
    </div>
  </div>

  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <template v-else>
    <!-- exposure summary -->
    <div class="stats" style="margin-bottom:16px" v-if="bk.summary">
      <div class="stat"><div class="k">positions</div><div class="v">{{ bk.summary.n }}</div></div>
      <div class="stat"><div class="k">gross</div><div class="v mono" style="font-size:15px">{{ money(bk.summary.gross) }}</div></div>
      <div class="stat"><div class="k">net</div><div class="v mono" style="font-size:15px">{{ money(bk.summary.net) }}</div></div>
      <div class="stat"><div class="k">cash</div><div class="v mono" style="font-size:15px">{{ money(bk.summary.cash) }}</div></div>
      <div class="stat"><div class="k">total (NAV)</div><div class="v mono" style="font-size:15px">{{ money(bk.summary.total) }}</div></div>
    </div>
    <div class="card" v-if="bk.summary && Object.keys(bk.summary.by_sector || {}).length">
      <div class="card-h"><h2>By sector</h2><span class="dim mono">market value</span></div>
      <div class="row" style="flex-wrap:wrap; gap:8px">
        <span v-for="(v, s) in bk.summary.by_sector" :key="s" class="pill">{{ s }} · {{ money(v as number) }}</span>
      </div>
    </div>

    <!-- holdings -->
    <div class="card">
      <div class="card-h"><h2>Holdings</h2><span class="dim mono">{{ bk.total }} open</span></div>
      <div v-if="!bk.items.length" class="muted">no open positions — fills land via the round (morgan proposes, User confirms)</div>
      <table v-else>
        <thead><tr><th>symbol</th><th>qty</th><th>avg entry</th><th>TP</th><th>SL</th><th>size %</th><th>opened</th></tr></thead>
        <tbody>
          <tr v-for="p in bk.items" :key="p.position_id">
            <td><span class="sym">{{ p.symbol }}</span> <span class="dim">{{ p.name }}</span></td>
            <td class="mono">{{ fmtInt(p.qty) }}</td>
            <td class="mono">{{ fmtNum(p.avg_entry) }}</td>
            <td class="mono pos">{{ p.take_profit == null ? '—' : fmtNum(p.take_profit) }}</td>
            <td class="mono neg">{{ p.stop_loss == null ? '—' : fmtNum(p.stop_loss) }}</td>
            <td class="mono">{{ p.sizing_pct == null ? '—' : p.sizing_pct + '%' }}</td>
            <td class="mono dim">{{ p.opened_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- action log -->
    <div class="card">
      <div class="card-h"><h2>Action log</h2><span class="dim mono">{{ actions?.total || 0 }} hold/add/trim/exit</span></div>
      <div v-if="!actions?.items?.length" class="muted">no actions yet</div>
      <table v-else>
        <thead><tr><th>date</th><th>symbol</th><th>action</th><th>Δqty</th><th>→ qty</th><th>by</th><th>reason</th></tr></thead>
        <tbody>
          <tr v-for="a in actions.items" :key="a.action_id">
            <td class="mono dim">{{ a.action_date }}</td>
            <td class="sym">{{ a.symbol }}</td>
            <td><span class="badge" :class="a.action === 'exit' || a.action === 'trim' ? 'short' : 'long'">{{ a.action }}</span></td>
            <td class="mono" :class="signCls(a.delta_qty)">{{ a.delta_qty == null ? '—' : fmtInt(a.delta_qty) }}</td>
            <td class="mono">{{ a.new_qty == null ? '—' : fmtInt(a.new_qty) }}</td>
            <td class="dim">{{ a.decided_by }}</td>
            <td class="dim" style="font-size:12px">{{ a.reason }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>
