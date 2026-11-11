import { clearSession, getToken } from './auth';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1';

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  const body = await response.json().catch(() => null) as { detail?: string } | null;
  if (!response.ok) {
    if (response.status === 401) {
      clearSession();
      if (window.location.pathname !== '/login') window.location.assign('/login');
    }
    const fallbackMessage = response.status === 413
      ? 'File vượt quá giới hạn tải lên là 20 MB. Vui lòng nén file hoặc chọn file nhỏ hơn.'
      : 'Đã xảy ra lỗi. Vui lòng thử lại.';
    throw new Error(body?.detail || fallbackMessage);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) => request<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) }),
  put: <T>(path: string, data: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(data) }),
  patch: <T>(path: string, data: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(data) }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' })
};
