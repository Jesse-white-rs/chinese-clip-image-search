/** 全局轻提示通知：success / error / info / warning，自动消失。 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastType = 'success' | 'error' | 'info' | 'warning'

export interface ToastItem {
  id: number
  message: string
  type: ToastType
}

let seq = 0

export const useToastStore = defineStore('toast', () => {
  const items = ref<ToastItem[]>([])

  function show(message: string, type: ToastType = 'info', duration = 3200) {
    const id = ++seq
    items.value.push({ id, message, type })
    // 最多保留 5 条
    if (items.value.length > 5) items.value.shift()
    window.setTimeout(() => dismiss(id), duration)
    return id
  }

  function dismiss(id: number) {
    const i = items.value.findIndex((t) => t.id === id)
    if (i >= 0) items.value.splice(i, 1)
  }

  const success = (msg: string, d?: number) => show(msg, 'success', d)
  const error = (msg: string, d?: number) => show(msg, 'error', d)
  const info = (msg: string, d?: number) => show(msg, 'info', d)
  const warning = (msg: string, d?: number) => show(msg, 'warning', d)

  return { items, show, dismiss, success, error, info, warning }
})
