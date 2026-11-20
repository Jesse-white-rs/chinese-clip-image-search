/** 定时备份 API（需 admin 权限）。 */
import request from './index'

export interface BackupTask {
  id: number
  name: string
  tableName: string
  cronExpr: string
  enabled: boolean
  includeMinio: boolean
  retentionDays: number
  lastRun: string | null
  lastStatus: string | null
  nextRun: string | null
  createdAt: string | null
}

export interface BackupHistory {
  id: number
  taskId: number
  tableName: string
  status: string
  message: string
  filePath: string
  sizeBytes: number
  startedAt: string | null
  finishedAt: string | null
}

export interface BackupFile {
  name: string
  sizeBytes: number
  createdAt: string
}

export const backupApi = {
  listTasks(): Promise<{ tasks: BackupTask[] }> {
    return request.get('/backups/tasks')
  },
  createTask(data: {
    name: string; table_name: string; cron_expr: string;
    enabled: boolean; include_minio: boolean; retention_days: number;
  }): Promise<{ id: number }> {
    return request.post('/backups/tasks', data)
  },
  updateTask(id: number, data: Partial<{
    name: string; table_name: string; cron_expr: string;
    enabled: boolean; include_minio: boolean; retention_days: number;
  }>): Promise<any> {
    return request.put(`/backups/tasks/${id}`, data)
  },
  deleteTask(id: number): Promise<any> {
    return request.delete(`/backups/tasks/${id}`)
  },
  runNow(id: number): Promise<any> {
    return request.post(`/backups/tasks/${id}/run`)
  },
  history(taskId?: number, limit = 50): Promise<{ history: BackupHistory[] }> {
    return request.get('/backups/history', { params: { ...(taskId ? { task_id: taskId } : {}), limit } })
  },
  files(): Promise<{ files: BackupFile[] }> {
    return request.get('/backups/files')
  },
  deleteFile(name: string): Promise<any> {
    return request.delete(`/backups/files/${encodeURIComponent(name)}`)
  },
  async download(name: string): Promise<void> {
    // 用 axios 携带 Authorization 头获取二进制，再触发浏览器下载
    const resp = await request.get(`/backups/files/${encodeURIComponent(name)}/download`, {
      responseType: 'blob',
    })
    const blob = resp as unknown as Blob
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.click()
    URL.revokeObjectURL(url)
  },
}
