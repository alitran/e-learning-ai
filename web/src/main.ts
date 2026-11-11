import { createApp } from 'vue';
import { createRouter, createWebHistory } from 'vue-router';
import App from './App.vue';
import LoginView from './views/LoginView.vue';
import ResetPasswordView from './views/ResetPasswordView.vue';
import LearnView from './views/LearnView.vue';
import ConfigView from './views/ConfigView.vue';
import HistoryView from './views/HistoryView.vue';
import { isAuthenticated } from './lib/auth';
import './style.css';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { guest: true } },
    { path: '/reset-password', name: 'reset-password', component: ResetPasswordView, meta: { guest: true } },
    { path: '/', redirect: '/learn' },
    { path: '/learn/:lessonId?', name: 'learn', component: LearnView, meta: { title: 'Không gian học' } },
    { path: '/config', name: 'config', component: ConfigView, meta: { title: 'Cấu hình học tập' } },
    { path: '/history', name: 'history', component: HistoryView, meta: { title: 'Lịch sử học tập' } },
    { path: '/:pathMatch(.*)*', redirect: '/learn' }
  ]
});

router.beforeEach(to => {
  if (to.name === 'login' && isAuthenticated()) return { name: 'learn' };
  if (!to.meta.guest && !isAuthenticated()) return { name: 'login' };
});

createApp(App).use(router).mount('#app');
