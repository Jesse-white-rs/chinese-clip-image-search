<template>
  <div class="docs-page">
    <!-- 左侧目录 -->
    <aside class="docs-side glass-panel">
      <div class="side-head">
        <span class="side-icon">⌘</span>
        <span>API 目录</span>
      </div>
      <div class="search-wrap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="search-icon">
          <circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/>
        </svg>
        <input v-model="keyword" class="input search-input" placeholder="搜索接口..." />
      </div>
      <div class="nav-groups">
        <div v-for="group in filteredGroups" :key="group" class="nav-group">
          <div class="group-label">{{ group }}</div>
          <a v-for="ep in endpointsByGroup(group)" :key="ep.id"
             class="nav-link" :href="'#' + ep.id" @click="activeId = ep.id"
             :class="{ active: activeId === ep.id }">
            <span class="method-tag" :class="'m-' + ep.method.toLowerCase()">{{ ep.method }}</span>
            <span class="link-title">{{ ep.title }}</span>
          </a>
        </div>
        <div v-if="filteredGroups.length === 0" class="no-result">未找到匹配的接口</div>
      </div>
    </aside>

    <!-- 右侧内容 -->
    <main class="docs-content">
      <!-- 顶部说明 -->
      <div class="docs-intro glass-panel">
        <div class="intro-head">
          <div class="intro-badge">API</div>
          <div>
            <h1>图搜服务接口文档</h1>
            <p>基础地址 <code>{{ baseUrl }}</code> · 统一返回 <code>{ status, message, data }</code></p>
          </div>
        </div>
        <div class="auth-notes">
          <div v-for="note in notes" :key="note.title" class="note" :class="'note-' + note.tone">
            <div class="note-title">{{ note.title }}</div>
            <div class="note-body">{{ note.body }}</div>
          </div>
        </div>
      </div>

      <!-- 接口卡片 -->
      <div v-for="group in filteredGroups" :key="'c-' + group" class="endpoint-group">
        <h2 class="group-heading">{{ group }}</h2>
        <div v-for="ep in endpointsByGroup(group)" :key="ep.id" :id="ep.id"
             class="endpoint-card glass-panel" :class="{ highlighted: activeId === ep.id }">
          <div class="ep-head">
            <span class="method-tag lg" :class="'m-' + ep.method.toLowerCase()">{{ ep.method }}</span>
            <code class="ep-path">{{ ep.path }}</code>
            <span class="auth-badge" :class="'auth-' + ep.auth">{{ ep.auth }}</span>
          </div>
          <h3 class="ep-title">{{ ep.title }}</h3>
          <p class="ep-desc">{{ ep.desc }}</p>

          <!-- 参数表 -->
          <div v-if="ep.params && ep.params.length" class="ep-section">
            <div class="section-label">参数</div>
            <div class="param-table">
              <div class="param-row" v-for="p in ep.params" :key="p.name">
                <span class="p-name">{{ p.name }}</span>
                <span class="p-in">{{ p.in }}</span>
                <span class="p-type">{{ p.type }}</span>
                <span class="p-req" :class="{ required: p.required }">{{ p.required ? '必填' : '可选' }}</span>
                <span class="p-desc">{{ p.desc }}</span>
              </div>
            </div>
          </div>

          <!-- 请求示例 -->
          <div v-if="ep.request" class="ep-section">
            <div class="section-label">请求示例</div>
            <div class="code-block">
              <button class="copy-btn" @click="copy(ep.request!, ep.id + '-req')">
                {{ copied === ep.id + '-req' ? '已复制' : '复制' }}
              </button>
              <pre>{{ ep.request }}</pre>
            </div>
          </div>

          <!-- 返回示例 -->
          <div class="ep-section">
            <div class="section-label">返回示例</div>
            <div class="code-block">
              <button class="copy-btn" @click="copy(ep.response, ep.id + '-res')">
                {{ copied === ep.id + '-res' ? '已复制' : '复制' }}
              </button>
              <pre>{{ ep.response }}</pre>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ENDPOINTS, GROUPS, AUTH_NOTES, BASE_URL, type ApiEndpoint } from '@/data/apiDocs'

const keyword = ref('')
const activeId = ref('auth-login')
const copied = ref('')
const notes = AUTH_NOTES
const baseUrl = BASE_URL

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return ENDPOINTS
  return ENDPOINTS.filter(ep =>
    [ep.title, ep.path, ep.desc, ep.method, ep.group].some(v => v.toLowerCase().includes(kw))
  )
})
const filteredGroups = computed(() => GROUPS.filter(g => filtered.value.some(ep => ep.group === g)))
function endpointsByGroup(group: string): ApiEndpoint[] {
  return filtered.value.filter(ep => ep.group === group)
}

async function copy(text: string, key: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = key
    setTimeout(() => { copied.value = '' }, 1800)
  } catch {
    // 剪贴板不可用时降级
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    copied.value = key
    setTimeout(() => { copied.value = '' }, 1800)
  }
}
</script>

<style scoped>
.docs-page { display: flex; gap: 18px; height: 100%; }

/* 左侧目录 */
.docs-side {
  width: 280px; flex-shrink: 0;
  padding: 18px 14px;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.side-head { display: flex; align-items: center; gap: 9px; font-size: 15px; font-weight: 600; padding: 0 6px 16px; }
.side-icon { color: var(--accent); font-size: 17px; }
.search-wrap { position: relative; margin-bottom: 14px; }
.search-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 15px; height: 15px; color: var(--text-3); }
.search-input { padding-left: 36px; font-size: 12px; }
.nav-groups { flex: 1; overflow-y: auto; }
.group-label { font-size: 10px; letter-spacing: 1.5px; color: var(--text-3); padding: 12px 8px 6px; text-transform: uppercase; }
.nav-link {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 9px; border-radius: 9px;
  color: var(--text-2); text-decoration: none; font-size: 12px;
  transition: var(--t);
}
.nav-link:hover { background: rgba(255,255,255,0.06); color: var(--text-1); }
.nav-link.active { background: rgba(90,158,140,0.15); color: #fff; }
.link-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.no-result { padding: 20px; text-align: center; color: var(--text-3); font-size: 12px; }

/* 右侧内容 */
.docs-content { flex: 1; min-width: 0; overflow-y: auto; padding-right: 4px; }
.docs-intro { padding: 26px 30px; margin-bottom: 24px; }
.intro-head { display: flex; align-items: center; gap: 18px; margin-bottom: 22px; }
.intro-badge {
  width: 56px; height: 56px; flex-shrink: 0;
  display: grid; place-items: center;
  font-size: 16px; font-weight: 700; letter-spacing: 1px; color: #fff;
  border-radius: 18px;
  background: linear-gradient(140deg, var(--aurora-1), var(--aurora-2));
  box-shadow: 0 8px 26px rgba(90,158,140,0.35), inset 0 1px 0 rgba(255,255,255,0.4);
}
.intro-head h1 { margin: 0 0 6px; font-size: 22px; font-weight: 600; }
.intro-head p { margin: 0; font-size: 13px; color: var(--text-2); }
.intro-head code { color: var(--accent); background: rgba(90,158,140,0.1); padding: 2px 7px; border-radius: 5px; font-size: 12px; }
.auth-notes { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.note { padding: 14px 16px; border-radius: var(--r-sm); border: 1px solid var(--glass-stroke); background: rgba(255,255,255,0.03); }
.note-ok { border-left: 3px solid var(--success); }
.note-warn { border-left: 3px solid var(--warning); }
.note-info { border-left: 3px solid var(--accent); }
.note-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.note-body { font-size: 12px; color: var(--text-2); line-height: 1.6; }

.group-heading { font-size: 16px; font-weight: 600; margin: 28px 0 14px; padding-left: 4px; }
.endpoint-card { padding: 22px 26px; margin-bottom: 16px; scroll-margin-top: 10px; transition: var(--t); }
.endpoint-card.highlighted { border-color: rgba(90,158,140,0.4); box-shadow: var(--glass-shadow), 0 0 0 1px rgba(90,158,140,0.2); }
.ep-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.ep-path { font-size: 13px; color: var(--text-1); background: rgba(0,0,0,0.25); padding: 5px 10px; border-radius: 7px; }
.ep-title { margin: 0 0 6px; font-size: 17px; font-weight: 600; }
.ep-desc { margin: 0 0 18px; font-size: 13px; color: var(--text-2); line-height: 1.6; }

/* 方法标签 */
.method-tag {
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700; letter-spacing: 0.5px;
  padding: 3px 7px; border-radius: 6px; min-width: 48px;
}
.method-tag.lg { font-size: 11px; padding: 5px 10px; min-width: 58px; }
.m-get { color: #5ee6a8; background: rgba(94,230,168,0.15); border: 1px solid rgba(94,230,168,0.3); }
.m-post { color: var(--accent); background: rgba(90,158,140,0.15); border: 1px solid rgba(90,158,140,0.3); }
.m-put { color: #ffcc7a; background: rgba(255,204,122,0.15); border: 1px solid rgba(255,204,122,0.3); }
.m-delete { color: #ff8095; background: rgba(255,128,149,0.15); border: 1px solid rgba(255,128,149,0.3); }

.auth-badge { font-size: 11px; padding: 3px 10px; border-radius: var(--r-pill); border: 1px solid var(--glass-stroke); }
.auth-公开 { color: var(--success); background: rgba(94,230,168,0.10); }
.auth-登录 { color: var(--accent); background: rgba(90,158,140,0.10); }
.auth-管理员 { color: var(--accent-2); background: rgba(127,186,168,0.10); }

.ep-section { margin-top: 16px; }
.section-label { font-size: 11px; letter-spacing: 1px; color: var(--text-3); margin-bottom: 9px; text-transform: uppercase; }
.param-table { border: 1px solid var(--glass-stroke); border-radius: var(--r-sm); overflow: hidden; }
.param-row {
  display: grid; grid-template-columns: 1.1fr 0.6fr 0.7fr 0.6fr 2fr;
  gap: 10px; padding: 9px 13px; font-size: 12px; align-items: center;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}
.param-row:last-child { border-bottom: none; }
.p-name { color: var(--accent); font-family: monospace; }
.p-in { color: var(--text-3); }
.p-type { color: var(--text-2); font-family: monospace; }
.p-req { color: var(--text-3); font-size: 11px; }
.p-req.required { color: var(--danger); }
.p-desc { color: var(--text-2); }

.code-block { position: relative; background: rgba(4,6,14,0.6); border: 1px solid var(--glass-stroke); border-radius: var(--r-sm); padding: 14px 16px; }
.code-block pre { margin: 0; font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px; line-height: 1.6; color: #c8d3f5; white-space: pre-wrap; word-break: break-word; }
.copy-btn {
  position: absolute; top: 8px; right: 8px;
  font-size: 11px; padding: 4px 10px;
  color: var(--text-2); background: rgba(255,255,255,0.07);
  border: 1px solid var(--glass-stroke); border-radius: 7px;
  cursor: pointer; transition: var(--t);
}
.copy-btn:hover { color: #fff; background: rgba(90,158,140,0.2); }

@media (max-width: 900px) {
  .docs-side { display: none; }
  .param-row { grid-template-columns: 1fr 1fr; }
}
</style>
