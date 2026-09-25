import { api } from './client'
import type { Dashboard } from './types'

export const dashboardApi = {
  get: (days: number) => api.get<Dashboard>('/dashboard', { params: { days } }).then((r) => r.data),
}
