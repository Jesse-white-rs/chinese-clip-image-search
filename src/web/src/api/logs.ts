/** 日志查询 API（需 admin 权限）。 */
import request from './index'

export interface LogFile {
  name: string
  size: number
  modified: number
}

export const logsApi = {
  list(): Promise<{ files: LogFile[] }> {
    return request.get('/logs')
  },
  read(name: string, lines = 200, level?: string): Promise<{ name: string; lines: string[] }> {
    return request.get(`/logs/${encodeURIComponent(name)}`, {
      params: { lines, ...(level ? { level } : {}) },
    })
  },
}
