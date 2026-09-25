import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { CheckCircle2, Copy, DownloadCloud, Instagram, RefreshCw, Save, Send, Sparkles, XCircle } from 'lucide-react'
import { settingsApi } from '@/api/settings'
import { errorMessage } from '@/api/client'
import type { AgentStatus, AiTestResult, SettingGroup } from '@/api/types'
import { Button, Card, CardHeader, Loading, PageHeader } from '@/components/ui'
import { StatusCard } from '@/components/StatusCard'
import { SettingField, changedValues, initialDraft, mergeDraft, type Draft } from '@/components/SettingField'
import { copyText } from '@/lib/clipboard'
import { fmtDate } from '@/lib/format'

function CopyRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-gray-500">{label}</p>
      <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 ring-1 ring-gray-200">
        <code className="min-w-0 flex-1 truncate text-xs text-gray-800">{value || ".env faylida PUBLIC_URL sozlanmagan (serverga chiqarilganda to'ldiriladi)"}</code>
        {value && (
          <button onClick={() => copyText(value)} className="rounded p-1 text-gray-400 hover:bg-white hover:text-gray-700" title="Nusxa olish">
            <Copy className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}

function InstagramExtras({ status }: { status: AgentStatus }) {
  const connect = useMutation({
    mutationFn: settingsApi.connectUrl,
    onSuccess: ({ url }) => {
      window.location.href = url
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const importer = useMutation({
    mutationFn: settingsApi.importInstagram,
    onSuccess: () => toast.success('Import boshlandi. Natija Telegram bildirishnomasiga keladi.'),
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <div className="space-y-4 rounded-lg bg-pink-50/40 p-4 ring-1 ring-pink-100">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-gray-900">
            {status.instagram_connected ? `Ulangan: @${status.instagram_username ?? '—'}` : 'Instagram akkaunt ulanmagan'}
          </p>
          <p className="text-xs text-gray-500">
            {status.instagram_connected
              ? `Token olingan: ${fmtDate(status.instagram_token_issued_at)} · 60 kunlik, avtomatik yangilanadi`
              : "Avval App ID, App Secret va Verify token'ni saqlang, so'ng «Ulash» tugmasini bosing."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            icon={<Instagram className="h-4 w-4" />}
            loading={connect.isPending}
            disabled={!status.instagram_ready}
            title={status.instagram_ready ? undefined : "Avval App ID, App Secret, Verify token'ni saqlang (PUBLIC_URL ham kerak)"}
            onClick={() => connect.mutate()}
          >
            {status.instagram_connected ? 'Qayta ulash' : 'Ulash'}
          </Button>
          <Button
            variant="secondary"
            icon={<DownloadCloud className="h-4 w-4" />}
            disabled={!status.instagram_connected}
            loading={importer.isPending}
            onClick={() => {
              if (window.confirm("Oxirgi 30 kundagi Instagram suhbatlari import qilinadi (AI ularga javob yozmaydi). Davom etasizmi?")) importer.mutate()
            }}
          >
            Eski suhbatlarni import qilish
          </Button>
        </div>
      </div>
      <CopyRow label="Webhook manzili (Meta App → Instagram → Webhooks: comments, messages)" value={status.webhooks.instagram ?? ''} />
      <CopyRow label="OAuth redirect URI (Meta App → Instagram → Business login settings)" value={status.public_url ? `${status.public_url}/connect/callback` : ''} />
    </div>
  )
}

const TG_WEBHOOK_TEXT: Record<AgentStatus['telegram_webhook']['state'], string> = {
  not_configured: 'Bot tokeni kiritilmagan',
  no_public_url: ".env da PUBLIC_URL yo'q — webhook o'rnatib bo'lmaydi (serverga chiqarilganda ishlaydi)",
  polling: "Lokal rejim: bot xabarlarni o'zi so'rab oladi (PUBLIC_URL yo'q)",
  ok: 'Webhook ishlayapti — xabarlar kelyapti',
  wrong_url: "Webhook boshqa manzilga o'rnatilgan",
  error: 'Webhook xatosi',
}

function TelegramExtras({ status }: { status: AgentStatus }) {
  const qc = useQueryClient()
  const reset = useMutation({
    mutationFn: settingsApi.resetTelegramWebhook,
    onSuccess: (st) => {
      qc.setQueryData(['settings'], (old: { groups: SettingGroup[]; status: AgentStatus } | undefined) =>
        old ? { ...old, status: st } : old)
      st.telegram_webhook.state === 'ok' ? toast.success("Webhook o'rnatildi") : toast.error(st.telegram_webhook.error || TG_WEBHOOK_TEXT[st.telegram_webhook.state])
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const wh = status.telegram_webhook
  const test = useMutation({
    mutationFn: settingsApi.testTelegram,
    onSuccess: (r) => (r.sent ? toast.success('Test xabar yuborildi') : toast.error(r.error || 'Yuborilmadi')),
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <div className="space-y-4 rounded-lg bg-sky-50/40 p-4 ring-1 ring-sky-100">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-gray-900">
            {status.telegram_connected ? `AI bot: @${status.telegram_bot_username ?? '—'}` : 'Telegram AI bot ulanmagan'}
          </p>
          <p className="text-xs text-gray-500">
            Webhook token saqlanganda avtomatik o'rnatiladi. Bildirishnoma uchun chat ID'ni bilish: botga /id yozing. Test tugmasidan oldin sozlamalarni saqlang.
          </p>
        </div>
        <Button variant="secondary" icon={<Send className="h-4 w-4" />} loading={test.isPending} onClick={() => test.mutate()}>
          Test bildirishnoma
        </Button>
      </div>
      <div className={`flex flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2 text-xs ring-1 ${wh.state === 'ok' || wh.state === 'polling' ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : wh.state === 'not_configured' || wh.state === 'no_public_url' ? 'bg-gray-50 text-gray-600 ring-gray-200' : 'bg-red-50 text-red-700 ring-red-200'}`}>
        <span className="flex items-center gap-1.5">
          {wh.state === 'ok' ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
          {TG_WEBHOOK_TEXT[wh.state]}{wh.error ? `: ${wh.error}` : ''}
        </span>
        {(wh.state === 'wrong_url' || wh.state === 'error') && (
          <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={reset.isPending} onClick={() => reset.mutate()}>
            Qayta o'rnatish
          </Button>
        )}
      </div>
      <CopyRow label="Webhook manzili (avtomatik o'rnatiladi)" value={status.webhooks.telegram ?? ''} />
    </div>
  )
}

function AiExtras({ status }: { status: AgentStatus }) {
  const [result, setResult] = useState<AiTestResult>()
  const test = useMutation({
    mutationFn: settingsApi.testAi,
    onSuccess: setResult,
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-violet-50/40 p-4 ring-1 ring-violet-100">
      <div className="min-w-0 text-sm">
        {!result && (
          <p className="text-gray-700">
            {status.ai_ready ? 'Kalit kiritilgan. Ishlashini tekshirib ko\'ring.' : "AI kaliti kiritilmagan — agent mijozlarga javob bermaydi."}
          </p>
        )}
        {result?.ok && (
          <p className="flex items-center gap-1.5 text-emerald-700">
            <CheckCircle2 className="h-4 w-4 shrink-0" /> Ishlayapti: {result.provider} · {result.model} — «{result.reply}»
          </p>
        )}
        {result && !result.ok && (
          <p className="flex items-center gap-1.5 text-red-700">
            <XCircle className="h-4 w-4 shrink-0" /> {result.error}
          </p>
        )}
        <p className="mt-0.5 text-xs text-gray-500">Kalitni o'zgartirsangiz, avval «Saqlash»ni bosing.</p>
      </div>
      <Button variant="secondary" icon={<Sparkles className="h-4 w-4" />} loading={test.isPending} onClick={() => test.mutate()}>
        AI'ni tekshirish
      </Button>
    </div>
  )
}

function GroupCard({ group, extras, onDirty }: {
  group: SettingGroup
  extras?: ReactNode
  onDirty: (id: string, dirty: boolean) => void
}) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Draft>(() => initialDraft(group.items))
  const prevItems = useRef(group.items)
  // Server data changed (maybe another group saved): keep this group's unsaved edits.
  useEffect(() => {
    if (prevItems.current !== group.items) {
      const before = prevItems.current
      setDraft((d) => mergeDraft(before, group.items, d))
      prevItems.current = group.items
    }
  }, [group.items])
  const changes = changedValues(group.items, draft)
  const dirty = Object.keys(changes).length > 0
  useEffect(() => onDirty(group.id, dirty), [group.id, dirty, onDirty])

  const save = useMutation({
    mutationFn: () => settingsApi.update(changes),
    onSuccess: (res) => {
      const fresh = res.groups.find((g) => g.id === group.id)
      if (fresh) setDraft(initialDraft(fresh.items))
      qc.setQueryData(['settings'], res)
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      toast.success('Saqlandi va darhol qo\'llandi')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <Card>
      <CardHeader
        title={dirty ? `${group.title} •` : group.title}
        action={
          <Button size="sm" icon={<Save className="h-3.5 w-3.5" />} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
            Saqlash
          </Button>
        }
      />
      <div className="space-y-5 px-5 py-5">
        {extras}
        <div className="grid gap-5 md:grid-cols-2">
          {group.items.map((item) => (
            <div key={item.key} className={item.type === 'textarea' ? 'md:col-span-2' : undefined}>
              <SettingField item={item} value={draft[item.key] ?? ''} onChange={(v) => setDraft((d) => ({ ...d, [item.key]: v }))} />
            </div>
          ))}
        </div>
      </div>
    </Card>
  )
}

export default function SettingsPage() {
  const { data, isLoading } = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get })
  const dirtyGroups = useRef(new Set<string>())
  const onDirty = useCallback((id: string, dirty: boolean) => {
    if (dirty) dirtyGroups.current.add(id)
    else dirtyGroups.current.delete(id)
  }, [])
  // Warn before closing/reloading the tab with unsaved changes
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirtyGroups.current.size) e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  if (isLoading || !data) return <Loading />
  // knowledge → Bilim bazasi page; funnel/gsheet → Voronka page (Sozlamalar tab)
  const groups = data.groups.filter((g) => !['knowledge', 'funnel', 'gsheet'].includes(g.id))

  return (
    <>
      <PageHeader title="Sozlamalar" subtitle="O'zgarishlar serverni qayta ishga tushirmasdan darhol qo'llanadi" />
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          {groups.map((g) => (
            <GroupCard
              key={g.id}
              group={g}
              onDirty={onDirty}
              extras={
                g.id === 'ai' ? <AiExtras status={data.status} />
                  : g.id === 'instagram' ? <InstagramExtras status={data.status} />
                  : g.id === 'telegram' ? <TelegramExtras status={data.status} />
                  : undefined
              }
            />
          ))}
        </div>
        <div className="lg:sticky lg:top-6 lg:self-start">
          <StatusCard status={data.status} canEdit={false} />
        </div>
      </div>
    </>
  )
}
