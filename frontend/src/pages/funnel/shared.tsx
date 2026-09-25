import { Link } from 'react-router-dom'
import { AlertTriangle, MessagesSquare, RefreshCw } from 'lucide-react'
import { errorMessage } from '@/api/client'
import type { BookingStatus, FunnelSource, FunnelStep } from '@/api/types'
import { Badge, Button, Empty } from '@/components/ui'
import {
  BOOKING_STATUS_COLORS, BOOKING_STATUS_LABELS, FUNNEL_SOURCE_COLORS, FUNNEL_SOURCE_LABELS,
  FUNNEL_STEP_COLORS, FUNNEL_STEP_LABELS,
} from '@/lib/labels'
import { cn } from '@/lib/cn'

export function ErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <Empty
      icon={<AlertTriangle className="h-6 w-6" />}
      title="Ma'lumotni yuklab bo'lmadi"
      text={errorMessage(error, 'Server bilan aloqani tekshiring.')}
      action={<Button variant="secondary" icon={<RefreshCw className="h-4 w-4" />} onClick={onRetry}>Qayta urinish</Button>}
    />
  )
}

/** Horizontal bar; SVG so the width needs no inline style. `className` sets the fill colour. */
export function Bar({ value, max, className }: { value: number; max: number; className: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <svg className="h-2 w-full overflow-hidden rounded-full" aria-hidden="true">
      <rect width="100%" height="100%" className="fill-gray-100" />
      {pct > 0 && <rect width={`${pct}%`} height="100%" rx="4" className={className} />}
    </svg>
  )
}

export function SourceBadge({ source }: { source: FunnelSource }) {
  return <Badge className={FUNNEL_SOURCE_COLORS[source]}>{FUNNEL_SOURCE_LABELS[source] ?? source}</Badge>
}

export function StepBadge({ step }: { step: FunnelStep }) {
  return <Badge className={FUNNEL_STEP_COLORS[step]}>{FUNNEL_STEP_LABELS[step] ?? step}</Badge>
}

export function BookingStatusBadge({ status }: { status: BookingStatus }) {
  return <Badge className={BOOKING_STATUS_COLORS[status]}>{BOOKING_STATUS_LABELS[status] ?? status}</Badge>
}

/** Opens the linked lead's conversation (existing `/inbox/:leadId` route). */
export function LeadLink({ leadId, className }: { leadId: string | null; className?: string }) {
  if (!leadId) return null
  return (
    <Link
      to={`/inbox/${leadId}`}
      onClick={(e) => e.stopPropagation()}
      className={cn('inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700', className)}
      title="Suhbatlarda ochish"
    >
      <MessagesSquare className="h-3.5 w-3.5" /> Suhbat
    </Link>
  )
}
