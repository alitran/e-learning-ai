<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { authUser, clearSession } from './lib/auth';

const route = useRoute();
const router = useRouter();
const guestPage = computed(() => Boolean(route.meta.guest));
const user = authUser;
const links = [
  { name: 'learn', label: 'Học cùng AI', icon: '✦', hint: 'Tạo bài học mới' },
  { name: 'history', label: 'Lịch sử học', icon: '◷', hint: 'Ôn lại bài đã lưu' },
  { name: 'config', label: 'Cấu hình', icon: '⚙', hint: 'Cá nhân hóa lộ trình' }
];

function logout() {
  clearSession();
  router.replace('/login');
}
</script>

<template>
  <RouterView v-if="guestPage" />
  <div v-else class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/learn">
        <span class="brand-mark">e<span>✳</span></span>
        <span><strong>học cùng AI</strong><small>HỌC THEO CÁCH CỦA BẠN</small></span>
      </RouterLink>
      <div class="side-label">KHÔNG GIAN HỌC TẬP</div>
      <nav class="side-nav">
        <RouterLink v-for="link in links" :key="link.name" :to="{ name: link.name }" class="nav-link">
          <span class="nav-icon">{{ link.icon }}</span>
          <span class="nav-copy"><strong>{{ link.label }}</strong><small>{{ link.hint }}</small></span>
          <span v-if="route.name === link.name" class="nav-active-dot"></span>
        </RouterLink>
      </nav>
      <div class="sidebar-note">
        <div class="note-icon">✧</div>
        <strong>Mỗi ngày một chút</strong>
        <p>Tiến bộ bắt đầu từ sự tò mò. Hãy chọn một chủ đề và bắt đầu nhé.</p>
        <div class="note-sparkles">✳　✦　✳</div>
      </div>
      <div class="sidebar-profile">
        <div class="avatar">{{ user?.display_name?.slice(0, 1).toUpperCase() || 'H' }}</div>
        <div class="profile-copy"><strong>{{ user?.display_name || 'Học viên' }}</strong><small>{{ user?.email }}</small></div>
        <button class="icon-button logout-button" title="Đăng xuất" aria-label="Đăng xuất" @click="logout">↗</button>
      </div>
    </aside>
    <main class="main-area">
      <header class="topbar">
        <div class="crumb"><span>Không gian học tập</span><i>/</i><strong>{{ route.meta.title }}</strong></div>
        <div class="topbar-right"><span class="status-pill"><span></span> Học tập chủ động</span><div class="top-avatar">{{ user?.display_name?.slice(0, 1).toUpperCase() || 'H' }}</div></div>
      </header>
      <RouterView />
    </main>
  </div>
</template>
