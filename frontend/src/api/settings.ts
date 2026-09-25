import { api } from './client'
import type { AgentStatus, AiTestResult, SettingsResponse } from './types'

export const settingsApi = {
  get: () => api.get<SettingsResponse>('/settings').then((r) => r.data),
  update: (values: Record<string, string | null>) =>
    api.put<SettingsResponse>('/settings', { values }).then((r) => r.data),
  status: () => api.get<AgentStatus>('/settings/status').then((r) => r.data),
  connectUrl: () =>
    api.post<{ url: string }>('/settings/instagram/connect-url').then((r) => r.data),
  importInstagram: () =>
    api.post<{ started: boolean }>('/settings/instagram/import').then((r) => r.data),
  testAi: () => api.post<AiTestResult>('/settings/ai/test').then((r) => r.data),
  resetTelegramWebhook: () =>
    api.post<AgentStatus>('/settings/telegram/webhook').then((r) => r.data),
  testTelegram: () =>
    api.post<{ sent: boolean; error?: string }>('/settings/telegram/test').then((r) => r.data),
}
