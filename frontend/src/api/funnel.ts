import { api } from './client'
import { cleanParams } from './leads'
import type {
  BookingOut, BookingPatch, BookingStatus, FunnelCreate, FunnelEntryList, FunnelMessageInput,
  FunnelMessageOut, FunnelOut, FunnelPatch, FunnelSlot, FunnelSource, FunnelStats, FunnelStep,
  LeadMagnetInfo, SendResult, SheetTestResult, TestMessageInput,
} from './types'

/**
 * `funnel_id` query param (SPEC 11.3): absent → all funnels for stats/entries/bookings,
 * → the default funnel for messages / lead magnet.
 */
const scope = (funnelId?: string) => (funnelId ? { funnel_id: funnelId } : {})

/** Text settings a funnel may override (SPEC 11.1); the global setting is the default. */
export const FUNNEL_TEXT_KEYS = [
  'FUNNEL_IG_COMMENT_REPLY',
  'FUNNEL_IG_DM_WELCOME',
  'FUNNEL_IG_NOT_FOLLOWING',
  'FUNNEL_IG_LINK_MESSAGE',
  'FUNNEL_TG_COMMENT_REPLY',
  'FUNNEL_BOT_WELCOME',
  'FUNNEL_ASK_NAME',
  'FUNNEL_ASK_PHONE',
  'FUNNEL_ASK_GRADE',
  'FUNNEL_GRADES',
  'FUNNEL_PDF_CAPTION',
  'FUNNEL_BOOK_BUTTON',
] as const

export interface FunnelEntryFilters {
  funnel_id?: string
  source?: FunnelSource | ''
  step?: FunnelStep | ''
  search?: string
  page?: number
  page_size?: number
}

export interface BookingFilters {
  funnel_id?: string
  /** YYYY-MM-DD, inclusive */
  date_from?: string
  /** YYYY-MM-DD, inclusive */
  date_to?: string
  status?: BookingStatus | ''
}

export function leadMagnetDownloadUrl(funnelId?: string): string {
  return funnelId
    ? `/api/funnel/lead-magnet/download?funnel_id=${encodeURIComponent(funnelId)}`
    : '/api/funnel/lead-magnet/download'
}

export const funnelApi = {
  funnels: () => api.get<FunnelOut[]>('/funnel/funnels').then((r) => r.data),
  createFunnel: (body: FunnelCreate) =>
    api.post<FunnelOut>('/funnel/funnels', body).then((r) => r.data),
  updateFunnel: (id: string, body: FunnelPatch) =>
    api.patch<FunnelOut>(`/funnel/funnels/${id}`, body).then((r) => r.data),
  removeFunnel: (id: string) => api.delete(`/funnel/funnels/${id}`),
  reorderFunnels: (ids: string[]) => api.post('/funnel/funnels/reorder', { ids }),

  stats: (days: number, funnelId?: string) =>
    api.get<FunnelStats>('/funnel/stats', { params: { days, ...scope(funnelId) } }).then((r) => r.data),
  entries: (f: FunnelEntryFilters) =>
    api.get<FunnelEntryList>('/funnel/entries', { params: cleanParams(f) }).then((r) => r.data),
  bookings: (f: BookingFilters) =>
    api.get<BookingOut[]>('/funnel/bookings', { params: cleanParams(f) }).then((r) => r.data),
  updateBooking: (id: string, body: BookingPatch) =>
    api.patch<BookingOut>(`/funnel/bookings/${id}`, body).then((r) => r.data),
  slots: (date: string) =>
    api.get<FunnelSlot[]>('/funnel/slots', { params: { date } }).then((r) => r.data),

  messages: (funnelId?: string) =>
    api.get<FunnelMessageOut[]>('/funnel/messages', { params: scope(funnelId) }).then((r) => r.data),
  createMessage: (body: FunnelMessageInput, funnelId?: string) =>
    api.post<FunnelMessageOut>('/funnel/messages', body, { params: scope(funnelId) }).then((r) => r.data),
  updateMessage: (id: string, body: Partial<FunnelMessageInput>) =>
    api.patch<FunnelMessageOut>(`/funnel/messages/${id}`, body).then((r) => r.data),
  removeMessage: (id: string) => api.delete(`/funnel/messages/${id}`),
  reorderMessages: (ids: string[], funnelId?: string) =>
    api.post<FunnelMessageOut[]>('/funnel/messages/reorder', { ids }, { params: scope(funnelId) }).then((r) => r.data),
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

  leadMagnet: (funnelId?: string) =>
    api.get<LeadMagnetInfo | null>('/funnel/lead-magnet', { params: scope(funnelId) }).then((r) => r.data),
  uploadLeadMagnet: (file: File, funnelId?: string) => {
    const form = new FormData()
    form.append('file', file)
    return api.put('/funnel/lead-magnet', form, { params: scope(funnelId) })
  },

  sheetTest: () => api.post<SheetTestResult>('/funnel/sheet/test').then((r) => r.data),
  sheetResync: () => api.post<{ queued: number }>('/funnel/sheet/resync').then((r) => r.data),
  testMessage: (body: TestMessageInput) =>
    api.post<SendResult>('/funnel/test-message', body).then((r) => r.data),
}
