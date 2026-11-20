<template>
  <div>
    <div class="page-head">
      <h2>图片管理</h2>
      <div class="head-tools">
        <select v-model="table" class="select" @change="reload">
          <option value="">请选择图库</option>
          <option v-for="t in tables" :key="t.name" :value="t.name">{{ t.name }}</option>
        </select>
        <button class="btn btn-sm" @click="reload">刷新</button>
        <button v-if="isAdmin && table" class="btn btn-sm btn-danger" @click="openClear">一键清空</button>
      </div>
    </div>

    <div v-if="!table" class="glass-panel empty">请先在顶部或此处选择一个图库</div>
    <template v-else>
      <div class="glass-panel card">
        <div v-if="loading" class="empty"><span class="spinner"></span> 加载中...</div>
        <div v-else-if="images.length === 0" class="empty">该图库暂无图片</div>
        <template v-else>
          <div class="img-grid">
            <div v-for="img in images" :key="img.imgId" class="img-card">
              <div class="thumb" @click="preview(img)">
                <img v-if="urls[img.imgId]" :src="urls[img.imgId]" :alt="img.imgId" />
                <div v-else-if="failed[img.imgId]" class="thumb-ph">无原图</div>
                <div v-else class="thumb-ph"><span class="spinner"></span></div>
              </div>
              <div class="img-meta">
                <div class="img-id" :title="img.imgId">ID: {{ img.imgId }}</div>
                <div class="img-sub">{{ img.commodityId || '无商品ID' }}</div>
                <div class="img-actions">
                  <span v-if="img.hasMinioImage" class="badge badge-ok">已存图</span>
                  <span v-else class="badge badge-off">仅向量</span>
                  <button class="btn btn-sm btn-danger" @click="onDelete(img)">删除</button>
                </div>
              </div>
            </div>
          </div>
          <div class="pager">
            <button class="btn btn-sm" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
            <span class="page-info">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 张</span>
            <button class="btn btn-sm" :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
          </div>
        </template>
      </div>
    </template>

    <!-- 一键清空确认弹窗 -->
    <div v-if="showClear" class="modal-mask" @click.self="showClear = false">
      <div class="glass-panel clear-box">
        <h3>清空图库图片</h3>
        <p class="warn-text">此操作将删除图库「<b>{{ table }}</b>」的全部图片数据，且不可恢复。图库本身（结构与索引）会保留。</p>
        <div class="form-item">
          <label class="check"><input v-model="clearCascade" type="checkbox" /> 同时删除 MinIO 中的原图</label>
        </div>
        <div class="form-item">
          <label class="label">请输入图库名 <code>{{ table }}</code> 以确认</label>
          <input v-model="clearConfirm" class="input" :placeholder="table" />
        </div>
        <div class="modal-actions">
          <button class="btn" @click="showClear = false">取消</button>
          <button class="btn btn-danger" :disabled="clearConfirm !== table || clearing" @click="onClear">
            {{ clearing ? '清空中...' : '确认清空' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 大图预览 -->
    <div v-if="previewImg" class="modal-mask" @click.self="previewImg = null">
      <div class="glass-panel preview-box">
        <div class="preview-head">
          <span>图片预览 · {{ previewImg.imgId }}</span>
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
import { ref, computed, onMounted, watch } from 'vue'
import { searchApi } from '@/api/search'
import { useUserStore } from '@/stores/user'
import { useImageBlob } from '@/composables/useImageBlob'

const userStore = useUserStore()
const isAdmin = computed(() => userStore.isAdmin)

interface ImageItem { imgId: string; commodityId: string; customsParams: string; rawUrl: string; hasMinioImage: boolean }
const { urls, failed, load, clear } = useImageBlob()

const tables = ref<{ name: string; count: number }[]>([])
const table = ref(localStorage.getItem('currentTable') || '')
const images = ref<ImageItem[]>([])
const page = ref(1)
const size = 12
const total = ref(0)
const totalPages = ref(0)
const loading = ref(false)
const previewImg = ref<ImageItem | null>(null)
const showClear = ref(false)
const clearConfirm = ref('')
const clearCascade = ref(true)
const clearing = ref(false)

async function loadTables() {
  try { tables.value = (await searchApi.listTables()).tables || [] } catch { /* ignore */ }
}

async function loadImages() {
  if (!table.value) return
  loading.value = true
  clear()
  try {
    const res = await searchApi.listImages(table.value, page.value, size)
    images.value = res.data || []
    total.value = res.total || 0
    totalPages.value = res.totalPages || 0
    // 并发加载缩略图（简单限流：逐批触发）
    for (const img of images.value) {
      if (img.hasMinioImage) load(table.value, img.imgId)
    }
  } catch { /* ignore */ }
  finally { loading.value = false }
}

function reload() {
  page.value = 1
  localStorage.setItem('currentTable', table.value)
  loadImages()
}
function go(p: number) { page.value = p; loadImages() }
function preview(img: ImageItem) { if (img.hasMinioImage) previewImg.value = img }

async function onDelete(img: ImageItem) {
  if (!confirm(`确定删除图片 ${img.imgId}？`)) return
  try { await searchApi.deleteImage(table.value, img.imgId); await loadImages() } catch { /* ignore */ }
}

function openClear() {
  clearConfirm.value = ''
  clearCascade.value = true
  showClear.value = true
}
async function onClear() {
  if (clearConfirm.value !== table.value) return
  clearing.value = true
  try {
    await searchApi.clearImages(table.value, clearCascade.value)
    showClear.value = false
    page.value = 1
    await loadImages()
    await loadTables()
  } catch { /* ignore */ }
  finally { clearing.value = false }
}

onMounted(async () => { await loadTables(); await loadImages() })
watch(table, () => { localStorage.setItem('currentTable', table.value) })
</script>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-head h2 { margin: 0; font-size: 20px; }
.head-tools { display: flex; gap: 10px; align-items: center; }
.head-tools .select { width: 180px; }
.card { padding: 18px; }
.img-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; }
.img-card { border: 1px solid var(--glass-border); border-radius: var(--radius-md); overflow: hidden; background: rgba(10,13,24,0.3); }
.thumb { height: 140px; display: grid; place-items: center; background: rgba(10,13,24,0.5); cursor: pointer; overflow: hidden; }
.thumb img { width: 100%; height: 100%; object-fit: cover; transition: transform var(--transition); }
.thumb:hover img { transform: scale(1.05); }
.thumb-ph { color: var(--text-muted); font-size: 12px; display: grid; place-items: center; gap: 8px; }
.img-meta { padding: 10px 12px; }
.img-id { font-size: 12px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.img-sub { font-size: 11px; color: var(--text-muted); margin: 3px 0 8px; }
.img-actions { display: flex; align-items: center; justify-content: space-between; }
.pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 20px; }
.page-info { font-size: 13px; color: var(--text-secondary); }
.modal-mask { position: fixed; inset: 0; background: rgba(3,7,15,0.75); display: grid; place-items: center; z-index: 50; backdrop-filter: blur(4px); }
.preview-box { width: 80vw; max-width: 900px; padding: 16px; }
.preview-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-size: 14px; }
.preview-body { display: grid; place-items: center; min-height: 300px; }
.preview-body img { max-width: 100%; max-height: 70vh; border-radius: 8px; }
.clear-box { width: 440px; max-width: 92vw; padding: 24px; }
.clear-box h3 { margin: 0 0 14px; font-size: 17px; }
.warn-text { font-size: 13px; line-height: 1.7; color: var(--warning); margin: 0 0 20px; }
.clear-box code { color: var(--accent); background: rgba(122,162,255,0.1); padding: 1px 6px; border-radius: 4px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
</style>
