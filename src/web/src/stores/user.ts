/** 用户状态：登录信息、token、角色，持久化到 localStorage。 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, type UserInfo } from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const saved = localStorage.getItem('user')
  const user = ref<UserInfo | null>(saved ? JSON.parse(saved) : null)
  const token = ref<string | null>(localStorage.getItem('token'))

  const isLoggedIn = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function login(username: string, password: string) {
    const result = await authApi.login(username, password)
    token.value = result.accessToken
    user.value = result.user
    localStorage.setItem('token', result.accessToken)
    localStorage.setItem('user', JSON.stringify(result.user))
  }

  async function logout() {
    try { await authApi.logout() } catch { /* 忽略登出接口错误 */ }
    token.value = null
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  return { user, token, isLoggedIn, isAdmin, login, logout }
})
