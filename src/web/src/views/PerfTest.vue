<template>
  <div>
    <div class="page-head">
      <h2>性能检测</h2>
      <span class="head-hint">压测任务在服务端后台执行，关闭页面不影响运行</span>
    </div>

    <div class="perf-grid">
      <!-- 配置卡片 -->
      <div class="glass-panel card config-card">
        <div class="card-title"><span class="title-icon">⚙</span> 压测配置</div>

        <div class="form-item">
          <label class="label">测试场景</label>
          <div class="scenario-list">
            <button v-for="s in scenarios" :key="s.value" class="scenario-btn"
                    :class="{ on: form.scenario === s.value }" @click="form.scenario = s.value">
              <span class="sc-icon">{{ s.icon }}</span>
              <span class="sc-name">{{ s.label }}</span>
              <span class="sc-desc">{{ s.desc }}</span>
            </button>
          </div>
        </div>

        <div class="form-item">
          <label class="label">目标图库</label>
          <select v-model="form.table_name" class="select">
            <option value="">请选择图库</option>
            <option v-for="t in tables" :key="t.name" :value="t.name">{{ t.name }}</option>
          </select>
        </div>

        <div class="form-item">
          <label class="label">请求量级</label>
          <div class="preset-row">
            <button v-for="p in presets" :key="p.value" class="preset-btn"
                    :class="{ on: form.total === p.value }" @click="form.total = p.value">
              {{ p.label }}
            </button>
          </div>
          <input v-model.number="form.total" class="input" type="number" min="1" max="2000000"
                 placeholder="自定义请求数（1 ~ 2,000,000）" style="margin-top:10px" />
        </div>

        <div class="form-item">
          <label class="label">并发数：{{ form.concurrency }}</label>
          <input v-model.number="form.concurrency" type="range" min="1" max="128" class="range" />
          <div class="range-marks"><span>1</span><span>32</span><span>64</span><span>128</span></div>
        </div>

        <div v-if="form.scenario === 'search_text'" class="form-item">
          <label class="label">测试文本</label>
          <input v-model="form.query_text" class="input" placeholder="红色物体" />
        </div>

        <div v-if="form.scenario === 'upload'" class="warning-box">
          <span class="warning-icon">⚠</span>
          <div><b>注意：</b>上传压测会真实写入向量与映射记录，{{ form.total >= 100000 ? '当前为十万级以上，将产生大量数据，请谨慎执行！' : '请确认图库与磁盘空间充足。' }}</div>
        </div>

        <button class="btn btn-primary start-btn" @click="startTest" :disabled="running || !form.table_name">
          <span v-if="running" class="spinner"></span>
          <span v-else>▶ 开始压测</span>
        </button>
      </div>

      <!-- 实时进度 / 结果 -->
      <div class="glass-panel card result-card">
        <div class="card-title"><span class="title-icon">▤</span> 运行结果</div>

        <div v-if="!taskId" class="empty-area">
          <div class="empty-icon">⌁</div>
          <p>配置参数后点击「开始压测」</p>
          <p class="sub">这里会实时显示进度与性能指标</p>
        </div>

        <template v-else>
          <!-- 进度 -->
          <div v-if="progress.status === 'running' || progress.status === 'pending'" class="running-area">
            <div class="running-head">
              <span class="running-label"><span class="spinner"></span> 压测进行中...</span>
              <span class="badge badge-user">{{ statusLabel(progress.status) }}</span>
            </div>
            <div class="progress-label">
              <span>{{ progress.current.toLocaleString() }} / {{ progress.total.toLocaleString() }}</span>
              <span>{{ progressPct }}%</span>
            </div>
            <div class="progress-track"><div class="progress-fill" :style="{ width: progressPct + '%' }"></div></div>
            <div class="progress-stats">
              <span class="ok-text">成功 {{ progress.success.toLocaleString() }}</span>
              <span class="err-text">失败 {{ progress.failed.toLocaleString() }}</span>
            </div>
          </div>

          <!-- 结果 -->
          <template v-else-if="result">
            <div class="result-head">
              <span class="badge" :class="result.failed === 0 ? 'badge-ok' : 'badge-off'">
                {{ result.failed === 0 ? '全部成功' : `${result.failed} 次失败` }}
              </span>
              <span class="result-meta">{{ result.duration }}s · 并发 {{ result.concurrency }} · {{ result.scenario }}</span>
            </div>

            <!-- 核心指标 -->
            <div class="metric-grid">
              <div class="metric primary">
                <div class="metric-value">{{ result.qps.toLocaleString() }}</div>
                <div class="metric-label">QPS（每秒请求）</div>
              </div>
              <div class="metric">
                <div class="metric-value">{{ result.avgMs }}<small>ms</small></div>
                <div class="metric-label">平均延迟</div>
              </div>
              <div class="metric">
                <div class="metric-value">{{ result.p95Ms }}<small>ms</small></div>
                <div class="metric-label">P95 延迟</div>
              </div>
              <div class="metric">
                <div class="metric-value">{{ result.p99Ms }}<small>ms</small></div>
                <div class="metric-label">P99 延迟</div>
              </div>
            </div>

            <!-- 分位数条形图 -->
            <div class="chart-section">
              <div class="section-label">延迟分布（毫秒）</div>
              <div v-for="bar in percentileBars" :key="bar.label" class="bar-row">
                <span class="bar-label">{{ bar.label }}</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: bar.width + '%' }"></div></div>
                <span class="bar-value">{{ bar.value }}ms</span>
              </div>
            </div>

            <!-- 详情 -->
            <div class="detail-grid">
              <div><span>总请求</span><b>{{ result.total.toLocaleString() }}</b></div>
              <div><span>成功</span><b class="ok-text">{{ result.success.toLocaleString() }}</b></div>
              <div><span>失败</span><b class="err-text">{{ result.failed.toLocaleString() }}</b></div>
              <div><span>总耗时</span><b>{{ result.duration }}s</b></div>
            </div>

            <div v-if="result.errors && result.errors.length" class="errors-box">
              <div class="section-label">错误示例（最多 20 条）</div>
              <div v-for="(e, i) in result.errors" :key="i" class="error-line">{{ e }}</div>
            </div>
          </template>
        </template>
      </div>
    </div>

    <!-- 历史记录 -->
    <div class="glass-panel card history-card">
      <div class="card-title">
        <span class="title-icon">◷</span> 历史记录
        <button class="btn btn-sm" style="margin-left:auto" @click="loadHistory">刷新</button>
      </div>
      <div v-if="history.length === 0" class="empty">暂无历史记录</div>
      <table v-else class="table">
        <thead><tr><th>场景</th><th>图库</th><th>查询文本</th><th>请求数</th><th>并发</th><th>QPS</th><th>平均</th><th>P95</th><th>结果</th><th>时间</th><th></th></tr></thead>
        <tbody>
          <tr v-for="h in history" :key="h.taskId">
            <td>{{ scenarioLabel(h.scenario) }}</td>
            <td class="accent-text">{{ h.tableName }}</td>
            <td class="muted small">{{ h.queryText || '-' }}</td>
            <td>{{ h.total.toLocaleString() }}</td>
            <td>{{ h.concurrency }}</td>
            <td class="accent-text">{{ h.qps }}</td>
            <td>{{ h.avgMs }}ms</td>
            <td>{{ h.p95Ms }}ms</td>
            <td>
              <span v-if="h.status === 'running'" class="badge badge-user">进行中</span>
              <span v-else class="badge" :class="h.failed === 0 ? 'badge-ok' : 'badge-off'">{{ h.failed === 0 ? '成功' : h.failed + '失败' }}</span>
            </td>
            <td class="muted small">{{ h.createdAt }}</td>
            <td><button class="btn btn-sm" @click="loadResult(h.taskId)">查看</button>
                <button class="btn btn-sm btn-danger" @click="deleteHistory(h.taskId)">删</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { perfApi, type PerfResult, type PerfProgress } from '@/api/perf'
import { searchApi } from '@/api/search'

const scenarios = [
  { value: 'upload', label: '图片上传', icon: '↑', desc: '测入库吞吐' },
  { value: 'search_image', label: '以图搜图', icon: '⌕', desc: '测图像检索' },
  { value: 'search_text', label: '文本搜图', icon: '⌨', desc: '测中文检索' },
]
const presets = [
  { value: 1000, label: '1 千' },
  { value: 10000, label: '1 万' },
  { value: 100000, label: '10 万' },
  { value: 1000000, label: '100 万' },
]

const form = ref({
  scenario: 'search_image', table_name: '', total: 1000,
  concurrency: 8, query_text: '红色物体',
})
const tables = ref<{ name: string; count: number }[]>([])
const taskId = ref('')
const progress = ref<PerfProgress>({
  taskId: '', scenario: '', current: 0, total: 0, success: 0, failed: 0, status: 'pending', message: '',
})
const result = ref<PerfResult | null>(null)
const history = ref<PerfResult[]>([])
const running = ref(false)
let timer: number | undefined

const progressPct = computed(() =>
  progress.value.total ? Math.round(progress.value.current / progress.value.total * 100) : 0
)
const percentileBars = computed(() => {
  if (!result.value) return []
  const r = result.value
  const max = Math.max(r.p99Ms, 1)
  return [
    { label: 'P50', value: r.p50Ms, width: Math.max(2, r.p50Ms / max * 100) },
    { label: 'P90', value: r.p90Ms, width: Math.max(2, r.p90Ms / max * 100) },
    { label: 'P95', value: r.p95Ms, width: Math.max(2, r.p95Ms / max * 100) },
    { label: 'P99', value: r.p99Ms, width: Math.max(2, r.p99Ms / max * 100) },
  ]
})

function statusLabel(s: string) {
  return { pending: '等待中', running: '进行中', done: '已完成' }[s] || s
}
function scenarioLabel(s: string) {
  return { upload: '图片上传', search_image: '以图搜图', search_text: '文本搜图' }[s] || s
}

async function loadTables() {
  try { tables.value = (await searchApi.listTables()).tables || [] } catch { /* ignore */ }
}
async function loadHistory() {
  try { history.value = (await perfApi.history()).results || [] } catch { /* ignore */ }
}

async function startTest() {
  if (!form.value.table_name) return
  if (form.value.scenario === 'upload' && form.value.total >= 100000) {
    if (!confirm(`即将执行 ${form.value.total.toLocaleString()} 次上传压测，会写入大量数据。确定继续？`)) return
  }
  running.value = true
  result.value = null
  try {
    const res = await perfApi.start({
      scenario: form.value.scenario, table_name: form.value.table_name,
      total: form.value.total, concurrency: form.value.concurrency,
      query_text: form.value.query_text,
    })
    taskId.value = res.taskId
    progress.value = {
      taskId: res.taskId, scenario: form.value.scenario,
      current: 0, total: res.total, success: 0, failed: 0, status: 'running', message: '',
    }
    startPolling()
  } catch (e: any) { alert(e.message) }
  finally { running.value = false }
}

function startPolling() {
  clearInterval(timer)
  timer = window.setInterval(async () => {
    try {
      const p = await perfApi.progress(taskId.value)
      progress.value = p
      if (p.status === 'done') {
        clearInterval(timer)
        const r = await perfApi.result(taskId.value)
        result.value = r
        await loadHistory()
      }
    } catch { clearInterval(timer) }
  }, 1000)
}

async function loadResult(id: string) {
  taskId.value = id
  try { result.value = await perfApi.result(id) } catch { /* ignore */ }
}
async function deleteHistory(id: string) {
  if (!confirm('确定删除这条记录？')) return
  try { await perfApi.delete(id); await loadHistory() } catch { /* ignore */ }
}

onMounted(async () => { await loadTables(); await loadHistory() })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.head-hint { font-size: 12px; color: var(--text-3); }
.perf-grid { display: grid; grid-template-columns: 380px 1fr; gap: 16px; }
.card { padding: 22px; }
.card-title { display: flex; align-items: center; gap: 9px; font-size: 15px; font-weight: 600; margin-bottom: 20px; }
.title-icon { color: var(--accent); font-size: 17px; }

/* 场景选择 */
.scenario-list { display: flex; flex-direction: column; gap: 8px; }
.scenario-btn {
  display: grid; grid-template-columns: 28px 1fr; grid-template-rows: auto auto;
  gap: 2px 10px; padding: 11px 13px; text-align: left;
  background: rgba(255,255,255,0.03); border: 1px solid var(--glass-stroke);
  border-radius: var(--r-sm); cursor: pointer; transition: var(--t);
}
.scenario-btn:hover { background: rgba(255,255,255,0.07); }
.scenario-btn.on { background: rgba(122,162,255,0.14); border-color: rgba(122,162,255,0.4); box-shadow: 0 0 18px rgba(122,162,255,0.12); }
.sc-icon { grid-row: 1 / 3; display: grid; place-items: center; font-size: 18px; color: var(--accent); }
.sc-name { font-size: 13px; font-weight: 500; color: var(--text-1); }
.sc-desc { font-size: 11px; color: var(--text-3); }

/* 量级预设 */
.preset-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.preset-btn {
  padding: 8px 4px; font-size: 12px; color: var(--text-2);
  background: rgba(255,255,255,0.04); border: 1px solid var(--glass-stroke);
  border-radius: 8px; cursor: pointer; transition: var(--t);
}
.preset-btn:hover { background: rgba(255,255,255,0.08); }
.preset-btn.on { color: #fff; background: rgba(122,162,255,0.2); border-color: rgba(122,162,255,0.45); }

.range { width: 100%; accent-color: var(--accent); }
.range-marks { display: flex; justify-content: space-between; font-size: 10px; color: var(--text-3); margin-top: 4px; }
.warning-box {
  display: flex; gap: 10px; padding: 12px 14px; margin-bottom: 16px;
  font-size: 12px; line-height: 1.6; color: var(--warning);
  background: rgba(255,204,122,0.08); border: 1px solid rgba(255,204,122,0.25);
  border-radius: var(--r-sm);
}
.warning-icon { font-size: 16px; flex-shrink: 0; }
.start-btn { width: 100%; height: 44px; font-size: 14px; }

/* 结果区 */
.empty-area { text-align: center; padding: 80px 20px; color: var(--text-3); }
.empty-icon { font-size: 48px; margin-bottom: 16px; opacity: 0.4; }
.empty-area p { margin: 4px 0; font-size: 14px; }
.empty-area .sub { font-size: 12px; }
.running-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.running-label { display: flex; align-items: center; gap: 10px; font-size: 14px; }
.progress-label { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 10px; }
.progress-stats { display: flex; gap: 20px; margin-top: 12px; font-size: 12px; }
.ok-text { color: var(--success); }
.err-text { color: var(--danger); }

.result-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.result-meta { font-size: 12px; color: var(--text-3); }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 22px; }
.metric {
  padding: 16px; text-align: center;
  background: rgba(255,255,255,0.03); border: 1px solid var(--glass-stroke);
  border-radius: var(--r-sm);
}
.metric.primary { background: linear-gradient(140deg, rgba(122,162,255,0.15), rgba(167,139,250,0.08)); border-color: rgba(122,162,255,0.3); }
.metric-value { font-size: 24px; font-weight: 600; color: var(--accent); }
.metric.primary .metric-value { font-size: 28px; }
.metric-value small { font-size: 12px; margin-left: 2px; color: var(--text-2); }
.metric-label { font-size: 11px; color: var(--text-3); margin-top: 6px; }

.chart-section { margin-bottom: 20px; }
.section-label { font-size: 11px; letter-spacing: 1px; color: var(--text-3); margin-bottom: 12px; text-transform: uppercase; }
.bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.bar-label { width: 36px; font-size: 12px; color: var(--text-2); }
.bar-track { flex: 1; height: 10px; background: rgba(0,0,0,0.3); border-radius: 8px; overflow: hidden; border: 1px solid var(--glass-stroke); }
.bar-fill { height: 100%; background: linear-gradient(90deg, var(--aurora-1), var(--aurora-2)); border-radius: 8px; box-shadow: 0 0 12px var(--glow); transition: width 0.5s; }
.bar-value { width: 70px; text-align: right; font-size: 12px; color: var(--text-2); }

.detail-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; padding: 14px; background: rgba(0,0,0,0.2); border-radius: var(--r-sm); }
.detail-grid > div { display: flex; flex-direction: column; gap: 4px; }
.detail-grid span { font-size: 11px; color: var(--text-3); }
.detail-grid b { font-size: 14px; }
.errors-box { margin-top: 16px; padding: 12px; background: rgba(255,128,149,0.06); border: 1px solid rgba(255,128,149,0.2); border-radius: var(--r-sm); }
.error-line { font-size: 11px; color: var(--danger); padding: 3px 0; word-break: break-all; }

.history-card { margin-top: 16px; }
@media (max-width: 1100px) { .perf-grid { grid-template-columns: 1fr; } .metric-grid, .detail-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
