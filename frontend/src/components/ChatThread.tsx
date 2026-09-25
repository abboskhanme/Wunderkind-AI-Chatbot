import { useEffect, useRef } from 'react'
import { StickyNote, ArrowRightLeft } from 'lucide-react'
import type { Message } from '@/api/types'
import { ROLE_LABELS, STATUS_LABELS } from '@/lib/labels'
import { fmtDateTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import type { LeadStatus } from '@/api/types'

const BUBBLE: Record<string, string> = {
  user: 'bg-white text-gray-900 ring-1 ring-gray-200',
  assistant: 'bg-brand-600 text-white',
  operator: 'bg-emerald-600 text-white',
  system: 'bg-gray-100 text-gray-700',
}

function StatusLine({ m }: { m: Message }) {
  const to = (m.meta?.to ?? m.meta?.status) as LeadStatus | undefined
  const label = to && STATUS_LABELS[to] ? `Holat: ${STATUS_LABELS[to]}` : m.text
  return (
    <div className="flex justify-center">
      <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-500">
        <ArrowRightLeft className="h-3 w-3" /> {label} · {fmtDateTime(m.created_at)}
      </span>
    </div>
  )
}

function NoteLine({ m }: { m: Message }) {
  const by = typeof m.meta?.by_name === 'string' ? m.meta.by_name : null
  return (
    <div className="mx-auto max-w-md rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
      <p className="mb-0.5 flex items-center gap-1 text-xs font-medium text-amber-700">
        <StickyNote className="h-3 w-3" /> Izoh{by ? ` · ${by}` : ''} · {fmtDateTime(m.created_at)}
      </p>
      <p className="whitespace-pre-wrap">{m.text}</p>
    </div>
  )
}

export function ChatThread({ messages, className }: { messages: Message[]; className?: string }) {
  const endRef = useRef<HTMLDivElement>(null)
  const last = messages[messages.length - 1]?.id
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [last])

  if (messages.length === 0) {
    return <div className={cn('flex items-center justify-center text-sm text-gray-400', className)}>Xabarlar yo'q</div>
  }

  return (
    <div className={cn('space-y-3', className)}>
      {messages.map((m) => {
        if (m.kind === 'status') return <StatusLine key={m.id} m={m} />
        if (m.kind === 'note') return <NoteLine key={m.id} m={m} />
        const mine = m.role !== 'user'
        const by = typeof m.meta?.by_name === 'string' ? m.meta.by_name : null
        return (
          <div key={m.id} className={cn('flex', mine ? 'justify-end' : 'justify-start')}>
            <div className="max-w-[80%]">
              <div className={cn('rounded-2xl px-3.5 py-2 text-sm shadow-sm', BUBBLE[m.role] ?? BUBBLE.system, mine ? 'rounded-br-md' : 'rounded-bl-md')}>
                {m.kind === 'comment' && (
                  <span className={cn('mb-1 block text-[10px] font-semibold uppercase tracking-wide', mine ? 'text-white/70' : 'text-pink-600')}>
                    Izoh (comment)
                  </span>
                )}
                <p className="whitespace-pre-wrap break-words">{m.text}</p>
              </div>
              <p className={cn('mt-1 px-1 text-[11px] text-gray-400', mine && 'text-right')}>
                {ROLE_LABELS[m.role] ?? m.role}
                {by && m.role === 'operator' ? ` · ${by}` : ''} · {fmtDateTime(m.created_at)}
              </p>
            </div>
          </div>
        )
      })}
      <div ref={endRef} />
    </div>
  )
}
