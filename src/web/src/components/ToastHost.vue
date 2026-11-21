<template>
  <Teleport to="body">
    <div class="toast-host" aria-live="polite">
      <TransitionGroup name="toast">
        <div v-for="t in toast.items" :key="t.id" class="toast" :class="`toast-${t.type}`" @click="toast.dismiss(t.id)">
          <span class="toast-icon">{{ icon(t.type) }}</span>
          <span class="toast-msg">{{ t.message }}</span>
          <span class="toast-close">×</span>
          <span class="toast-progress"></span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useToastStore, type ToastType } from '@/stores/toast'

const toast = useToastStore()
function icon(type: ToastType) {
  return { success: '✓', error: '✕', warning: '!', info: 'i' }[type]
}
</script>

<style scoped>
.toast-host {
  position: fixed; top: 24px; right: 24px; z-index: 9999;
  display: flex; flex-direction: column; gap: 10px;
  pointer-events: none;
}
.toast {
  position: relative; min-width: 260px; max-width: 420px;
  display: flex; align-items: center; gap: 11px;
  padding: 13px 16px; overflow: hidden;
  font-size: 13px; color: var(--text-1);
  background: rgba(28, 32, 54, 0.72);
  border: 1px solid var(--glass-stroke-hi);
  border-radius: var(--r-md);
  backdrop-filter: blur(24px) saturate(160%);
  -webkit-backdrop-filter: blur(24px) saturate(160%);
  box-shadow: 0 18px 50px rgba(0,0,0,0.5), var(--glass-inset);
  pointer-events: auto; cursor: pointer;
}
.toast-icon {
  width: 24px; height: 24px; flex-shrink: 0;
  display: grid; place-items: center; border-radius: 8px;
  font-size: 13px; font-weight: 700; color: #fff;
}
.toast-success .toast-icon { background: linear-gradient(140deg, #5ee6a8, #2fbf82); box-shadow: 0 3px 12px rgba(94,230,168,0.4); }
.toast-error .toast-icon { background: linear-gradient(140deg, #ff8095, #e0526e); box-shadow: 0 3px 12px rgba(255,128,149,0.4); }
.toast-warning .toast-icon { background: linear-gradient(140deg, #ffcc7a, #e0a53d); box-shadow: 0 3px 12px rgba(255,204,122,0.4); }
.toast-info .toast-icon { background: linear-gradient(140deg, var(--aurora-1), var(--aurora-3)); box-shadow: 0 3px 12px rgba(90,158,140,0.32); }
.toast-msg { flex: 1; line-height: 1.5; }
.toast-close { color: var(--text-3); font-size: 17px; line-height: 1; opacity: 0; transition: var(--t); }
.toast:hover .toast-close { opacity: 1; }
.toast-progress {
  position: absolute; left: 0; bottom: 0; height: 2px;
  background: var(--accent); opacity: 0.6;
  animation: toast-shrink 3.2s linear forwards;
}
.toast-success .toast-progress { background: var(--success); }
.toast-error .toast-progress { background: var(--danger); }
.toast-warning .toast-progress { background: var(--warning); }
@keyframes toast-shrink { from { width: 100%; } to { width: 0%; } }

/* 进出动画 */
.toast-enter-active { transition: all 0.4s var(--ease); }
.toast-leave-active { transition: all 0.3s var(--ease); position: absolute; right: 0; }
.toast-enter-from { opacity: 0; transform: translateX(40px) scale(0.9); }
.toast-leave-to { opacity: 0; transform: translateX(30px) scale(0.92); }
.toast-move { transition: transform 0.35s var(--ease); }

@media (max-width: 600px) {
  .toast-host { top: 14px; right: 14px; left: 14px; }
  .toast { min-width: 0; max-width: none; }
}
</style>
