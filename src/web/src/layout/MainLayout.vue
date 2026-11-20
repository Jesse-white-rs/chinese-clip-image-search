<template>
  <div class="layout">
    <!-- 悬浮侧边栏 -->
    <aside class="sidebar glass-panel">
      <div class="brand">
        <div class="brand-mark">◈</div>
        <div class="brand-text">
          <div class="brand-title">图搜空间</div>
          <div class="brand-sub">SPATIAL SEARCH</div>
        </div>
      </div>

      <nav class="nav">
        <div class="nav-label">工作台</div>
        <router-link v-for="item in workNav" :key="item.path" :to="item.path"
                     class="nav-item" active-class="active">
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.title }}</span>
          <span class="nav-indicator"></span>
        </router-link>
        <div class="nav-label admin-label" v-if="adminNav.length">管理</div>
        <router-link v-for="item in adminNav" :key="item.path" :to="item.path"
                     class="nav-item" active-class="active">
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.title }}</span>
          <span class="nav-indicator"></span>
        </router-link>
      </nav>

      <div class="sidebar-foot">
        <div class="foot-status"><span class="status-dot"></span> 系统运行中</div>
        <div class="version">Chinese-CLIP · v1.0</div>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="main">
      <header class="topbar glass-panel">
        <div class="crumb">
          <span class="crumb-mark">✦</span>
          {{ currentTitle }}
        </div>
        <div class="topbar-right">
          <div class="table-picker">
            <span class="picker-icon">▤</span>
            <select v-model="currentTable" class="select picker-select" @change="onTableChange">
              <option value="">选择图库</option>
              <option v-for="t in tables" :key="t.name" :value="t.name">{{ t.name }}</option>
            </select>
          </div>
          <div class="topbar-divider"></div>
          <div class="user-menu">
            <div class="avatar">{{ (user?.username || '?').charAt(0).toUpperCase() }}</div>
            <div class="user-meta">
              <span class="username">{{ user?.username }}</span>
              <span class="user-role">{{ isAdmin ? '管理员' : '用户' }}</span>
            </div>
            <button class="icon-btn" title="退出登录" @click="onLogout">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="17" height="17">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>
              </svg>
            </button>
          </div>
        </div>
      </header>

      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { searchApi } from '@/api/search'

const router = useRouter()
const route = useRoute()
const store = useUserStore()
const user = computed(() => store.user)
const isAdmin = computed(() => store.isAdmin)

const currentTable = ref(localStorage.getItem('currentTable') || '')
const tables = ref<{ name: string; count: number }[]>([])

const workNav = [
  { path: '/dashboard', title: '系统概览', icon: '◉' },
  { path: '/images', title: '图片管理', icon: '▦' },
  { path: '/upload', title: '上传入库', icon: '↑' },
  { path: '/search', title: '图片检索', icon: '⌕' },
  { path: '/api-docs', title: '接口文档', icon: '⌘' },
]
const allAdminNav = [
  { path: '/tables', title: '图库管理', icon: '▤' },
  { path: '/backups', title: '定时备份', icon: '⤓' },
  { path: '/users', title: '用户管理', icon: '♙' },
  { path: '/logs', title: '系统日志', icon: '≡' },
  { path: '/perf', title: '性能检测', icon: '⌁' },
]
const adminNav = computed(() => isAdmin.value ? allAdminNav : [])
const currentTitle = computed(() => (route.meta.title as string) || '图搜空间')

async function loadTables() {
  try {
    const res = await searchApi.listTables()
    tables.value = res.tables || []
    if (currentTable.value && !tables.value.some(t => t.name === currentTable.value)) {
      currentTable.value = tables.value[0]?.name || ''
    }
  } catch { /* 静默 */ }
}

function onTableChange() {
  localStorage.setItem('currentTable', currentTable.value)
  window.dispatchEvent(new CustomEvent('table-change', { detail: currentTable.value }))
}
function onTableChangeEvent(e: Event) { currentTable.value = (e as CustomEvent).detail }

async function onLogout() {
  await store.logout()
  router.push('/login')
}

onMounted(() => {
  loadTables()
  window.addEventListener('table-change', onTableChangeEvent)
})
onUnmounted(() => window.removeEventListener('table-change', onTableChangeEvent))
watch(() => route.fullPath, () => { loadTables() })
</script>

<style scoped>
.layout { display: flex; height: 100vh; gap: 16px; padding: 16px; overflow: hidden; }

/* 悬浮侧边栏 */
.sidebar {
  width: 236px; flex-shrink: 0;
  padding: 24px 14px 18px;
  display: flex; flex-direction: column;
}
.brand { display: flex; align-items: center; gap: 13px; padding: 0 10px 28px; }
.brand-mark {
  width: 44px; height: 44px; flex-shrink: 0;
  display: grid; place-items: center; font-size: 24px; color: #fff;
  border-radius: 15px;
  background: linear-gradient(140deg, var(--aurora-1), var(--aurora-2) 60%, var(--aurora-3));
  box-shadow: 0 8px 26px rgba(122,162,255,0.35), inset 0 1px 0 rgba(255,255,255,0.4);
}
.brand-title { font-size: 16px; font-weight: 600; letter-spacing: 1px; }
.brand-sub { font-size: 9px; letter-spacing: 2.5px; color: var(--text-3); margin-top: 3px; }

.nav { flex: 1; display: flex; flex-direction: column; gap: 3px; overflow-y: auto; }
.nav-label {
  font-size: 10px; color: var(--text-3); letter-spacing: 1.5px;
  padding: 0 14px; margin: 8px 0 8px; text-transform: uppercase;
}
.admin-label { margin-top: 18px; }
.nav-item {
  position: relative;
  display: flex; align-items: center; gap: 13px;
  padding: 11px 14px;
  color: var(--text-2); text-decoration: none;
  border-radius: var(--r-sm); font-size: 14px;
  transition: var(--t);
}
.nav-item:hover { background: rgba(255,255,255,0.06); color: var(--text-1); }
.nav-item.active {
  color: #fff;
  background: linear-gradient(100deg, rgba(122,162,255,0.20), rgba(167,139,250,0.08));
  box-shadow: inset 0 0 0 1px rgba(138,180,255,0.18), 0 4px 18px rgba(122,162,255,0.12);
}
.nav-icon { width: 22px; text-align: center; font-size: 17px; }
.nav-indicator {
  position: absolute; right: 12px; width: 5px; height: 5px;
  border-radius: 50%; background: var(--accent);
  opacity: 0; box-shadow: 0 0 10px var(--accent); transition: var(--t);
}
.nav-item.active .nav-indicator { opacity: 1; }

.sidebar-foot { padding: 14px 10px 0; border-top: 1px solid rgba(255,255,255,0.07); }
.foot-status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-2); margin-bottom: 8px; }
.version { font-size: 10px; color: var(--text-3); letter-spacing: 0.5px; }

/* 主区域 */
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; gap: 16px; }

.topbar {
  padding: 14px 22px;
  display: flex; align-items: center; justify-content: space-between;
  border-radius: var(--r-md);
  flex-shrink: 0;
}
.crumb { display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 500; letter-spacing: 0.5px; }
.crumb-mark { color: var(--accent); font-size: 14px; }
.topbar-right { display: flex; align-items: center; gap: 18px; }
.table-picker { display: flex; align-items: center; gap: 9px; }
.picker-icon { color: var(--accent); font-size: 15px; }
.picker-select { width: auto; min-width: 150px; padding: 8px 32px 8px 12px; font-size: 13px; }
.topbar-divider { width: 1px; height: 26px; background: rgba(255,255,255,0.1); }
.user-menu { display: flex; align-items: center; gap: 11px; }
.avatar {
  width: 36px; height: 36px; display: grid; place-items: center;
  border-radius: 12px; font-size: 14px; font-weight: 600; color: #fff;
  background: linear-gradient(140deg, var(--aurora-2), var(--aurora-1));
  box-shadow: 0 4px 16px rgba(167,139,250,0.3), inset 0 1px 0 rgba(255,255,255,0.4);
}
.user-meta { display: flex; flex-direction: column; gap: 2px; }
.username { font-size: 13px; font-weight: 500; }
.user-role { font-size: 10px; color: var(--text-3); }
.icon-btn {
  width: 34px; height: 34px; display: grid; place-items: center;
  color: var(--text-2); background: rgba(255,255,255,0.05);
  border: 1px solid var(--glass-stroke); border-radius: 10px;
  cursor: pointer; transition: var(--t);
}
.icon-btn:hover { color: var(--danger); background: rgba(255,128,149,0.12); border-color: rgba(255,128,149,0.3); }

.content {
  flex: 1; overflow-y: auto; overflow-x: hidden;
  padding: 4px 4px 20px;
}
</style>
