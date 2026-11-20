/**
 * axios 请求封装：统一 baseURL、自动携带 JWT、401 跳转登录、统一解包响应。
 */
import axios, { type InternalAxiosRequestConfig, type AxiosResponse } from 'axios'
import router from '@/router'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

request.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (response: AxiosResponse) => {
    const data = response.data
    // 二进制响应（图片）直接返回
    if (response.config.responseType === 'blob') {
      return data
    }
    if (data && typeof data === 'object' && 'status' in data) {
      if (!data.status) {
        return Promise.reject(new Error(data.message || '请求失败'))
      }
      return data.data
    }
    return data
  },
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      router.push('/login')
    }
    const msg = error.response?.data?.detail || error.message || '网络错误'
    return Promise.reject(new Error(typeof msg === 'string' ? msg : '请求失败'))
  },
)

export default request
