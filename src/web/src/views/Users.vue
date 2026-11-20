<template>
  <div>
    <div class="page-head">
      <h2>用户管理</h2>
      <button class="btn btn-primary" @click="showCreate = true">+ 新建用户</button>
    </div>

    <div class="glass-panel card">
      <div v-if="loading" class="empty"><span class="spinner"></span> 加载中...</div>
      <table v-else class="table">
        <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>状态</th><th>最后登录</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.id }}</td>
            <td>{{ u.username }}</td>
            <td><span class="badge" :class="u.role === 'admin' ? 'badge-admin' : 'badge-user'">{{ u.role === 'admin' ? '管理员' : '普通用户' }}</span></td>
            <td><span class="badge" :class="u.isActive ? 'badge-ok' : 'badge-off'">{{ u.isActive ? '启用' : '禁用' }}</span></td>
            <td class="muted">{{ u.lastLogin || '从未登录' }}</td>
            <td>
              <button class="btn btn-sm" @click="openEdit(u)">编辑</button>
              <button class="btn btn-sm" @click="openPwd(u)">重置密码</button>
              <button class="btn btn-sm btn-danger" @click="onDelete(u)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="pager" v-if="totalPages > 1">
        <button class="btn btn-sm" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
        <span class="page-info">第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn btn-sm" :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
      </div>
    </div>

    <!-- 新建用户 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="glass-panel modal">
        <h3>新建用户</h3>
        <div class="form-item"><label class="label">用户名</label><input v-model="form.username" class="input" /></div>
        <div class="form-item"><label class="label">密码</label><input v-model="form.password" class="input" type="password" /></div>
        <div class="form-item"><label class="label">角色</label>
          <select v-model="form.role" class="select"><option value="user">普通用户</option><option value="admin">管理员</option></select>
        </div>
        <div v-if="err" class="error-msg">{{ err }}</div>
        <div class="modal-actions"><button class="btn" @click="showCreate = false">取消</button><button class="btn btn-primary" @click="onCreate">创建</button></div>
      </div>
    </div>

    <!-- 编辑用户 -->
    <div v-if="showEdit" class="modal-mask" @click.self="showEdit = false">
      <div class="glass-panel modal">
        <h3>编辑用户 · {{ editTarget?.username }}</h3>
        <div class="form-item"><label class="label">角色</label>
          <select v-model="editRole" class="select"><option value="user">普通用户</option><option value="admin">管理员</option></select>
        </div>
        <div class="form-item"><label class="check"><input v-model="editActive" type="checkbox" /> 账号启用</label></div>
        <div v-if="err" class="error-msg">{{ err }}</div>
        <div class="modal-actions"><button class="btn" @click="showEdit = false">取消</button><button class="btn btn-primary" @click="onUpdate">保存</button></div>
      </div>
    </div>

    <!-- 重置密码 -->
    <div v-if="showPwd" class="modal-mask" @click.self="showPwd = false">
      <div class="glass-panel modal">
        <h3>重置密码 · {{ pwdTarget?.username }}</h3>
        <div class="form-item"><label class="label">新密码</label><input v-model="newPwd" class="input" type="password" /></div>
        <div v-if="err" class="error-msg">{{ err }}</div>
        <div class="modal-actions"><button class="btn" @click="showPwd = false">取消</button><button class="btn btn-primary" @click="onResetPwd">确认</button></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { authApi } from '@/api/auth'

interface User { id: number; username: string; role: string; isActive: boolean; lastLogin: string | null }
const users = ref<User[]>([])
const page = ref(1)
const size = 10
const totalPages = ref(0)
const loading = ref(true)
const err = ref('')

const showCreate = ref(false)
const form = ref({ username: '', password: '', role: 'user' })

const showEdit = ref(false)
const editTarget = ref<User | null>(null)
const editRole = ref('user')
const editActive = ref(true)

const showPwd = ref(false)
const pwdTarget = ref<User | null>(null)
const newPwd = ref('')

async function load() {
  loading.value = true
  try {
    const res = await authApi.listUsers(page.value, size)
    users.value = res.data || []
    totalPages.value = res.totalPages || 0
  } catch { /* ignore */ }
  finally { loading.value = false }
}
function go(p: number) { page.value = p; load() }

async function onCreate() {
  err.value = ''
  try {
    await authApi.createUser(form.value)
    showCreate.value = false
    form.value = { username: '', password: '', role: 'user' }
    await load()
  } catch (e: any) { err.value = e.message }
}
function openEdit(u: User) {
  editTarget.value = u
  editRole.value = u.role
  editActive.value = u.isActive
  err.value = ''
  showEdit.value = true
}
async function onUpdate() {
  if (!editTarget.value) return
  try {
    await authApi.updateUser(editTarget.value.id, { role: editRole.value, isActive: editActive.value })
    showEdit.value = false
    await load()
  } catch (e: any) { err.value = e.message }
}
function openPwd(u: User) { pwdTarget.value = u; newPwd.value = ''; err.value = ''; showPwd.value = true }
async function onResetPwd() {
  if (!pwdTarget.value || !newPwd.value) { err.value = '请输入新密码'; return }
  try {
    await authApi.resetPassword(pwdTarget.value.id, newPwd.value)
    showPwd.value = false
  } catch (e: any) { err.value = e.message }
}
async function onDelete(u: User) {
  if (!confirm(`确定删除用户「${u.username}」？`)) return
  try { await authApi.deleteUser(u.id); await load() } catch (e: any) { err.value = e.message }
}

onMounted(load)
</script>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-head h2 { margin: 0; font-size: 20px; }
.card { padding: 18px; }
.table td .btn { margin-right: 6px; }
.muted { color: var(--text-muted); font-size: 12px; }
.pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 18px; }
.page-info { font-size: 13px; color: var(--text-secondary); }
.modal-mask { position: fixed; inset: 0; background: rgba(3,7,15,0.7); display: grid; place-items: center; z-index: 50; backdrop-filter: blur(4px); }
.modal { width: 420px; max-width: 92%; padding: 26px; }
.modal h3 { margin: 0 0 20px; font-size: 17px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }
.check { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--text-secondary); cursor: pointer; }
.check input { accent-color: var(--accent); }
.error-msg { font-size: 13px; color: var(--danger); margin: 8px 0; }
</style>
