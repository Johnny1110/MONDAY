<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  points: number[]
  width?: number
  height?: number
  baseline?: number | null
}>(), { width: 600, height: 130, baseline: null })

const geo = computed(() => {
  const p = props.points
  const W = props.width, H = props.height, pad = 10
  if (p.length < 2) return null
  const vals = props.baseline == null ? p : [...p, props.baseline]
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1
  const X = (i: number) => pad + (i / (p.length - 1)) * (W - 2 * pad)
  const Y = (v: number) => H - pad - ((v - min) / span) * (H - 2 * pad)
  const line = p.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(' ')
  const area = `${line} L${X(p.length - 1).toFixed(1)} ${H - pad} L${X(0).toFixed(1)} ${H - pad} Z`
  return { line, area, baseY: props.baseline == null ? null : Y(props.baseline),
           up: p[p.length - 1] >= p[0], W, H }
})
</script>

<template>
  <svg v-if="geo" :viewBox="`0 0 ${geo.W} ${geo.H}`" class="spark" preserveAspectRatio="none">
    <line v-if="geo.baseY != null" :x1="0" :x2="geo.W" :y1="geo.baseY" :y2="geo.baseY" class="base" />
    <path :d="geo.area" :class="['area', geo.up ? 'up' : 'dn']" />
    <path :d="geo.line" :class="['stroke', geo.up ? 'up' : 'dn']" />
  </svg>
  <div v-else class="muted">not enough data to chart yet</div>
</template>

<style scoped>
.spark { width: 100%; height: 140px; display: block; }
.base { stroke: var(--line); stroke-dasharray: 3 3; stroke-width: 1; }
.stroke { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; }
.stroke.up { stroke: var(--pos); }
.stroke.dn { stroke: var(--neg); }
.area { stroke: none; opacity: 0.13; }
.area.up { fill: var(--pos); }
.area.dn { fill: var(--neg); }
</style>
