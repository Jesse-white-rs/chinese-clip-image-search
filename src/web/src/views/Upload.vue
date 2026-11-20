<template>
  <div>
    <div class="page-head">
      <h2>上传入库</h2>
      <select v-model="table" class="select" style="width: 200px">
        <option value="">请选择图库</option>
        <option v-for="t in tables" :key="t.name" :value="t.name">{{ t.name }}</option>
      </select>
    </div>

    <div v-if="!table" class="glass-panel empty">请先选择一个图库</div>
    <template v-else>
      <div class="tabs">
        <button v-for="t in tabs" :key="t.key" class="tab" :class="{ active: active === t.key }" @click="active = t.key">{{ t.label }}</button>
      </div>

      <div class="glass-panel card">
        <!-- 单张上传 -->
        <div v-if="active === 'single'" class="form-grid">
          <div class="form-item">
            <label class="label">图片来源</label>
            <div class="seg">
              <button class="seg-btn" :class="{ on: source === 'file' }" @click="source = 'file'">本地文件</button>
              <button class="seg-btn" :class="{ on: source === 'url' }" @click="source = 'url'">图片链接</button>
            </div>
          </div>
          <div v-if="source === 'file'" class="form-item">
            <label class="label">选择图片</label>
            <input type="file" class="input" accept="image/*" @change="onFile" />
          </div>
          <div v-else class="form-item">
            <label class="label">图片 URL</label>
            <input v-model="singleUrl" class="input" placeholder="https://..." />
          </div>
          <div class="form-item">
            <label class="label">商品 ID</label>
            <input v-model="commodityId" class="input" placeholder="可选" />
          </div>
          <div class="form-item">
            <label class="label">自定义参数</label>
            <input v-model="customsParam" class="input" placeholder="可选" />
          </div>
          <div class="form-item">
            <label class="check"><input v-model="saveToMinio" type="checkbox" /> 保存到 MinIO（不勾选则只入库特征向量）</label>
          </div>
          <div class="form-item">
            <button class="btn btn-primary" :disabled="uploading" @click="doSingle">
              <span v-if="uploading" class="spinner"></span><span v-else>上传</span>
            </button>
          </div>
          <div v-if="msg" class="result-msg" :class="{ err: msgErr }">{{ msg }}</div>
        </div>

        <!-- 手动 ID 上传 -->
        <div v-else-if="active === 'manual'" class="form-grid">
          <div class="form-item">
            <label class="label">Milvus ID（必填）</label>
            <input v-model.number="manualId" class="input" type="number" placeholder="例如 10001" />
          </div>
          <div class="form-item">
            <label class="label">图片来源</label>
            <div class="seg">
              <button class="seg-btn" :class="{ on: manualSource === 'file' }" @click="manualSource = 'file'">本地文件</button>
              <button class="seg-btn" :class="{ on: manualSource === 'url' }" @click="manualSource = 'url'">图片链接</button>
            </div>
          </div>
          <div v-if="manualSource === 'file'" class="form-item">
            <label class="label">选择图片</label>
            <input type="file" class="input" accept="image/*" @change="onManualFile" />
          </div>
          <div v-else class="form-item">
            <label class="label">图片 URL</label>
            <input v-model="manualUrl" class="input" placeholder="https://..." />
          </div>
          <div class="form-item">
            <label class="label">商品 ID</label>
            <input v-model="manualCommodityId" class="input" placeholder="可选" />
          </div>
          <div class="form-item">
            <label class="check"><input v-model="manualSaveToMinio" type="checkbox" /> 保存到 MinIO</label>
          </div>
          <div class="form-item">
            <button class="btn btn-primary" :disabled="uploading" @click="doManual">
              <span v-if="uploading" class="spinner"></span><span v-else>上传</span>
            </button>
          </div>
          <div v-if="msg" class="result-msg" :class="{ err: msgErr }">{{ msg }}</div>
        </div>

        <!-- 批量上传 -->
        <div v-else-if="active === 'batch'" class="form-grid">
          <div class="form-item">
            <label class="label">图片来源</label>
            <div class="seg">
              <button class="seg-btn" :class="{ on: batchSource === 'url' }" @click="batchSource = 'url'">图片链接列表</button>
              <button class="seg-btn" :class="{ on: batchSource === 'file' }" @click="batchSource = 'file'">多文件</button>
            </div>
          </div>
          <div v-if="batchSource === 'url'" class="form-item">
            <label class="label">每行一个 URL，可用 "URL,商品ID" 格式</label>
            <textarea v-model="batchUrls" class="textarea" rows="8" placeholder="https://img1.jpg,sku001&#10;https://img2.jpg,sku002"></textarea>
          </div>
          <div v-else class="form-item">
            <label class="label">选择多个图片</label>
            <input type="file" class="input" multiple accept="image/*" @change="onBatchFiles" />
            <div class="hint">已选择 {{ batchFiles.length }} 个文件</div>
          </div>
          <div class="form-item">
            <label class="check"><input v-model="batchSaveToMinio" type="checkbox" /> 保存到 MinIO</label>
          </div>
          <div class="form-item">
            <button class="btn btn-primary" :disabled="uploading" @click="doBatch">
              <span v-if="uploading" class="spinner"></span><span v-else>开始批量导入</span>
            </button>
          </div>
          <div v-if="taskId" class="progress-box">
            <div class="progress-label">
              <span>导入进度：{{ taskProgress.current }} / {{ taskProgress.total }}</span>
              <span class="badge" :class="taskProgress.status === 'done' ? 'badge-ok' : 'badge-user'">{{ statusText }}</span>
            </div>
            <div class="progress-track"><div class="progress-fill" :style="{ width: pct + '%' }"></div></div>
            <div class="progress-detail">成功 {{ taskProgress.success }} · 失败 {{ taskProgress.failed }}</div>
          </div>
        </div>

        <!-- 目录导入 -->
        <div v-else class="form-grid">
          <div class="form-item">
            <label class="label">服务器目录路径</label>
            <input v-model="dirPath" class="input" placeholder="/data/images" />
          </div>
          <div class="form-item">
            <label class="check"><input v-model="dirSaveToMinio" type="checkbox" /> 保存到 MinIO</label>
          </div>
          <div class="form-item">
            <button class="btn btn-primary" :disabled="uploading" @click="doImport">开始导入</button>
          </div>
          <div v-if="dirTaskStarted" class="progress-box">
            <div class="progress-label">
              <span>导入进度：{{ importProgress.current }} / {{ importProgress.total }}</span>
              <span class="badge badge-user">{{ importProgress.status }}</span>
            </div>
            <div class="progress-track"><div class="progress-fill" :style="{ width: importPct + '%' }"></div></div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { searchApi } from '@/api/search'

const tabs = [
  { key: 'single', label: '单张上传' },
  { key: 'manual', label: '手动 ID' },
  { key: 'batch', label: '批量上传' },
  { key: 'directory', label: '目录导入' },
]
const active = ref('single')
const table = ref(localStorage.getItem('currentTable') || '')
const tables = ref<{ name: string; count: number }[]>([])
const uploading = ref(false)
const msg = ref('')
const msgErr = ref(false)

// 单张
const source = ref<'file' | 'url'>('file')
const singleFile = ref<File | null>(null)
const singleUrl = ref('')
const commodityId = ref('')
const customsParam = ref('')
const saveToMinio = ref(true)

// 手动 ID
const manualId = ref<number>(0)
const manualSource = ref<'file' | 'url'>('file')
const manualFile = ref<File | null>(null)
const manualUrl = ref('')
const manualCommodityId = ref('')
const manualSaveToMinio = ref(true)

// 批量
const batchSource = ref<'url' | 'file'>('url')
const batchUrls = ref('')
const batchFiles = ref<File[]>([])
const batchSaveToMinio = ref(true)
const taskId = ref('')
const taskProgress = ref<any>({ current: 0, total: 0, success: 0, failed: 0, status: 'pending' })
let taskTimer: number | undefined

// 目录
const dirPath = ref('')
const dirSaveToMinio = ref(true)
const dirTaskStarted = ref(false)
const importProgress = ref<any>({ current: 0, total: 0, status: 'idle' })
let dirTimer: number | undefined

const pct = computed(() => taskProgress.value.total ? Math.round(taskProgress.value.current / taskProgress.value.total * 100) : 0)
const importPct = computed(() => importProgress.value.total ? Math.round(importProgress.value.current / importProgress.value.total * 100) : 0)
const statusText = computed(() => {
  const map: Record<string, string> = { pending: '等待', running: '进行中', done: '完成', failed: '失败' }
  const s: string = taskProgress.value.status
  return map[s] || s
})

function result(message: string, isErr = false) { msg.value = message; msgErr.value = isErr }

async function loadTables() {
  try { tables.value = (await searchApi.listTables()).tables || [] } catch { /* ignore */ }
}

function onFile(e: Event) { singleFile.value = (e.target as HTMLInputElement).files?.[0] || null }
function onManualFile(e: Event) { manualFile.value = (e.target as HTMLInputElement).files?.[0] || null }
function onBatchFiles(e: Event) { batchFiles.value = Array.from((e.target as HTMLInputElement).files || []) }

async function doSingle() {
  if (source.value === 'file' && !singleFile.value) return result('请选择图片', true)
  if (source.value === 'url' && !singleUrl.value) return result('请输入图片 URL', true)
  uploading.value = true
  try {
    const form = new FormData()
    if (source.value === 'file') form.append('image', singleFile.value!)
    else form.append('image_url', singleUrl.value)
    form.append('commodity_id', commodityId.value)
    form.append('customs_param', customsParam.value)
    form.append('save_to_minio', String(saveToMinio.value))
    const res = await searchApi.uploadSingle(table.value, form)
    result(`上传成功，图片 ID：${res.imgId}`)
  } catch (e: any) { result(e.message, true) }
  finally { uploading.value = false }
}

async function doManual() {
  if (!manualId.value) return result('请输入 Milvus ID', true)
  if (manualSource.value === 'file' && !manualFile.value) return result('请选择图片', true)
  if (manualSource.value === 'url' && !manualUrl.value) return result('请输入图片 URL', true)
  uploading.value = true
  try {
    const form = new FormData()
    form.append('milvus_id', String(manualId.value))
    if (manualSource.value === 'file') form.append('image', manualFile.value!)
    else form.append('image_url', manualUrl.value)
    form.append('commodity_id', manualCommodityId.value)
    form.append('save_to_minio', String(manualSaveToMinio.value))
    const res = await searchApi.uploadManualId(table.value, form)
    result(`上传成功，图片 ID：${res.imgId}`)
  } catch (e: any) { result(e.message, true) }
  finally { uploading.value = false }
}

async function doBatch() {
  uploading.value = true
  try {
    let payload: any
    if (batchSource.value === 'url') {
      const items = batchUrls.value.split('\n').map(line => line.trim()).filter(Boolean).map(line => {
        const [url, cid] = line.split(',')
        return { image_url: url.trim(), commodity_id: (cid || '').trim() }
      })
      if (!items.length) return result('请输入至少一个图片 URL', true)
      payload = { items, save_to_minio: batchSaveToMinio.value, auto_id: true }
    } else {
      if (!batchFiles.value.length) return result('请选择图片文件', true)
      const form = new FormData()
      batchFiles.value.forEach(f => form.append('files', f))
      form.append('save_to_minio', String(batchSaveToMinio.value))
      payload = form
    }
    const res = await searchApi.uploadBatch(table.value, payload)
    taskId.value = res.taskId
    startTaskPolling()
    result(`任务已启动，共 ${res.total} 张`)
  } catch (e: any) { result(e.message, true) }
  finally { uploading.value = false }
}

function startTaskPolling() {
  clearInterval(taskTimer)
  taskTimer = window.setInterval(async () => {
    try {
      taskProgress.value = await searchApi.taskProgress(taskId.value)
      if (['done', 'failed'].includes(taskProgress.value.status)) clearInterval(taskTimer)
    } catch { clearInterval(taskTimer) }
  }, 800)
}

async function doImport() {
  if (!dirPath.value) return result('请输入目录路径', true)
  uploading.value = true
  try {
    await searchApi.importDirectory(table.value, dirPath.value, dirSaveToMinio.value)
    dirTaskStarted.value = true
    startDirPolling()
    result('目录导入任务已启动')
  } catch (e: any) { result(e.message, true) }
  finally { uploading.value = false }
}

function startDirPolling() {
  clearInterval(dirTimer)
  dirTimer = window.setInterval(async () => {
    try {
      importProgress.value = await searchApi.importProgress(table.value)
      if (importProgress.value.status === 'done') clearInterval(dirTimer)
    } catch { clearInterval(dirTimer) }
  }, 1000)
}

onMounted(loadTables)
onUnmounted(() => { clearInterval(taskTimer); clearInterval(dirTimer) })
</script>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.page-head h2 { margin: 0; font-size: 20px; }
.tabs { display: flex; gap: 4px; margin-bottom: 14px; }
.tab { padding: 9px 18px; font-size: 13px; color: var(--text-secondary); background: transparent; border: 1px solid transparent; border-radius: var(--radius-sm); cursor: pointer; transition: all var(--transition); }
.tab:hover { color: var(--text-primary); }
.tab.active { color: #fff; background: rgba(122,162,255,0.15); border-color: var(--glass-border-hover); }
.card { padding: 22px; }
.form-grid { max-width: 560px; }
.seg { display: inline-flex; padding: 3px; background: rgba(10,13,24,0.6); border-radius: var(--radius-sm); border: 1px solid var(--glass-border); }
.seg-btn { padding: 6px 14px; font-size: 13px; color: var(--text-secondary); background: transparent; border: none; border-radius: 6px; cursor: pointer; }
.seg-btn.on { color: #fff; background: rgba(122,162,255,0.25); }
.check { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--text-secondary); cursor: pointer; }
.check input { accent-color: var(--accent); }
.result-msg { margin-top: 14px; font-size: 13px; color: var(--success); }
.result-msg.err { color: var(--danger); }
.hint { font-size: 11px; color: var(--text-muted); margin-top: 6px; }
.progress-box { margin-top: 20px; padding: 14px; background: rgba(10,13,24,0.4); border: 1px solid var(--glass-border); border-radius: var(--radius-md); }
.progress-label { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 10px; }
.progress-detail { font-size: 12px; color: var(--text-muted); margin-top: 8px; }
</style>
