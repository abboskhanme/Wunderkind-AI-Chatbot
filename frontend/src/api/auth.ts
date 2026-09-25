import { api } from './client'
import type { LoginResponse, User } from './types'

export const authApi = {
  login: (username: string, password: string) =>
    api.post<LoginResponse>('/auth/login', { username, password }).then((r) => r.data),
  me: () => api.get<User>('/auth/me').then((r) => r.data),
}
