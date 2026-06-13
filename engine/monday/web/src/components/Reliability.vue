<script setup lang="ts">
import { computed } from 'vue'

// Reliability diagram (calibration curve): the lab's signature plot — do the 70%-confidence
// ideas really hit ~70%? Points on the diagonal = well-calibrated; below = over-confident.
const props = defineProps<{ curve: { mean_pred: number; observed: number; n: number }[] }>()

const S = 220, pad = 26
const X = (v: number) => pad + v * (S - 2 * pad)
const Y = (v: number) => S - pad - v * (S - 2 * pad)

const pts = computed(() =>
  props.curve.map((c) => ({ x: X(c.mean_pred), y: Y(c.observed), r: Math.min(12, 3 + Math.sqrt(c.n)) })))
const poly = computed(() =>
  props.curve.length
    ? props.curve.slice().sort((a, b) => a.mean_pred - b.mean_pred)
        .map((c) => `${X(c.mean_pred).toFixed(1)},${Y(c.observed).toFixed(1)}`).join(' ')
    : '')
</script>

<template>
  <div v-if="!curve.length" class="muted">no settled ideas to calibrate yet</div>
  <svg v-else :viewBox="`0 0 ${S} ${S}`" class="rel">
    <rect :x="pad" :y="pad" :width="S - 2 * pad" :height="S - 2 * pad" class="frame" />
    <line :x1="X(0)" :y1="Y(0)" :x2="X(1)" :y2="Y(1)" class="diag" />
    <polyline v-if="poly" :points="poly" class="curve" />
    <circle v-for="(p, i) in pts" :key="i" :cx="p.x" :cy="p.y" :r="p.r" class="pt" />
    <text :x="pad" :y="S - 8" class="ax">0</text>
    <text :x="S - pad" :y="S - 8" class="ax" text-anchor="end">predicted →</text>
    <text :x="8" :y="pad + 4" class="ax">observed ↑</text>
  </svg>
</template>

<style scoped>
.rel { width: 240px; height: 240px; }
.frame { fill: var(--panel2); stroke: var(--line); }
.diag { stroke: var(--dim); stroke-dasharray: 4 4; }
.curve { fill: none; stroke: var(--gold); stroke-width: 2; opacity: 0.6; }
.pt { fill: var(--gold2); stroke: #1a1300; stroke-width: 1; opacity: 0.9; }
.ax { fill: var(--dim); font-size: 10px; }
</style>
