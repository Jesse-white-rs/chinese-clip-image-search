<template>
  <div>
    <div class="page-head">
      <h2>系统概览</h2>
      <button class="btn btn-sm" @click="loadAll" :disabled="loading">刷新</button>
    </div>

    <div v-if="loading" class="glass-panel empty"><span class="spinner"></span> 加载中...</div>

    <template v-else>
      <!-- 服务健康状态 -->
      <div class="section-title">服务健康</div>
      <div class="grid cols-4 stagger">
        <div class="glass-panel card card-hover health-card" :class="health?.model?.ready ? 'ok' : 'bad'">
          <div class="card-head"><span class="status-dot" :class="{ off: !health?.model?.ready }"></span> 模型</div>
          <div class="card-value">{{ health?.model?.ready ? '正常' : '异常' }}</div>
          <div class="card-sub">{{ health?.model?.model }} · {{ health?.model?.device }} · {{ health?.model?.dim }}维</div>
        </div>
        <div class="glass-panel card card-hover health-card" :class="health?.milvus ? 'ok' : 'bad'">
          <div class="card-head"><span class="status-dot" :class="{ off: !health?.milvus }"></span> Milvus</div>
          <div class="card-value">{{ health?.milvus ? '正常' : '异常' }}</div>
          <div class="card-sub">向量数据库</div>
        </div>
        <div class="glass-panel card card-hover health-card" :class="health?.mysql ? 'ok' : 'bad'">
          <div class="card-head"><span class="status-dot" :class="{ off: !health?.mysql }"></span> MySQL</div>
          <div class="card-value">{{ health?.mysql ? '正常' : '异常' }}</div>
          <div class="card-sub">映射数据库</div>
        </div>
        <div class="glass-panel card card-hover health-card" :class="health?.minio ? 'ok' : 'bad'">
          <div class="card-head"><span class="status-dot" :class="{ off: !health?.minio }"></span> MinIO</div>
          <div class="card-value">{{ health?.minio ? '正常' : '异常' }}</div>
          <div class="card-sub">对象存储</div>
        </div>
      </div>

      <!-- 统计 -->
      <div class="section-title">数据概览</div>
      <div class="grid cols-3 stagger">
        <div class="glass-panel card stat-card">
          <div class="stat-icon">▤</div>
          <div class="stat-value"><AnimatedNumber :value="tables.length" /></div>
          <div class="stat-label">图库总数</div>
        </div>
        <div class="glass-panel card stat-card">
          <div class="stat-icon">▦</div>
          <div class="stat-value"><AnimatedNumber :value="totalImages" format="comma" /></div>
          <div class="stat-label">图片总数</div>
        </div>
        <div class="glass-panel card stat-card">
          <div class="stat-icon">◈</div>
          <div class="stat-value"><AnimatedNumber :value="1024" /></div>
          <div class="stat-label">特征维度</div>
        </div>
      </div>

      <!-- 图库分布 -->
      <div class="section-title">图库分布</div>
      <div class="glass-panel card">
        <div v-if="tables.length === 0" class="empty">暂无图库，请到「图库管理」创建</div>
        <table v-else class="table">
          <thead><tr><th>图库名称</th><th>图片数量</th><th>占比</th></tr></thead>
          <tbody>
            <tr v-for="t in tables" :key="t.name">
              <td>{{ t.name }}</td>
              <td>{{ t.count.toLocaleString() }}</td>
              <td>
                <div class="mini-bar"><div class="mini-fill" :style="{ width: pct(t.count) + '%' }"></div></div>
                <span class="pct-text">{{ pct(t.count) }}%</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { searchApi } from '@/api/search'

const loading = ref(true)
const health = ref<any>(null)
const tables = ref<{ name: string; count: number }[]>([])
const totalImages = computed(() => tables.value.reduce((s, t) => s + t.count, 0))

function pct(count: number) {
  if (!totalImages.value) return 0
  return Math.round(count / totalImages.value * 100)
}

async function loadAll() {
  loading.value = true
  try {
    const [h, t] = await Promise.all([searchApi.health(), searchApi.listTables()])
    health.value = h
    tables.value = t.tables || []
  } catch { /* 概览错误静默，健康状态会显示异常 */ }
  finally { loading.value = false }
}

onMounted(loadAll)
</script>

<style scoped>
.grid { display: grid; gap: 14px; }
.cols-4 { grid-template-columns: repeat(4, 1fr); }
.cols-3 { grid-template-columns: repeat(3, 1fr); }

/* 健康卡片：左侧状态色条 + 状态色数值 */
.health-card { overflow: hidden; }
.health-card::after {
  content: ''; position: absolute; left: 0; top: 18%; bottom: 18%; width: 3px;
  border-radius: 0 3px 3px 0; transition: var(--t);
}
.health-card.ok::after { background: linear-gradient(180deg, var(--success), rgba(94,230,168,0.3)); box-shadow: 0 0 12px rgba(94,230,168,0.5); }
.health-card.bad::after { background: linear-gradient(180deg, var(--danger), rgba(255,128,149,0.3)); box-shadow: 0 0 12px rgba(255,128,149,0.5); }
.health-card .card-head { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); }
.health-card.ok .card-value { color: var(--success); }
.health-card.bad .card-value { color: var(--danger); }
.card-value { font-size: 24px; font-weight: 650; margin: 12px 0 4px; }
.card-sub { font-size: 11px; color: var(--text-3); }

.stat-card { display: flex; flex-direction: column; align-items: flex-start; }
.stat-icon {
  width: 42px; height: 42px; display: grid; place-items: center;
  font-size: 21px; color: var(--accent);
  background: linear-gradient(140deg, rgba(90,158,140,0.16), rgba(127,186,168,0.08));
  border: 1px solid rgba(95,168,147,0.28);
  border-radius: 13px; margin-bottom: 14px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.12);
}
.stat-value {
  font-size: 32px; font-weight: 700; line-height: 1.1;
  background: linear-gradient(120deg, #fff, #cfe8de);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.stat-label { font-size: 12px; color: var(--text-3); margin-top: 6px; letter-spacing: 0.3px; }
.mini-bar { display: inline-block; width: 130px; height: 6px; background: rgba(10,13,24,0.6); border-radius: 6px; overflow: hidden; vertical-align: middle; border: 1px solid var(--glass-stroke); }
.mini-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); box-shadow: 0 0 10px var(--glow); }
.pct-text { font-size: 12px; color: var(--text-2); margin-left: 9px; font-variant-numeric: tabular-nums; }
@media (max-width: 1000px) { .cols-4, .cols-3 { grid-template-columns: repeat(2, 1fr); } }
</style>
