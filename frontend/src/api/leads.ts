import { api } from './client'
import type {
  Assignee, CustomerProfile, InboxItem, LeadDetail, LeadList, LeadOut, LeadPatch, Message,
  ReplyResult,
} from './types'

export interface LeadFilters {
  status?: string
  channel?: string
  search?: string
  min_score?: number
  has_contact?: boolean
  page?: number
  page_size?: number
}

export interface InboxFilters {
  search?: string
  channel?: string
  only_unread?: boolean
}

/** Drop empty values so they are not sent as query params. */
export function cleanParams<T extends object>(obj: T): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {}
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null || v === '' || v === false) continue
    out[k] = v as string | number | boolean
  }
  return out
}

export const leadsApi = {
  list: (f: LeadFilters) =>
    api.get<LeadList>('/leads', { params: cleanParams(f) }).then((r) => r.data),
  inbox: (f: InboxFilters) =>
    api.get<InboxItem[]>('/leads/inbox', { params: cleanParams(f) }).then((r) => r.data),
  get: (id: string) => api.get<LeadDetail>(`/leads/${id}`).then((r) => r.data),
  update: (id: string, body: LeadPatch) =>
    api.patch<LeadOut>(`/leads/${id}`, body).then((r) => r.data),
  remove: (id: string) => api.delete(`/leads/${id}`),
  markRead: (id: string) => api.post(`/leads/${id}/read`),
  reply: (id: string, text: string) =>
    api.post<ReplyResult>(`/leads/${id}/reply`, { text }).then((r) => r.data),
  botState: (id: string) =>
    api.get<{ paused: boolean }>(`/leads/${id}/bot`).then((r) => r.data),
  setBot: (id: string, enabled: boolean) =>
    api.post<{ paused: boolean }>(`/leads/${id}/bot`, { enabled }).then((r) => r.data),
  addNote: (id: string, text: string) =>
    api.post<Message>(`/leads/${id}/notes`, { text }).then((r) => r.data),
  assignees: () => api.get<Assignee[]>('/leads/assignees').then((r) => r.data),
  refreshProfile: (id: string) =>
    api.post<CustomerProfile | null>(`/leads/${id}/profile/refresh`).then((r) => r.data),
  avatarBlob: (id: string) =>
    api.get<Blob>(`/leads/${id}/avatar`, { responseType: 'blob' }).then((r) => r.data),
  exportUrl: (f: LeadFilters) => {
    const qs = new URLSearchParams(
      Object.entries(cleanParams({ ...f, page: undefined, page_size: undefined })).map(
        ([k, v]) => [k, String(v)],
      ),
    ).toString()
    return `/api/leads/export.csv${qs ? `?${qs}` : ''}`
  },
}
