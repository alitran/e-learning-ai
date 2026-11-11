<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../lib/api';
import { saveSession } from '../lib/auth';
import type { User } from '../lib/types';

const router = useRouter();
const mode = ref<'login' | 'register' | 'forgot'>('login');
const registering = computed(() => mode.value === 'register');
const busy = ref(false);
const error = ref('');
const success = ref('');
const name = ref('');
const email = ref('');
const password = ref('');

async function submit() {
  error.value = '';
  success.value = '';
  busy.value = true;
  try {
    const result = await api.post<{ access_token: string; user: User }>(
      registering.value ? '/auth/register' : '/auth/login',
      registering.value
        ? { email: email.value, password: password.value, display_name: name.value }
        : { email: email.value, password: password.value }
    );
    saveSession(result.access_token, result.user);
    router.replace('/learn');
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không thể đăng nhập lúc này.';
  } finally {
    busy.value = false;
  }
}

async function requestPasswordReset() {
  error.value = '';
  success.value = '';
  busy.value = true;
  try {
    const result = await api.post<{ message: string }>('/auth/password-reset-requests', {
      email: email.value
    });
    success.value = result.message;
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Chưa gửi được yêu cầu đặt lại mật khẩu.';
  } finally {
    busy.value = false;
  }
}

function changeMode(nextMode: 'login' | 'register' | 'forgot') {
  mode.value = nextMode;
  error.value = '';
  success.value = '';
}
</script>

<template>
  <div class="login-page">
    <section class="login-story">
      <RouterLink to="/login" class="brand login-brand">
        <span class="brand-mark">e<span>✳</span></span>
        <span><strong>học cùng AI</strong><small>HỌC THEO CÁCH CỦA BẠN</small></span>
      </RouterLink>
      <div class="story-content">
        <div class="eyebrow"><span class="eyebrow-line"></span> MỘT NGƯỜI BẠN ĐỒNG HÀNH MỚI</div>
        <h1>Học điều bạn<br /><em>thực sự tò mò.</em></h1>
        <p class="story-lede">Bài học được tạo riêng cho bạn, từ tài liệu của bạn, theo nhịp học của bạn.</p>
        <div class="story-illustration" aria-hidden="true">
          <div class="orb orb-one"></div><div class="orb orb-two"></div>
          <div class="book book-back"></div><div class="book book-mid"></div>
          <div class="book book-front"><div class="book-sun">✳</div><div class="book-lines"></div></div>
          <div class="floating-card card-note"><span>✦</span><b>Học từng chút một</b><small>vẫn là tiến bộ</small></div>
          <div class="floating-card card-formula"><small>x² + y²</small><b>= ✨</b></div>
          <div class="story-star star-a">✦</div><div class="story-star star-b">✳</div><div class="story-star star-c">✦</div>
        </div>
        <div class="story-footer"><span>✳</span> Một hành trình học tập của riêng bạn</div>
      </div>
    </section>
    <section class="login-panel">
      <div class="login-card">
        <div class="mobile-brand brand"><span class="brand-mark">e<span>✳</span></span><span><strong>học cùng AI</strong><small>HỌC THEO CÁCH CỦA BẠN</small></span></div>
        <div class="form-kicker">{{ mode === 'register' ? 'BẮT ĐẦU HÀNH TRÌNH' : mode === 'forgot' ? 'KHÔI PHỤC TÀI KHOẢN' : 'CHÀO MỪNG TRỞ LẠI' }}</div>
        <h2>{{ mode === 'register' ? 'Tạo tài khoản' : mode === 'forgot' ? 'Quên mật khẩu?' : 'Đăng nhập' }}</h2>
        <p class="form-subtitle">{{ mode === 'register' ? 'Tạo không gian học tập cá nhân của bạn.' : mode === 'forgot' ? 'Nhập email để nhận liên kết đặt lại mật khẩu.' : 'Tiếp tục hành trình học tập của bạn.' }}</p>
        <form class="auth-form" @submit.prevent="mode === 'forgot' ? requestPasswordReset() : submit()">
          <label v-if="registering" class="field-label">Tên của bạn<input v-model="name" required minlength="2" autocomplete="name" placeholder="Ví dụ: Minh Anh" /></label>
          <label class="field-label">Email<input v-model="email" required type="email" autocomplete="email" placeholder="ban@email.com" /></label>
          <label v-if="mode !== 'forgot'" class="field-label">Mật khẩu<input v-model="password" required type="password" :minlength="registering ? 8 : undefined" autocomplete="current-password" :placeholder="registering ? 'Ít nhất 8 ký tự' : 'Nhập mật khẩu'" /></label>
          <button v-if="mode === 'login'" class="text-button forgot-password-link" type="button" @click="changeMode('forgot')">Quên mật khẩu?</button>
          <p v-if="error" class="inline-error">{{ error }}</p>
          <p v-if="success" class="inline-success">{{ success }}</p>
          <button class="button button-primary button-wide" type="submit" :disabled="busy">
            {{ busy ? 'Đang xử lý…' : mode === 'register' ? 'Tạo tài khoản' : mode === 'forgot' ? 'Gửi liên kết đặt lại' : 'Đăng nhập' }} <span>→</span>
          </button>
        </form>
        <p v-if="mode === 'forgot'" class="auth-switch"><button type="button" @click="changeMode('login')">← Quay lại đăng nhập</button></p>
        <p v-else class="auth-switch">{{ registering ? 'Đã có tài khoản?' : 'Chưa có tài khoản?' }} <button type="button" @click="changeMode(registering ? 'login' : 'register')">{{ registering ? 'Đăng nhập' : 'Tạo tài khoản' }}</button></p>
        <template v-if="mode !== 'forgot'">
          <div class="login-divider"><span></span> CÁ NHÂN HÓA THEO BẠN <span></span></div>
          <div class="login-footnote"><span>✧</span><p>Chọn lớp, môn học và tài liệu để AI cùng bạn tạo nên bài học phù hợp.</p></div>
        </template>
      </div>
      <div class="login-copyright">© 2026 e-learning-ai <span>·</span> Học tập với sự tò mò</div>
    </section>
  </div>
</template>
