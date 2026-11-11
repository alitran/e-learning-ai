<script setup lang="ts">
import { computed, ref } from 'vue';
import { api } from '../lib/api';
import { clearSession } from '../lib/auth';

const token = computed(() => new URLSearchParams(window.location.hash.slice(1)).get('token') || '');
const password = ref('');
const confirmation = ref('');
const busy = ref(false);
const error = ref('');
const success = ref(false);

async function submit() {
  error.value = '';
  if (password.value !== confirmation.value) {
    error.value = 'Mật khẩu xác nhận chưa khớp.';
    return;
  }
  if (!token.value) {
    error.value = 'Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.';
    return;
  }

  busy.value = true;
  try {
    await api.post('/auth/password-resets', {
      token: token.value,
      new_password: password.value
    });
    clearSession();
    success.value = true;
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Chưa đặt lại được mật khẩu.';
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="reset-page">
    <RouterLink to="/login" class="brand reset-brand">
      <span class="brand-mark">e<span>✳</span></span>
      <span><strong>học cùng AI</strong><small>HỌC THEO CÁCH CỦA BẠN</small></span>
    </RouterLink>
    <section class="reset-card surface-card">
      <div class="form-kicker">KHÔI PHỤC TÀI KHOẢN</div>
      <h1>Đặt mật khẩu mới</h1>
      <p class="form-subtitle">Tạo mật khẩu mới có ít nhất 8 ký tự.</p>
      <div v-if="success" class="reset-success">
        <p>Mật khẩu đã được cập nhật. Hãy đăng nhập bằng mật khẩu mới.</p>
        <RouterLink class="button button-primary button-wide" to="/login">Quay lại đăng nhập <span>→</span></RouterLink>
      </div>
      <form v-else class="auth-form" @submit.prevent="submit">
        <p v-if="!token" class="inline-error">Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.</p>
        <label class="field-label">Mật khẩu mới<input v-model="password" required type="password" minlength="8" maxlength="128" autocomplete="new-password" placeholder="Ít nhất 8 ký tự" /></label>
        <label class="field-label">Nhập lại mật khẩu<input v-model="confirmation" required type="password" minlength="8" maxlength="128" autocomplete="new-password" placeholder="Nhập lại mật khẩu mới" /></label>
        <p v-if="error" class="inline-error">{{ error }}</p>
        <button class="button button-primary button-wide" type="submit" :disabled="busy || !token">{{ busy ? 'Đang cập nhật…' : 'Đặt lại mật khẩu' }} <span>→</span></button>
      </form>
      <RouterLink v-if="!success" class="text-button reset-back-link" to="/login">← Quay lại đăng nhập</RouterLink>
    </section>
    <p class="reset-footnote">Liên kết đặt lại chỉ sử dụng được một lần và hết hạn sau 30 phút.</p>
  </main>
</template>
