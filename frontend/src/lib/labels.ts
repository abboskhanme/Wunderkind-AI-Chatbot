import type {
  BookingStatus, FunnelSource, FunnelStatKey, FunnelStep, LeadStatus, MessageRole, ReplyWindow,
} from '@/api/types'

export const STATUS_LABELS: Record<LeadStatus, string> = {
  new: 'Yangi',
  contacted: "Bog'lanildi",
  trial: 'Suhbatga yozildi',
  enrolled: "Qabul qilindi",
  lost: "Yo'qotildi",
}

export const STATUS_COLORS: Record<LeadStatus, string> = {
  new: 'bg-sky-50 text-sky-700 ring-sky-200',
  contacted: 'bg-amber-50 text-amber-700 ring-amber-200',
  trial: 'bg-violet-50 text-violet-700 ring-violet-200',
  enrolled: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  lost: 'bg-gray-100 text-gray-600 ring-gray-200',
}

export const STATUSES = Object.keys(STATUS_LABELS) as LeadStatus[]

export const STAGE_LABELS: Record<string, string> = {
  greeting: 'Salomlashish',
  discovery: 'Ehtiyojni aniqlash',
  offer: 'Taklif',
  objection: "E'tiroz",
  closing: 'Yakunlash',
  booked: 'Yozildi',
  support: "Qo'llab-quvvatlash",
}

export const CHANNEL_LABELS: Record<string, string> = {
  instagram: 'Instagram',
  telegram: 'Telegram',
}

export const SOURCE_LABELS: Record<string, string> = {
  instagram: 'Instagram',
  telegram: 'Telegram',
  instagram_import: 'Instagram (import)',
  lead_magnet_instagram: 'Qo\'llanma (Instagram)',
  lead_magnet_telegram: 'Qo\'llanma (Telegram)',
}

export const ROLE_LABELS: Record<MessageRole, string> = {
  user: 'Mijoz',
  assistant: 'AI',
  operator: 'Operator',
  system: 'Tizim',
}

export const WINDOW_LABELS: Record<ReplyWindow, string> = {
  open: 'Oyna ochiq',
  human_agent: 'Faqat operator (7 kun)',
  closed: 'Oyna yopiq',
}

export const USER_ROLE_LABELS: Record<string, string> = {
  admin: 'Administrator',
  operator: 'Operator',
}

// --- Lead-magnet funnel ---------------------------------------------------------

export const FUNNEL_SOURCE_LABELS: Record<FunnelSource, string> = {
  instagram: 'Instagram',
  telegram_channel: 'Telegram kanal',
  telegram_direct: 'Telegram bot',
}

export const FUNNEL_SOURCES = Object.keys(FUNNEL_SOURCE_LABELS) as FunnelSource[]

export const FUNNEL_SOURCE_COLORS: Record<FunnelSource, string> = {
  instagram: 'bg-pink-50 text-pink-700 ring-pink-200',
  telegram_channel: 'bg-sky-50 text-sky-700 ring-sky-200',
  telegram_direct: 'bg-brand-50 text-brand-700 ring-brand-200',
}

/** Where the person currently is in the funnel (entry `step`). */
export const FUNNEL_STEP_LABELS: Record<FunnelStep, string> = {
  ig_waiting_follow: 'Obunani kutmoqda',
  ig_link_sent: 'Havola yuborildi',
  tg_channel_gate: "Kanalga a'zolik kutilmoqda",
  ask_name: "Ism so'ralmoqda",
  ask_phone: "Telefon so'ralmoqda",
  ask_grade: "Sinf so'ralmoqda",
  pdf_pending: 'PDF navbatda',
  pdf_sent: 'PDF yuborildi',
}

export const FUNNEL_STEPS = Object.keys(FUNNEL_STEP_LABELS) as FunnelStep[]

export const FUNNEL_STEP_COLORS: Record<FunnelStep, string> = {
  ig_waiting_follow: 'bg-pink-50 text-pink-700 ring-pink-200',
  ig_link_sent: 'bg-pink-50 text-pink-700 ring-pink-200',
  tg_channel_gate: 'bg-sky-50 text-sky-700 ring-sky-200',
  ask_name: 'bg-amber-50 text-amber-700 ring-amber-200',
  ask_phone: 'bg-amber-50 text-amber-700 ring-amber-200',
  ask_grade: 'bg-amber-50 text-amber-700 ring-amber-200',
  pdf_pending: 'bg-orange-50 text-orange-700 ring-orange-200',
  pdf_sent: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
}

/** Fallback labels for `GET /funnel/stats` steps (the server sends its own `label`). */
export const FUNNEL_STAT_LABELS: Record<FunnelStatKey, string> = {
  comments: "Kirganlar (izoh / bot)",
  link_sent: 'Havola yuborildi',
  bot_started: 'Botni ishga tushirdi',
  contact_collected: 'Telefon qoldirdi',
  pdf_sent: "Qo'llanmani oldi",
  booked: 'Suhbatga yozildi',
  attended: 'Suhbatga keldi',
}

export const BOOKING_STATUS_LABELS: Record<BookingStatus, string> = {
  scheduled: 'Belgilangan',
  attended: 'Keldi',
  no_show: 'Kelmadi',
  cancelled: 'Bekor qilingan',
}

export const BOOKING_STATUSES = Object.keys(BOOKING_STATUS_LABELS) as BookingStatus[]

export const BOOKING_STATUS_COLORS: Record<BookingStatus, string> = {
  scheduled: 'bg-sky-50 text-sky-700 ring-sky-200',
  attended: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  no_show: 'bg-rose-50 text-rose-700 ring-rose-200',
  cancelled: 'bg-gray-100 text-gray-600 ring-gray-200',
}

/** "5" → "5-sinf"; non-numeric grades ("Bog'cha") are shown as is. */
export function gradeLabel(grade: string | null | undefined): string | null {
  if (!grade) return null
  return /^\d+$/.test(grade.trim()) ? `${grade.trim()}-sinf` : grade
}
