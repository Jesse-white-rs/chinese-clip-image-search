/** 路由配置：登录页公开，其余页面需登录；admin 专属页面做角色守卫。 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'Login', component: () => import('@/views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/layout/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '系统概览' } },
      { path: 'tables', name: 'Tables', component: () => import('@/views/Tables.vue'), meta: { title: '图库管理', admin: true } },
      { path: 'images', name: 'Images', component: () => import('@/views/Images.vue'), meta: { title: '图片管理' } },
      { path: 'upload', name: 'Upload', component: () => import('@/views/Upload.vue'), meta: { title: '上传入库' } },
      { path: 'search', name: 'Search', component: () => import('@/views/Search.vue'), meta: { title: '图片检索' } },
      { path: 'users', name: 'Users', component: () => import('@/views/Users.vue'), meta: { title: '用户管理', admin: true } },
      { path: 'logs', name: 'Logs', component: () => import('@/views/Logs.vue'), meta: { title: '系统日志', admin: true } },
      { path: 'backups', name: 'Backups', component: () => import('@/views/Backups.vue'), meta: { title: '定时备份', admin: true } },
      { path: 'api-docs', name: 'ApiDocs', component: () => import('@/views/ApiDocs.vue'), meta: { title: '接口文档' } },
      { path: 'perf', name: 'PerfTest', component: () => import('@/views/PerfTest.vue'), meta: { title: '性能检测', admin: true } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const store = useUserStore()
  if (!to.meta.public && !store.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin && !store.isAdmin) {
    return { path: '/dashboard' }
  }
  if (to.path === '/login' && store.isLoggedIn) {
    return { path: '/dashboard' }
  }
  return true
})

export default router
