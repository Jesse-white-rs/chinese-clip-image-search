/** 图搜业务 API：图库、图片、上传、检索。 */
import request from './index'

export interface SearchResult {
  imgId: string
  similarity: string
  customsParams: string
  commodityId: string
}

export const searchApi = {
  health(): Promise<any> {
    return request.get('/health')
  },
  listTables(): Promise<{ tables: { name: string; count: number }[] }> {
    return request.get('/tables')
  },
  createTable(tableName: string): Promise<any> {
    return request.post('/tables', { table_name: tableName })
  },
  deleteTable(tableName: string, cascade = false): Promise<any> {
    return request.delete(`/tables/${tableName}`, { params: { cascade } })
  },
  stats(tableName: string): Promise<{ count: number }> {
    return request.get(`/tables/${tableName}/stats`)
  },
  listImages(table: string, page = 1, size = 12): Promise<any> {
    return request.get(`/tables/${table}/images`, { params: { page, size } })
  },
  deleteImage(table: string, imgId: string): Promise<any> {
    return request.delete(`/tables/${table}/images/${imgId}`)
  },
  clearImages(table: string, cascade = true): Promise<any> {
    return request.delete(`/tables/${table}/images`, { params: { cascade } })
  },
  imageUrl(table: string, imgId: string): string {
    const token = localStorage.getItem('token') || ''
    return `/api/v1/tables/${table}/images/${imgId}/content?token=${encodeURIComponent(token)}`
  },
  fetchImageBlob(table: string, imgId: string): Promise<Blob> {
    return request.get(`/tables/${table}/images/${imgId}/content`, { responseType: 'blob' }) as any
  },
  uploadSingle(table: string, formData: FormData): Promise<{ imgId: string }> {
    return request.post(`/tables/${table}/images`, formData)
  },
  uploadManualId(table: string, formData: FormData): Promise<{ imgId: string }> {
    return request.post(`/tables/${table}/images/manual-id`, formData)
  },
  uploadBatch(table: string, payload: any): Promise<{ taskId: string; total: number }> {
    return request.post(`/tables/${table}/images/batch`, payload)
  },
  taskProgress(taskId: string): Promise<any> {
    return request.get(`/tasks/${taskId}/progress`)
  },
  taskResult(taskId: string, page = 1, size = 100): Promise<{
    total: number; page: number; size: number
    items: { index: number; imgId: string; commodityId: string; customsParam: string; rawUrl: string }[]
  }> {
    return request.get(`/tasks/${taskId}/result`, { params: { page, size } })
  },
  importDirectory(table: string, dirPath: string, saveToMinio = true): Promise<any> {
    return request.post(`/tables/${table}/import/directory`, {
      dir_path: dirPath, save_to_minio: saveToMinio,
    })
  },
  importProgress(table: string): Promise<any> {
    return request.get(`/tables/${table}/import/progress`)
  },
  searchByImage(table: string, formData: FormData): Promise<{ results: SearchResult[] }> {
    return request.post(`/tables/${table}/search/image`, formData)
  },
  searchByText(table: string, queryText: string, topk = 10): Promise<{ results: SearchResult[] }> {
    const form = new FormData()
    form.append('query_text', queryText)
    form.append('topk', String(topk))
    return request.post(`/tables/${table}/search/text`, form)
  },
}
