<template>
  <div>
    <div class="page-head">
      <h2>图库管理</h2>
      <button class="btn btn-primary" @click="showCreate = true">+ 新建图库</button>
    </div>

    <div class="glass-panel card">
      <div v-if="loading" class="empty"><span class="spinner"></span> 加载中...</div>
      <div v-else-if="tables.length === 0" class="empty">暂无图库，点击右上角新建</div>
      <table v-else class="table">
        <thead><tr><th>图库名称</th><th>图片数量</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="t in tables" :key="t.name">
            <td><span class="table-name">▤ {{ t.name }}</span></td>
            <td>{{ t.count.toLocaleString() }}</td>
            <td>
              <button class="btn btn-sm" @click="selectTable(t.name)">设为当前</button>
              <button class="btn btn-sm btn-danger" @click="confirmDelete(t)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 新建弹窗 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="glass-panel modal">
        <h3>新建图库</h3>
        <div class="form-item">
          <label class="label">图库名称</label>
          <input v-model="newName" class="input" placeholder="例如：product_images" @keyup.enter="onCreate" />
        </div>
        <div v-if="err" class="error-msg">{{ err }}</div>
        <div class="modal-actions">
          <button class="btn" @click="showCreate = false">取消</button>
          <button class="btn btn-primary" @click="onCreate" :disabled="creating">创建</button>
        </div>
      </div>
    </div>

    <!-- 删除确认 -->
    <div v-if="deleteTarget" class="modal-mask" @click.self="deleteTarget = null">
      <div class="glass-panel modal">
        <h3>删除图库</h3>
        <p class="warn-text">确定删除图库「{{ deleteTarget.name }}」？此操作不可恢复。</p>
        <label class="check"><input v-model="cascade" type="checkbox" /> 同时删除 MinIO 中的原图</label>
        <div class="modal-actions">
          <button class="btn" @click="deleteTarget = null">取消</button>
          <button class="btn btn-danger" @click="onDelete" :disabled="deleting">确认删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { searchApi } from '@/api/search'

interface TableItem { name: string; count: number }
const tables = ref<TableItem[]>([])
const loading = ref(true)
const showCreate = ref(false)
const newName = ref('')
const creating = ref(false)
const err = ref('')
const deleteTarget = ref<TableItem | null>(null)
const cascade = ref(false)
const deleting = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await searchApi.listTables()
    tables.value = res.tables || []
  } catch { /* ignore */ }
  finally { loading.value = false }
}

function selectTable(name: string) {
  localStorage.setItem('currentTable', name)
  // 触发顶部选择器同步：派发自定义事件后由布局监听
  window.dispatchEvent(new CustomEvent('table-change', { detail: name }))
}

async function onCreate() {
  if (!newName.value.trim()) { err.value = '请输入图库名称'; return }
  creating.value = true
  err.value = ''
  try {
    await searchApi.createTable(newName.value.trim())
    showCreate.value = false
    newName.value = ''
    await load()
  } catch (e: any) { err.value = e.message }
  finally { creating.value = false }
}

function confirmDelete(t: TableItem) {
  deleteTarget.value = t
  cascade.value = false
}

async function onDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await searchApi.deleteTable(deleteTarget.value.name, cascade.value)
    if (localStorage.getItem('currentTable') === deleteTarget.value.name) {
      localStorage.removeItem('currentTable')
    }
    deleteTarget.value = null
    await load()
  } catch (e: any) { err.value = e.message }
  finally { deleting.value = false }
}

onMounted(load)
</script>

<style scoped>
.table-name { color: var(--accent); }
.table td .btn { margin-right: 8px; }
.modal-mask { position: fixed; inset: 0; background: rgba(3,7,15,0.7); display: grid; place-items: center; z-index: 50; backdrop-filter: blur(4px); }
.modal { width: 420px; max-width: 92%; padding: 26px; }
.modal h3 { margin: 0 0 20px; font-size: 17px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }
.warn-text { font-size: 13px; color: var(--text-secondary); line-height: 1.6; }
.check { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--text-secondary); cursor: pointer; margin-top: 12px; }
.check input { accent-color: var(--accent); }
.error-msg { font-size: 13px; color: var(--danger); margin: 8px 0; }
</style>
