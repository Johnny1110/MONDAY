<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJSON } from '../lib/api'
import { md } from '../lib/md'

const r = ref<any>(null)
const err = ref('')
const loading = ref(true)

onMounted(async () => {
  try { r.value = await getJSON('/api/reports?page_size=50') }
  catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <template v-else>
    <div v-if="!r.items.length" class="muted">no reports yet</div>
    <div v-for="rep in r.items" :key="rep.id" class="card">
      <div class="card-h">
        <h2>{{ rep.title }}</h2>
        <span class="dim mono">{{ rep.kind }} · {{ (rep.ts || '').slice(0, 10) }}</span>
      </div>
      <div class="md" v-html="md(rep.body)"></div>
    </div>
  </template>
</template>
