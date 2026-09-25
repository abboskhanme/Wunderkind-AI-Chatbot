import { api } from './client'
import type { BotMenu, MenuItem, MenuItemInput } from './types'

export const botMenuApi = {
  get: () => api.get<BotMenu>('/bot-menu').then((r) => r.data),
  setGreeting: (greeting: string) =>
    api.put<{ greeting: string }>('/bot-menu/greeting', { greeting }).then((r) => r.data),
  create: (body: MenuItemInput) => api.post<MenuItem>('/bot-menu/items', body).then((r) => r.data),
  update: (id: string, body: Partial<MenuItemInput>) =>
    api.patch<MenuItem>(`/bot-menu/items/${id}`, body).then((r) => r.data),
  remove: (id: string) => api.delete(`/bot-menu/items/${id}`),
  reorder: (ids: string[]) =>
    api.post<MenuItem[]>('/bot-menu/items/reorder', { ids }).then((r) => r.data),
  uploadImages: (id: string, files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return api.post<MenuItem>(`/bot-menu/items/${id}/images`, form).then((r) => r.data)
  },
  removeImage: (imageId: string) => api.delete(`/bot-menu/images/${imageId}`),
  // Fetched with the Authorization header (a token in the URL would end up in access logs)
  imageBlob: (imageId: string) =>
    api.get<Blob>(`/bot-menu/images/${imageId}`, { responseType: 'blob' }).then((r) => r.data),
}
