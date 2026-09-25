import { api } from './client'
import { cleanParams } from './leads'
import type {
  BookingOut, BookingPatch, BookingStatus, FunnelEntryList, FunnelMessageInput, FunnelMessageOut,
  FunnelSlot, FunnelSource, FunnelStats, FunnelStep, LeadMagnetInfo, SendResult, SheetTestResult,
  TestMessageInput,
} from './types'

export interface FunnelEntryFilters {
  source?: FunnelSource | ''
  step?: FunnelStep | ''
  search?: string
  page?: number
  page_size?: number
}

export interface BookingFilters {
  /** YYYY-MM-DD, inclusive */
  date_from?: string
  /** YYYY-MM-DD, inclusive */
  date_to?: string
  status?: BookingStatus | ''
}

export const LEAD_MAGNET_DOWNLOAD_URL = '/api/funnel/lead-magnet/download'

export const funnelApi = {
  stats: (days: number) =>
    api.get<FunnelStats>('/funnel/stats', { params: { days } }).then((r) => r.data),
  entries: (f: FunnelEntryFilters) =>
    api.get<FunnelEntryList>('/funnel/entries', { params: cleanParams(f) }).then((r) => r.data),
  bookings: (f: BookingFilters) =>
    api.get<BookingOut[]>('/funnel/bookings', { params: cleanParams(f) }).then((r) => r.data),
  updateBooking: (id: string, body: BookingPatch) =>
    api.patch<BookingOut>(`/funnel/bookings/${id}`, body).then((r) => r.data),
  slots: (date: string) =>
    api.get<FunnelSlot[]>('/funnel/slots', { params: { date } }).then((r) => r.data),

  messages: () => api.get<FunnelMessageOut[]>('/funnel/messages').then((r) => r.data),
  createMessage: (body: FunnelMessageInput) =>
    api.post<FunnelMessageOut>('/funnel/messages', body).then((r) => r.data),
  updateMessage: (id: string, body: Partial<FunnelMessageInput>) =>
    api.patch<FunnelMessageOut>(`/funnel/messages/${id}`, body).then((r) => r.data),
  removeMessage: (id: string) => api.delete(`/funnel/messages/${id}`),
  reorderMessages: (ids: string[]) =>
    api.post<FunnelMessageOut[]>('/funnel/messages/reorder', { ids }).then((r) => r.data),
  uploadMessageImage: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.put(`/funnel/messages/${id}/image`, form)
  },
  removeMessageImage: (id: string) => api.delete(`/funnel/messages/${id}/image`),
  // Fetched with the Authorization header (a token in the URL would end up in access logs).
  // `v` busts the browser cache: the URL stays the same when the image is replaced.
  messageImageBlob: (id: string, v?: number) =>
    api
      .get<Blob>(`/funnel/messages/${id}/image`, { params: v ? { v } : undefined, responseType: 'blob' })
      .then((r) => r.data),

  leadMagnet: () => api.get<LeadMagnetInfo | null>('/funnel/lead-magnet').then((r) => r.data),
  uploadLeadMagnet: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.put('/funnel/lead-magnet', form)
  },

  sheetTest: () => api.post<SheetTestResult>('/funnel/sheet/test').then((r) => r.data),
  sheetResync: () => api.post<{ queued: number }>('/funnel/sheet/resync').then((r) => r.data),
  testMessage: (body: TestMessageInput) =>
    api.post<SendResult>('/funnel/test-message', body).then((r) => r.data),
}
