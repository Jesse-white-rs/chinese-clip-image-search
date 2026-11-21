import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import ToastHost from './components/ToastHost.vue'
import AnimatedNumber from './components/AnimatedNumber.vue'
import './styles/glass.css'

createApp(App).use(createPinia()).use(router)
  .component('ToastHost', ToastHost)
  .component('AnimatedNumber', AnimatedNumber)
  .mount('#app')
