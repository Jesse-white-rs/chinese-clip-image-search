/** 认证与用户管理相关 API。 */
import request from './index'

export interface UserInfo {
  id: number
  username: string
  role: 'admin' | 'user'
}

export interface LoginResult {
  accessToken: string
  tokenType: string
  user: UserInfo
}

export const authApi = {
  login(username: string, password: string): Promise<LoginResult> {
    return request.post('/auth/login', { username, password })
  },
  logout(): Promise<any> {
    return request.post('/auth/logout')
  },
  me(): Promise<{ user: UserInfo }> {
    return request.get('/auth/me')
  },
  listUsers(page = 1, size = 10): Promise<any> {
    return request.get('/users', { params: { page, size } })
  },
  createUser(data: { username: string; password: string; role: string }): Promise<any> {
    return request.post('/users', data)
  },
  updateUser(id: number, data: { role?: string; isActive?: boolean }): Promise<any> {
    return request.put(`/users/${id}`, data)
  },
  resetPassword(id: number, password: string): Promise<any> {
    return request.put(`/users/${id}/password`, { password })
  },
  deleteUser(id: number): Promise<any> {
    return request.delete(`/users/${id}`)
  },
}
