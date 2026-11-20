/** 性能压测 API（需 admin 权限）。 */
import request from './index'

export interface PerfResult {
  taskId: string
  scenario: string
  tableName: string
  queryText?: string
  total: number
  concurrency: number
  duration: number
  qps: number
  avgMs: number
  p50Ms: number
  p90Ms: number
  p95Ms: number
  p99Ms: number
  success: number
  failed: number
  batchSize?: number
  images?: number
  imagesPerSec?: number
  avgMsPerImage?: number
  errors?: string[]
  status: string
  createdAt?: string
  finishedAt?: string
}

export interface PerfProgress {
  taskId: string
  scenario: string
  current: number
  total: number
  success: number
  failed: number
  status: string
  message: string
}

export const perfApi = {
  start(data: {
    scenario: string; table_name: string; total: number; concurrency: number
    query_text?: string; batch_size?: number
  }): Promise<{ taskId: string; total: number }> {
    return request.post('/perf/tasks', data)
  },
  progress(taskId: string): Promise<PerfProgress> {
    return request.get(`/perf/tasks/${taskId}/progress`)
  },
  result(taskId: string): Promise<PerfResult> {
    return request.get(`/perf/tasks/${taskId}/result`)
  },
  history(limit = 50): Promise<{ results: PerfResult[] }> {
    return request.get('/perf/results', { params: { limit } })
  },
  delete(taskId: string): Promise<any> {
    return request.delete(`/perf/results/${taskId}`)
  },
}
