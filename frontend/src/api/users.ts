import { api } from './client'
import type { Role, User } from './types'

export interface UserCreate {
  username: string
  full_name: string
  password: string
  role: Role
}

export interface UserPatch {
  full_name?: string
  password?: string
  role?: Role
  is_active?: boolean
}

export const usersApi = {
  list: () => api.get<User[]>('/users').then((r) => r.data),
  create: (body: UserCreate) => api.post<User>('/users', body).then((r) => r.data),
  update: (id: string, body: UserPatch) => api.patch<User>(`/users/${id}`, body).then((r) => r.data),
  remove: (id: string) => api.delete(`/users/${id}`),
}
