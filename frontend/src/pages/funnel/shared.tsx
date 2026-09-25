import { Link } from 'react-router-dom'
import { AlertTriangle, Copy, MessagesSquare, RefreshCw } from 'lucide-react'
import { errorMessage } from '@/api/client'
import type { BookingStatus, FunnelOut, FunnelSource, FunnelStep } from '@/api/types'
import { Badge, Button, Empty } from '@/components/ui'
import {
  BOOKING_STATUS_COLORS, BOOKING_STATUS_LABELS, FUNNEL_SOURCE_COLORS, FUNNEL_SOURCE_LABELS,
  FUNNEL_STEP_COLORS, FUNNEL_STEP_LABELS,
} from '@/lib/labels'
import { cn } from '@/lib/cn'
import { copyText } from '@/lib/clipboard'

export const FUNNELS_KEY = ['funnel', 'funnels'] as const

/** Props every Voronka tab receives from the page shell. */
export interface FunnelTabProps {
  /** Selected funnel; null = "Hammasi" (all funnels) */
  funnel: FunnelOut | null
  funnels: FunnelOut[]
  selectFunnel: (id: string | null) => void
}

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

export function FunnelBadge({ name }: { name: string | null | undefined }) {
  if (!name) return null
  return <Badge className="bg-violet-50 text-violet-700 ring-violet-200">{name}</Badge>
}

export function CopyRow({ label, value, hint }: { label: string; value: string | null; hint?: string }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-gray-700">{label}</p>
      <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 ring-1 ring-gray-200">
        <code className="min-w-0 flex-1 truncate text-xs text-gray-800">{value || "Bot ulanmagan — havola yo'q"}</code>
        {value && (
          <button type="button" onClick={() => copyText(value)} className="rounded p-1 text-gray-400 hover:bg-white hover:text-gray-700" title="Nusxa olish" aria-label="Nusxa olish">
            <Copy className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  )
}
