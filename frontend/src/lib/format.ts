import { format, formatDistanceToNowStrict, isToday, isYesterday, parseISO } from 'date-fns'
import { uz } from 'date-fns/locale'

function toDate(value: string | Date): Date {
  return typeof value === 'string' ? parseISO(value) : value
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return format(toDate(value), 'dd.MM.yyyy HH:mm')
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return '—'
  return format(toDate(value), 'dd.MM.yyyy')
}

/** Compact time for chat lists: "14:05", "Kecha", "12.03". */
export function fmtShort(value: string | null | undefined): string {
  if (!value) return ''
  const d = toDate(value)
  if (isToday(d)) return format(d, 'HH:mm')
  if (isYesterday(d)) return 'Kecha'
  return format(d, 'dd.MM')
}

export function fmtAgo(value: string | null | undefined): string {
  if (!value) return '—'
  return formatDistanceToNowStrict(toDate(value), { locale: uz, addSuffix: true })
}

export function fmtNumber(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString('ru-RU').replace(/,/g, ' ')
}

/** File size: "840 KB", "2.4 MB". */
export function fmtBytes(n: number | null | undefined): string {
  const b = n ?? 0
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${Math.round(b / 1024)} KB`
  return `${(b / 1024 / 1024).toFixed(1)} MB`
}

/** Minutes as a readable duration: "10 daqiqa", "1 kun 3 soat". */
export function fmtMinutes(total: number): string {
  if (total <= 0) return 'darhol'
  const days = Math.floor(total / 1440)
  const hours = Math.floor((total % 1440) / 60)
  const minutes = total % 60
  const parts: string[] = []
  if (days) parts.push(`${days} kun`)
  if (hours) parts.push(`${hours} soat`)
  if (minutes) parts.push(`${minutes} daqiqa`)
  return parts.join(' ')
}

/** Day heading: "Dushanba, 28.09.2026". */
export function fmtDayTitle(value: string | Date): string {
  return format(toDate(value), 'EEEE, dd.MM.yyyy', { locale: uz })
}
