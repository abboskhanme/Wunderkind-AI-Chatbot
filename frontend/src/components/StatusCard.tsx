import { Link } from 'react-router-dom'
import { CheckCircle2, XCircle } from 'lucide-react'
import type { AgentStatus } from '@/api/types'
import { fmtDate } from '@/lib/format'
import { Card, CardHeader } from './ui'

function Row({ ok, label, detail, to }: { ok: boolean; label: string; detail?: string | null; to?: string }) {
  return (
    <div className="flex items-start gap-3 py-2.5">
      {ok ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" /> : <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-gray-300" />}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-900">{label}</p>
        {detail && <p className="truncate text-xs text-gray-500">{detail}</p>}
      </div>
      {!ok && to && (
        <Link to={to} className="shrink-0 text-xs font-medium text-brand-600 hover:text-brand-700">
          Sozlash →
        </Link>
      )}
    </div>
  )
}

export function StatusCard({ status, canEdit }: { status: AgentStatus; canEdit: boolean }) {
  const to = canEdit ? '/settings' : undefined
  return (
    <Card>
      <CardHeader title="Agent holati" subtitle="Nima ulangan va nima yetishmayapti" />
      <div className="divide-y divide-gray-100 px-5 py-1">
        <Row ok={status.ai_ready} label={`Sun'iy intellekt (${status.ai_provider || '—'})`} detail={status.ai_ready ? 'Kalit kiritilgan' : 'API kaliti kiritilmagan'} to={to} />
        <Row
          ok={status.instagram_connected}
          label="Instagram"
          detail={status.instagram_connected ? `@${status.instagram_username ?? '—'} · token: ${fmtDate(status.instagram_token_issued_at)}` : 'Akkaunt ulanmagan'}
          to={to}
        />
        <Row
          ok={status.telegram_connected}
          label="Telegram AI bot"
          detail={status.telegram_connected ? `@${status.telegram_bot_username ?? '—'}` : 'Bot tokeni kiritilmagan'}
          to={to}
        />
        <Row ok={status.notifications_ready} label="Telegram bildirishnomalar" detail={status.notifications_ready ? 'Qaynoq leadlar xabari yoqilgan' : 'Chat ID kiritilmagan'} to={to} />
        <Row ok={Boolean(status.public_url)} label="Tashqi manzil (PUBLIC_URL)" detail={status.public_url || ".env faylida PUBLIC_URL ko'rsatilmagan"} />
      </div>
    </Card>
  )
}
