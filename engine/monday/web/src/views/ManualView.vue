<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getText } from '../lib/api'
import { md } from '../lib/md'

const html = ref('')
const err = ref('')
const loading = ref(true)

onMounted(async () => {
  try { html.value = md(await getText('/manual')) }
  catch (e: any) { err.value = String(e.message || e) }
  finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="spin">loading…</div>
  <div v-else-if="err" class="err">{{ err }}</div>
  <div v-else class="card md" v-html="html"></div>
</template>
