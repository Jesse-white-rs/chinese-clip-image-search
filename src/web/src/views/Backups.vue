<template>
  <div>
    <div class="page-head">
      <h2>定时备份</h2>
      <button v-if="active === 'tasks'" class="btn btn-primary" @click="showCreate = true">+ 新建任务</button>
      <button v-else-if="active === 'files'" class="btn btn-sm" @click="loadFiles">刷新</button>
    </div>

    <div class="tabs">
      <button class="tab" :class="{ active: active === 'tasks' }" @click="switchTo('tasks')">备份任务</button>
      <button class="tab" :class="{ active: active === 'history' }" @click="switchTo('history')">执行历史</button>
      <button class="tab" :class="{ active: active === 'files' }" @click="switchTo('files')">备份文件</button>
    </div>

    <!-- 任务列表 -->
    <div v-if="active === 'tasks'" class="glass-panel card">
      <div v-if="loading" class="empty"><span class="spinner"></span> 加载中...</div>
      <div v-else-if="tasks.length === 0" class="empty">暂无备份任务，点击右上角新建</div>
      <table v-else class="table">
        <thead><tr><th>任务名</th><th>图库</th><th>Cron</th><th>状态</th><th>下次运行</th><th>上次结果</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.id">
            <td>{{ t.name }}</td>
            <td><span class="accent-text">{{ t.tableName }}</span></td>
            <td><code class="cron">{{ t.cronExpr }}</code></td>
            <td>
              <span class="badge" :class="t.enabled ? 'badge-ok' : 'badge-off'">{{ t.enabled ? '启用' : '停用' }}</span>
              <span v-if="t.includeMinio" class="badge badge-user" style="margin-left:6px">含MinIO清单</span>
            </td>
            <td class="muted">{{ t.nextRun || '—' }}</td>
            <td>
              <span class="badge" :class="t.lastStatus === 'success' ? 'badge-ok' : (t.lastStatus === 'failed' ? 'badge-off' : 'badge-user')">
                {{ t.lastStatus || '未执行' }}
              </span>
              <div class="muted small">{{ t.lastRun || '' }}</div>
            </td>
            <td>
              <button class="btn btn-sm" @click="runNow(t)">立即执行</button>
              <button class="btn btn-sm" @click="toggle(t)">{{ t.enabled ? '停用' : '启用' }}</button>
              <button class="btn btn-sm" @click="openEdit(t)">编辑</button>
              <button class="btn btn-sm btn-danger" @click="deleteTask(t)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="tip">Cron 为 5 段表达式：分 时 日 月 周，例如 <code>0 2 * * *</code> 表示每天凌晨 2 点。</div>
    </div>

    <!-- 执行历史 -->
    <div v-else-if="active === 'history'" class="glass-panel card">
      <div v-if="history.length === 0" class="empty">暂无执行记录</div>
      <table v-else class="table">
        <thead><tr><th>任务</th><th>图库</th><th>结果</th><th>信息</th><th>备份文件</th><th>开始时间</th></tr></thead>
        <tbody>
          <tr v-for="h in history" :key="h.id">
            <td>#{{ h.taskId }}</td>
            <td class="accent-text">{{ h.tableName }}</td>
            <td><span class="badge" :class="h.status === 'success' ? 'badge-ok' : 'badge-off'">{{ h.status }}</span></td>
            <td class="muted msg-cell" :title="h.message">{{ h.message }}</td>
            <td class="muted small">{{ fileName(h.filePath) }}</td>
            <td class="muted">{{ h.startedAt }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 备份文件 -->
    <div v-else class="glass-panel card">
      <div v-if="files.length === 0" class="empty">暂无备份文件</div>
      <table v-else class="table">
        <thead><tr><th>文件名</th><th>大小</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="f in files" :key="f.name">
            <td class="accent-text">{{ f.name }}</td>
            <td>{{ formatSize(f.sizeBytes) }}</td>
            <td class="muted">{{ f.createdAt }}</td>
            <td>
              <button class="btn btn-sm" @click="download(f.name)">下载</button>
              <button class="btn btn-sm btn-danger" @click="deleteFile(f.name)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="tip">备份文件按保留天数自动清理（默认 30 天）。</div>
    </div>

    <!-- 新建/编辑弹窗 -->
    <div v-if="showCreate" class="modal-mask" @click.self="closeModal">
      <div class="glass-panel modal">
        <h3>{{ editing ? '编辑备份任务' : '新建备份任务' }}</h3>
        <div class="form-item"><label class="label">任务名称</label><input v-model="form.name" class="input" placeholder="例如：每日备份商品图库" /></div>
        <div class="form-item">
          <label class="label">目标图库</label>
          <select v-model="form.table_name" class="select">
            <option value="">请选择</option>
            <option v-for="t in tableNames" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>
        <div class="form-item">
          <label class="label">Cron 表达式（分 时 日 月 周）</label>
          <input v-model="form.cron_expr" class="input" placeholder="0 2 * * *" />
          <div class="hint">每天 2 点：0 2 * * *　每 6 小时：0 */6 * * *</div>
        </div>
        <div class="form-item"><label class="label">备份文件保留天数</label><input v-model.number="form.retention_days" class="input" type="number" min="1" /></div>
        <div class="form-item"><label class="check"><input v-model="form.enabled" type="checkbox" /> 启用任务</label></div>
        <div class="form-item"><label class="check"><input v-model="form.include_minio" type="checkbox" /> 导出 MinIO 对象清单（不含原图文件）</label></div>
        <div v-if="err" class="error-msg">{{ err }}</div>
        <div class="modal-actions">
          <button class="btn" @click="closeModal">取消</button>
          <button class="btn btn-primary" @click="saveTask" :disabled="saving">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { backupApi, type BackupTask, type BackupHistory, type BackupFile } from '@/api/backup'
import { searchApi } from '@/api/search'
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()

const active = ref<'tasks' | 'history' | 'files'>('tasks')
const tasks = ref<BackupTask[]>([])
const history = ref<BackupHistory[]>([])
const files = ref<BackupFile[]>([])
const tableNames = ref<string[]>([])
const loading = ref(false)
const saving = ref(false)
const showCreate = ref(false)
const editing = ref<BackupTask | null>(null)
const err = ref('')

const form = ref({
  name: '', table_name: '', cron_expr: '0 2 * * *',
  enabled: true, include_minio: false, retention_days: 30,
})

function fileName(path: string) { return path ? path.split('/').pop() || '' : '—' }
function formatSize(size: number) {
  if (size < 1024) return `${size}B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)}GB`
}

async function loadTables() {
  try { tableNames.value = (await searchApi.listTables()).tables.map(t => t.name) } catch { /* ignore */ }
}
async function loadTasks() {
  loading.value = true
  try { tasks.value = (await backupApi.listTasks()).tasks || [] } catch { /* ignore */ }
  finally { loading.value = false }
}
async function loadHistory() {
  loading.value = true
  try { history.value = (await backupApi.history()).history || [] } catch { /* ignore */ }
  finally { loading.value = false }
}
async function loadFiles() {
  loading.value = true
  try { files.value = (await backupApi.files()).files || [] } catch { /* ignore */ }
  finally { loading.value = false }
}
async function switchTo(tab: 'tasks' | 'history' | 'files') {
  active.value = tab
  if (tab === 'tasks') loadTasks()
  else if (tab === 'history') loadHistory()
  else loadFiles()
}

function closeModal() { showCreate.value = false; editing.value = null; err.value = '' }
function openEdit(t: BackupTask) {
  editing.value = t
  form.value = {
    name: t.name, table_name: t.tableName, cron_expr: t.cronExpr,
    enabled: t.enabled, include_minio: t.includeMinio, retention_days: t.retentionDays,
  }
  err.value = ''
  showCreate.value = true
}

async function saveTask() {
  if (!form.value.name.trim() || !form.value.table_name) { err.value = '请填写任务名并选择图库'; return }
  saving.value = true
  err.value = ''
  try {
    if (editing.value) {
      await backupApi.updateTask(editing.value.id, {
        name: form.value.name, table_name: form.value.table_name,
        cron_expr: form.value.cron_expr, enabled: form.value.enabled,
        include_minio: form.value.include_minio, retention_days: form.value.retention_days,
      })
    } else {
      await backupApi.createTask(form.value)
    }
    const wasEdit = !!editing.value
    closeModal()
    await loadTasks()
    toast.success(wasEdit ? '任务已更新' : '任务已创建')
  } catch (e: any) { err.value = e.message }
  finally { saving.value = false }
}

async function toggle(t: BackupTask) {
  try { await backupApi.updateTask(t.id, { enabled: !t.enabled }); await loadTasks() } catch { /* ignore */ }
}
async function runNow(t: BackupTask) {
  try { await backupApi.runNow(t.id); toast.info('备份任务已启动，可在「执行历史」查看结果') } catch (e: any) { toast.error(e.message) }
}
async function deleteTask(t: BackupTask) {
  if (!confirm(`确定删除备份任务「${t.name}」？`)) return
  try { await backupApi.deleteTask(t.id); await loadTasks(); toast.success('任务已删除') } catch (e: any) { toast.error(e.message) }
}
async function deleteFile(name: string) {
  if (!confirm(`确定删除备份文件「${name}」？`)) return
  try { await backupApi.deleteFile(name); await loadFiles(); toast.success('备份文件已删除') } catch (e: any) { toast.error(e.message) }
}
async function download(name: string) {
  try { await backupApi.download(name); toast.success('下载已开始') } catch (e: any) { toast.error(e.message) }
}

onMounted(async () => { await loadTables(); await loadTasks() })
</script>

<style scoped>
/* tabs / tab / card 由 glass.css 统一提供 */
.table td .btn { margin-right: 6px; }
.accent-text { color: var(--accent); }
.cron { font-size: 12px; color: var(--accent); background: rgba(90,158,140,0.14); padding: 2px 6px; border-radius: 4px; }
.muted { color: var(--text-muted); font-size: 12px; }
.small { font-size: 11px; }
.msg-cell { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tip { margin-top: 14px; font-size: 12px; color: var(--text-muted); }
.hint { font-size: 11px; color: var(--text-muted); margin-top: 5px; }
.modal-mask { position: fixed; inset: 0; background: rgba(3,7,15,0.7); display: grid; place-items: center; z-index: 50; backdrop-filter: blur(4px); }
.modal { width: 460px; max-width: 92%; padding: 26px; max-height: 90vh; overflow: auto; }
.modal h3 { margin: 0 0 20px; font-size: 17px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }
.check { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--text-secondary); cursor: pointer; }
.check input { accent-color: var(--accent); }
.error-msg { font-size: 13px; color: var(--danger); margin: 8px 0; }
</style>
