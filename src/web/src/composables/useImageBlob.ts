/** 图片 blob 加载与缓存：通过 axios 带 token 获取，转成 objectURL 供 <img> 显示。 */
import { ref, onUnmounted } from 'vue'
import { searchApi } from '@/api/search'

const cache = new Map<string, string>()   // imgId -> objectURL

export function useImageBlob() {
  const urls = ref<Record<string, string>>({})
  const failed = ref<Record<string, boolean>>({})
  const active = ref(true)

  onUnmounted(() => { active.value = false })

  async function load(table: string, imgId: string) {
    const key = `${table}/${imgId}`
    if (cache.has(key)) {
      urls.value[imgId] = cache.get(key)!
      return
    }
    try {
      const blob = await searchApi.fetchImageBlob(table, imgId)
      // 后端未落 MinIO 时返回 JSON blob，识别后标记为无图
      if (blob.type.includes('application/json')) {
        failed.value[imgId] = true
        return
      }
      const url = URL.createObjectURL(blob)
      cache.set(key, url)
      if (active.value) urls.value[imgId] = url
    } catch {
      failed.value[imgId] = true
    }
  }

  function clear() {
    urls.value = {}
    failed.value = {}
  }

  return { urls, failed, load, clear }
}
