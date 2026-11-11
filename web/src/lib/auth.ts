import type { User } from './types';
import { ref } from 'vue';

const TOKEN_KEY = 'ela_access_token';
const USER_KEY = 'ela_user';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): User | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export const authUser = ref<User | null>(getUser());

export function isAuthenticated(): boolean {
  return Boolean(getToken());
}

export function saveSession(token: string, user: User): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  authUser.value = user;
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  authUser.value = null;
}
