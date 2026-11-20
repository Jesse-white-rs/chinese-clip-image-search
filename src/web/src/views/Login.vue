<template>
  <div class="login-scene">
    <!-- 环境光球 -->
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>

    <div class="login-shell">
      <!-- 品牌标识 -->
      <div class="brand-block">
        <div class="brand-glyph">
          <div class="glyph-core">◈</div>
          <div class="glyph-ring"></div>
        </div>
        <h1 class="brand-name">图搜空间</h1>
        <p class="brand-tagline">Visual Search · Spatial Intelligence</p>
      </div>

      <!-- 登录玻璃卡片 -->
      <div class="login-card glass-panel">
        <div class="card-header">
          <div class="header-line"></div>
          <span>欢迎回来</span>
          <div class="header-line"></div>
        </div>

        <form @submit.prevent="onLogin">
          <div class="form-item">
            <label class="label">用户名</label>
            <div class="input-wrap">
              <svg class="field-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>
              </svg>
              <input v-model="username" class="input field-input" autocomplete="username" placeholder="请输入用户名" />
            </div>
          </div>
          <div class="form-item">
            <label class="label">密码</label>
            <div class="input-wrap">
              <svg class="field-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>
              </svg>
              <input v-model="password" class="input field-input" type="password" autocomplete="current-password" placeholder="请输入密码" />
            </div>
          </div>

          <div class="remember-row">
            <label class="check"><input v-model="remember" type="checkbox" /> 保持登录状态</label>
            <span class="secure-hint">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="13" height="13">
                <rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>
              </svg>
              加密连接
            </span>
          </div>

          <transition name="fade">
            <div v-if="error" class="error-msg">{{ error }}</div>
          </transition>

          <button class="login-btn" :disabled="loading" type="submit">
            <span v-if="loading" class="spinner"></span>
            <template v-else>
              <span>进入空间</span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                <path d="M5 12h14M13 6l6 6-6 6"/>
              </svg>
            </template>
          </button>
        </form>

        <div class="card-footer">
          <span class="footer-dot"></span>
          Chinese-CLIP · 1024D 向量引擎
        </div>
      </div>

      <p class="bottom-note">安全认证 · JWT 加密访问 · 7 天有效</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const username = ref('')
const password = ref('')
const remember = ref(true)
const loading = ref(false)
const error = ref('')

async function onLogin() {
  if (!username.value || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await store.login(username.value, password.value)
    const redirect = (route.query.redirect as string) || '/dashboard'
    router.push(redirect)
  } catch (e: any) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-scene {
  position: relative;
  height: 100vh;
  display: grid;
  place-items: center;
  overflow: hidden;
}

/* 环境光球：模拟 visionOS 的空间光源 */
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.55;
  pointer-events: none;
  animation: orb-float 18s ease-in-out infinite alternate;
}
.orb-1 { width: 520px; height: 520px; top: -10%; left: 8%;
  background: radial-gradient(circle, rgba(122,162,255,0.55), transparent 70%); }
.orb-2 { width: 460px; height: 460px; bottom: -5%; right: 5%;
  background: radial-gradient(circle, rgba(167,139,250,0.48), transparent 70%);
  animation-delay: -6s; }
.orb-3 { width: 380px; height: 380px; top: 40%; left: 55%;
  background: radial-gradient(circle, rgba(94,234,212,0.28), transparent 70%);
  animation-delay: -12s; }
@keyframes orb-float {
  0%   { transform: translate(0, 0) scale(1); }
  100% { transform: translate(40px, -30px) scale(1.12); }
}

.login-shell {
  position: relative;
  z-index: 1;
  width: 420px;
  max-width: 92vw;
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* 品牌区 */
.brand-block { text-align: center; margin-bottom: 32px; }
.brand-glyph {
  width: 76px; height: 76px; margin: 0 auto 20px;
  position: relative; display: grid; place-items: center;
}
.glyph-core {
  width: 60px; height: 60px;
  display: grid; place-items: center;
  font-size: 30px; color: #fff;
  border-radius: 20px;
  background: linear-gradient(140deg, rgba(122,162,255,0.95), rgba(167,139,250,0.85) 55%, rgba(94,234,212,0.75));
  box-shadow: 0 12px 40px rgba(122,162,255,0.4), inset 0 1px 0 rgba(255,255,255,0.5);
  position: relative; z-index: 1;
}
.glyph-ring {
  position: absolute; inset: 0;
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 26px;
  animation: ring-pulse 3s ease-in-out infinite;
}
@keyframes ring-pulse {
  0%,100% { transform: scale(1); opacity: 0.5; }
  50% { transform: scale(1.12); opacity: 0.15; }
}
.brand-name {
  margin: 0 0 6px;
  font-size: 26px;
  font-weight: 600;
  letter-spacing: 3px;
  background: linear-gradient(120deg, #fff, #c7d4ff);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.brand-tagline {
  margin: 0; font-size: 10px; letter-spacing: 3px;
  color: var(--text-3); text-transform: uppercase;
}

/* 登录卡片 */
.login-card { width: 100%; padding: 32px 34px 24px; }
.card-header {
  display: flex; align-items: center; gap: 14px;
  font-size: 14px; color: var(--text-2); margin-bottom: 26px;
}
.header-line { flex: 1; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.14)); }
.header-line:last-child { background: linear-gradient(90deg, rgba(255,255,255,0.14), transparent); }

.input-wrap { position: relative; }
.field-icon {
  position: absolute; left: 14px; top: 50%; transform: translateY(-50%);
  width: 17px; height: 17px; color: var(--text-3); pointer-events: none;
}
.field-input { padding-left: 42px; }

.remember-row {
  display: flex; justify-content: space-between; align-items: center;
  margin: 4px 0 22px;
}
.secure-hint {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; color: var(--text-3);
}

/* 登录按钮：流光胶囊 */
.login-btn {
  width: 100%; height: 50px;
  display: flex; align-items: center; justify-content: center; gap: 10px;
  font-size: 15px; font-weight: 600; letter-spacing: 1px;
  color: #fff;
  background: linear-gradient(110deg, #7aa2ff, #a78bfa 55%, #8ab4ff);
  background-size: 200% 100%;
  border: 1px solid rgba(255,255,255,0.3);
  border-radius: var(--r-pill);
  cursor: pointer;
  box-shadow: 0 10px 32px rgba(122,162,255,0.35), inset 0 1px 0 rgba(255,255,255,0.4);
  transition: var(--t);
  animation: btn-shimmer 6s linear infinite;
}
.login-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 14px 44px rgba(122,162,255,0.5), inset 0 1px 0 rgba(255,255,255,0.5);
}
.login-btn:active:not(:disabled) { transform: translateY(0) scale(0.99); }
.login-btn:disabled { opacity: 0.7; cursor: wait; }
@keyframes btn-shimmer { 0% { background-position: 0% 50%; } 100% { background-position: 200% 50%; } }

.card-footer {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  margin-top: 24px; padding-top: 18px;
  border-top: 1px solid rgba(255,255,255,0.07);
  font-size: 11px; color: var(--text-3); letter-spacing: 0.5px;
}
.footer-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--success); box-shadow: 0 0 8px var(--success); }

.bottom-note { margin-top: 22px; font-size: 11px; color: var(--text-3); letter-spacing: 0.5px; }

.fade-enter-active, .fade-leave-active { transition: opacity 0.25s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
