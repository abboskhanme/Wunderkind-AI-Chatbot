import { Instagram, Send } from 'lucide-react'
import type { Channel, LeadStatus } from '@/api/types'
import { STATUS_COLORS, STATUS_LABELS } from '@/lib/labels'
import { cn } from '@/lib/cn'
import { Badge } from './ui'

export function StatusBadge({ status }: { status: LeadStatus }) {
  return <Badge className={STATUS_COLORS[status] ?? undefined}>{STATUS_LABELS[status] ?? status}</Badge>
}

export function ChannelIcon({ channel, className }: { channel: Channel | string; className?: string }) {
  if (channel === 'telegram') {
    return (
      <span className={cn('inline-flex items-center justify-center rounded-full bg-sky-100 p-1 text-sky-600', className)} title="Telegram">
        <Send className="h-3.5 w-3.5" />
      </span>
    )
  }
  return (
    <span className={cn('inline-flex items-center justify-center rounded-full bg-pink-100 p-1 text-pink-600', className)} title="Instagram">
      <Instagram className="h-3.5 w-3.5" />
    </span>
  )
}

export function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 70 ? 'bg-rose-50 text-rose-700 ring-rose-200'
      : score >= 40 ? 'bg-amber-50 text-amber-700 ring-amber-200'
        : 'bg-gray-100 text-gray-600 ring-gray-200'
  return <Badge className={color}>{score >= 70 ? '🔥 ' : ''}{score}</Badge>
}

export function leadTitle(l: {
  name: string | null
  username: string | null
  contact?: string | null
  profile_name?: string | null
}) {
  return l.name || l.profile_name || (l.username ? `@${l.username}` : null) || l.contact || 'Nomsiz mijoz'
}
