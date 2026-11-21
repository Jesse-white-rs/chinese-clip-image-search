<template>
  <span ref="el">{{ display }}</span>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'

const props = withDefaults(defineProps<{
  value: number
  duration?: number
  format?: 'plain' | 'comma' | 'percent'
}>(), { duration: 700, format: 'plain' })

const el = ref<HTMLElement | null>(null)
const display = ref('0')
let raf = 0

function render(v: number) {
  if (props.format === 'comma') return Math.round(v).toLocaleString()
  if (props.format === 'percent') return `${Math.round(v)}%`
  return String(Math.round(v))
}

function animateTo(target: number) {
  cancelAnimationFrame(raf)
  const from = Number(display.value.replace(/[^\d-]/g, '')) || 0
  if (from === target) { display.value = render(target); return }
  const start = performance.now()
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (reduce) { display.value = render(target); return }
  const tick = (now: number) => {
    const p = Math.min(1, (now - start) / props.duration)
    const eased = 1 - Math.pow(1 - p, 3)  // ease-out cubic
    display.value = render(from + (target - from) * eased)
    if (p < 1) raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
}

onMounted(() => animateTo(props.value))
watch(() => props.value, (v) => animateTo(v))
</script>
