<template>
  <div>
    <div class="page-head">
      <h2>图片检索</h2>
      <select v-model="table" class="select" style="width: 200px">
        <option value="">请选择图库</option>
        <option v-for="t in tables" :key="t.name" :value="t.name">{{ t.name }}</option>
      </select>
    </div>

    <div v-if="!table" class="glass-panel empty">请先选择一个图库</div>
    <template v-else>
      <div class="glass-panel card search-panel">
        <div class="tabs">
          <button class="tab" :class="{ active: mode === 'image' }" @click="mode = 'image'">以图搜图</button>
          <button class="tab" :class="{ active: mode === 'text' }" @click="mode = 'text'">中文文本搜图</button>
        </div>

        <div v-if="mode === 'image'" class="search-form">
          <div class="seg">
            <button class="seg-btn" :class="{ on: imgSource === 'file' }" @click="imgSource = 'file'">本地文件</button>
            <button class="seg-btn" :class="{ on: imgSource === 'url' }" @click="imgSource = 'url'">图片链接</button>
          </div>
          <input v-if="imgSource === 'file'" type="file" class="input" accept="image/*" @change="onSearchFile" />
          <input v-else v-model="searchUrl" class="input" placeholder="https://..." />
        </div>
        <div v-else class="search-form">
          <input v-model="queryText" class="input" placeholder="输入中文描述，例如：红色的连衣裙" @keyup.enter="doSearch" />
        </div>

        <div class="search-opts">
          <div class="topk">
            <label class="label">返回数量 (topk)：{{ topk }}</label>
            <input v-model.number="topk" type="range" min="1" max="50" class="range" />
          </div>
          <button class="btn btn-primary" :disabled="searching" @click="doSearch">
            <span v-if="searching" class="spinner"></span><span v-else>开始检索</span>
          </button>
        </div>
      </div>

      <!-- 结果 -->
      <div class="section-title" v-if="searched">检索结果（{{ results.length }}）</div>
      <div v-if="searched" class="glass-panel card">
        <div v-if="results.length === 0" class="empty">没有找到相似图片</div>
        <div v-else class="img-grid stagger">
          <div v-for="(r, i) in results" :key="r.imgId + i" class="img-card" @click="preview(r)">
            <div class="thumb">
              <img v-if="urls[r.imgId]" :src="urls[r.imgId]" :alt="r.imgId" />
              <div v-else-if="failed[r.imgId]" class="thumb-ph">无原图</div>
              <div v-else class="thumb-ph"><span class="spinner"></span></div>
              <div class="rank">#{{ i + 1 }}</div>
            </div>
            <div class="img-meta">
              <div class="sim-row">
                <span class="sim-value">{{ r.similarity }}</span>
                <span class="sim-label">相似度</span>
              </div>
              <div class="img-sub">{{ r.commodityId || '无商品ID' }}</div>
              <div v-if="r.customsParams" class="img-sub">{{ r.customsParams }}</div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 预览 -->
    <div v-if="previewImg" class="modal-mask" @click.self="previewImg = null">
      <div class="glass-panel preview-box">
        <div class="preview-head">
          <span>图片预览 · {{ previewImg.imgId }} · {{ previewImg.similarity }}</span>
          <button class="btn btn-sm" @click="previewImg = null">关闭</button>
        </div>
        <div class="preview-body">
          <img v-if="urls[previewImg.imgId]" :src="urls[previewImg.imgId]" />
          <div v-else class="empty">该图片未存储原图</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { searchApi, type SearchResult } from '@/api/search'
import { useImageBlob } from '@/composables/useImageBlob'

const { urls, failed, load, clear } = useImageBlob()
const tables = ref<{ name: string; count: number }[]>([])
const table = ref(localStorage.getItem('currentTable') || '')
const mode = ref<'image' | 'text'>('text')
const imgSource = ref<'file' | 'url'>('file')
const searchFile = ref<File | null>(null)
const searchUrl = ref('')
const queryText = ref('')
const topk = ref(10)
const searching = ref(false)
const searched = ref(false)
const results = ref<SearchResult[]>([])
const previewImg = ref<SearchResult | null>(null)

async function loadTables() {
  try { tables.value = (await searchApi.listTables()).tables || [] } catch { /* ignore */ }
}
function onSearchFile(e: Event) { searchFile.value = (e.target as HTMLInputElement).files?.[0] || null }

async function doSearch() {
  if (mode.value === 'image' && imgSource.value === 'file' && !searchFile.value) return
  if (mode.value === 'image' && imgSource.value === 'url' && !searchUrl.value) return
  if (mode.value === 'text' && !queryText.value.trim()) return
  searching.value = true
  searched.value = false
  clear()
  try {
    let res: { results: SearchResult[] }
    if (mode.value === 'image') {
      const form = new FormData()
      if (imgSource.value === 'file') form.append('image', searchFile.value!)
      else form.append('image_url', searchUrl.value)
      form.append('topk', String(topk.value))
      res = await searchApi.searchByImage(table.value, form)
    } else {
      res = await searchApi.searchByText(table.value, queryText.value.trim(), topk.value)
    }
    results.value = res.results || []
    searched.value = true
    results.value.forEach(r => load(table.value, r.imgId))
  } catch { /* ignore */ }
  finally { searching.value = false }
}

function preview(r: SearchResult) { previewImg.value = r }

onMounted(loadTables)
</script>

<style scoped>
/* 公共类（page-head / section-title / card / tabs / tab / seg / seg-btn /
   range / img-grid / img-card / thumb / img-meta / img-sub）现由 glass.css 统一提供 */

.search-panel { padding: 22px; }
.search-form { margin-bottom: 16px; }
.search-opts { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; }
.topk { flex: 1; max-width: 320px; }
.rank {
  position: absolute; top: 9px; left: 9px; z-index: 1;
  padding: 3px 9px; font-size: 11px; font-weight: 600; color: #fff;
  background: linear-gradient(120deg, var(--aurora-1), var(--aurora-3));
  border-radius: var(--r-pill); box-shadow: 0 3px 12px rgba(0,0,0,0.4);
}
.sim-row { display: flex; align-items: baseline; gap: 7px; }
.sim-value {
  font-size: 19px; font-weight: 700;
  background: linear-gradient(120deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.sim-label { font-size: 11px; color: var(--text-3); }
.modal-mask { position: fixed; inset: 0; background: rgba(3,7,15,0.75); display: grid; place-items: center; z-index: 50; backdrop-filter: blur(4px); }
.preview-box { width: 80vw; max-width: 900px; padding: 16px; }
.preview-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-size: 14px; }
.preview-body { display: grid; place-items: center; min-height: 300px; }
.preview-body img { max-width: 100%; max-height: 70vh; border-radius: 8px; }
</style>
