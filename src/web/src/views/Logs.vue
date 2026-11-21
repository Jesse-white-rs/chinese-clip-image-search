<template>
  <div>
    <div class="page-head">
      <h2>系统日志</h2>
      <div class="head-tools">
        <select v-model="selected" class="select" @change="onSelect">
          <option value="">请选择日志文件</option>
          <optgroup label="业务审计日志">
            <option v-for="f in auditFiles" :key="f.name" :value="f.name">{{ f.name }} ({{ formatSize(f.size) }})</option>
          </optgroup>
          <optgroup label="系统运行日志">
            <option v-for="f in systemFiles" :key="f.name" :value="f.name">{{ f.name }} ({{ formatSize(f.size) }})</option>
          </optgroup>
        </select>
        <input v-model="keyword" class="input kw-input" placeholder="过滤关键字（URL/商品ID/imgId）" />
        <select v-model="level" class="select" @change="readLogs">
          <option value="">全部级别</option>
          <option value="ERROR">ERROR</option>
          <option value="WARNING">WARNING</option>
          <option value="INFO">INFO</option>
          <option value="DEBUG">DEBUG</option>
        </select>
        <select v-model.number="lines" class="select" @change="readLogs">
          <option :value="100">100 行</option>
          <option :value="200">200 行</option>
          <option :value="500">500 行</option>
          <option :value="1000">1000 行</option>
        </select>
        <button class="btn btn-sm" @click="readLogs" :disabled="!selected || loading">刷新</button>
        <label class="check"><input v-model="autoRefresh" type="checkbox" /> 自动刷新</label>
      </div>
    </div>

    <div v-if="!selected" class="glass-panel empty">请选择一个日志文件查看</div>
    <template v-else>
      <div class="glass-panel card log-card">
        <div v-if="loading" class="empty"><span class="spinner"></span> 加载中...</div>
        <div v-else-if="logLines.length === 0" class="empty">暂无日志内容</div>
        <div v-else class="log-view">
          <div v-for="(line, i) in filteredLines" :key="i" class="log-line" :class="lineClass(line)">{{ line }}</div>
        </div>
      </div>
      <div class="log-foot">显示最新 {{ logLines.length }} 行 · 文件 {{ selected }}</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { logsApi, type LogFile } from '@/api/logs'

const files = ref<LogFile[]>([])
const selected = ref('')
const level = ref('')
const lines = ref(200)
const keyword = ref('')
const logLines = ref<string[]>([])
const loading = ref(false)
const autoRefresh = ref(false)
let timer: number | undefined

const auditFiles = computed(() => files.value.filter(f => f.name.startsWith('audit-')))
const systemFiles = computed(() => files.value.filter(f => !f.name.startsWith('audit-')))
const filteredLines = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return logLines.value
  return logLines.value.filter(l => l.toLowerCase().includes(kw))
})

function formatSize(size: number) {
  if (size < 1024) return `${size}B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${(size / 1024 / 1024).toFixed(1)}MB`
}

function lineClass(line: string) {
  if (line.includes('｜ AUDIT ｜')) return 'lv-audit'
  if (line.includes('｜ ERROR ｜')) return 'lv-error'
  if (line.includes('｜ WARNING ｜')) return 'lv-warn'
  if (line.includes('｜ INFO ｜')) return 'lv-info'
  if (line.includes('｜ DEBUG ｜')) return 'lv-debug'
  return ''
}

async function loadFiles() {
  try { files.value = (await logsApi.list()).files || [] } catch { /* ignore */ }
}

async function readLogs() {
  if (!selected.value) return
  loading.value = true
  try {
    const res = await logsApi.read(selected.value, lines.value, level.value || undefined)
    logLines.value = res.lines || []
  } catch { /* ignore */ }
  finally { loading.value = false }
}

function onSelect() { readLogs() }

function startAuto() {
  clearInterval(timer)
  if (autoRefresh.value) {
    timer = window.setInterval(readLogs, 5000)
  }
}

import { watch } from 'vue'
watch(autoRefresh, startAuto)

onMounted(async () => {
  await loadFiles()
  if (files.value.length) {
    selected.value = files.value[0].name
    readLogs()
  }
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.page-head { flex-wrap: wrap; gap: 12px; }
.head-tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.head-tools .select { width: auto; min-width: 110px; }
.kw-input { width: 200px; font-size: 12px; padding: 7px 11px; }
.check { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); cursor: pointer; }
.check input { accent-color: var(--accent); }
.card { padding: 0; overflow: hidden; }
.log-card { min-height: 400px; }
.log-view {
  padding: 14px 16px;
  max-height: 68vh;
  overflow: auto;
  font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.7;
  background: rgba(6,8,18,0.5);
  border-radius: var(--radius-lg);
}
.log-line { color: var(--text-secondary); white-space: pre-wrap; word-break: break-all; padding: 1px 0; }
.log-line:hover { background: rgba(90,158,140,0.08); }
.lv-error { color: #f87171; }
.lv-warn { color: #fbbf24; }
.lv-info { color: #7dd3fc; }
.lv-debug { color: #64748b; }
.lv-audit { color: var(--accent); }
.log-foot { font-size: 11px; color: var(--text-muted); margin-top: 10px; text-align: right; }
</style>
