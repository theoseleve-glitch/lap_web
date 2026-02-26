import { api } from './api-client';

export interface AuthUser {
  id: number;
  email: string;
  display_name: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  return api.post<LoginResponse>('/auth/login', { email, password });
}

export async function register(
  email: string,
  password: string,
  displayName: string,
): Promise<{ user: AuthUser }> {
  return api.post<{ user: AuthUser }>('/auth/register', {
    email,
    password,
    display_name: displayName,
  });
}

export async function verifyEmail(token: string): Promise<{ verified: boolean }> {
  return api.post<{ verified: boolean }>('/auth/verify-email', { token });
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout');
}

export async function refreshToken(): Promise<{ access_token: string }> {
  return api.post<{ access_token: string }>('/auth/refresh');
}
