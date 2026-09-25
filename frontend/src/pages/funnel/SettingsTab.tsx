import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { CheckCircle2, FileSpreadsheet, Info, RefreshCw, Save, Send, Settings2, XCircle } from 'lucide-react'
import { settingsApi } from '@/api/settings'
import { funnelApi, FUNNEL_TEXT_KEYS } from '@/api/funnel'
import { errorMessage } from '@/api/client'
import type { SendResult, SettingGroup, SettingItem, SheetTestResult, TestMessageKind } from '@/api/types'
import { Button, Card, CardHeader, Empty, Input, Label, Loading, Select } from '@/components/ui'
import { SettingField, changedValues, initialDraft, mergeDraft, type Draft } from '@/components/SettingField'
import { ErrorState, type FunnelTabProps } from './shared'
import { MESSAGES_KEY } from './MessagesTab'

/** Keys edited per funnel (keywords + text overrides) — not shown among the shared settings. */
const PER_FUNNEL_KEYS = new Set<string>(['FUNNEL_KEYWORDS', ...FUNNEL_TEXT_KEYS])

// --- Settings groups (rendered with the shared SettingField) --------------------

interface Section {
  title: string
  match: (key: string) => boolean
}

const inList = (keys: string[]) => (key: string) => keys.includes(key)

/** Visual split of the shared `funnel` settings; unknown keys fall into "Boshqa". */
const FUNNEL_SECTIONS: Section[] = [
  { title: 'Umumiy', match: inList(['FUNNEL_ENABLED', 'FUNNEL_BOT_START_FUNNEL']) },
  { title: 'Instagram', match: (k) => k.startsWith('FUNNEL_IG_') },
  { title: 'Telegram kanal', match: (k) => k.startsWith('FUNNEL_TG_') },
  {
    title: 'Suhbat jadvali',
    match: inList([
      'FUNNEL_WORK_DAYS', 'FUNNEL_DAY_START', 'FUNNEL_DAY_END', 'FUNNEL_SLOT_MINUTES',
      'FUNNEL_SLOT_CAPACITY', 'FUNNEL_BOOK_DAYS_AHEAD', 'FUNNEL_HOLIDAYS',
    ]),
  },
  {
    title: 'Tasdiqlash va eslatma',
    match: inList([
      'FUNNEL_STAFF_NAME', 'FUNNEL_STAFF_PHONE', 'FUNNEL_ADDRESS', 'FUNNEL_LOCATION_LAT',
      'FUNNEL_LOCATION_LON', 'FUNNEL_CONFIRM_TEXT', 'FUNNEL_REMINDER_TIME', 'FUNNEL_REMINDER_TEXT',
    ]),
  },
]

function splitSections(items: SettingItem[], sections: Section[] | undefined): { title: string | null; items: SettingItem[] }[] {
  if (!sections) return [{ title: null, items }]
  const out = sections.map((s) => ({ title: s.title as string | null, items: [] as SettingItem[] }))
  const rest: SettingItem[] = []
  for (const item of items) {
    const i = sections.findIndex((s) => s.match(item.key))
    if (i >= 0) out[i].items.push(item)
    else rest.push(item)
  }
  if (rest.length) out.push({ title: 'Boshqa', items: rest })
  return out.filter((s) => s.items.length > 0)
}

function FieldGrid({ items, draft, setDraft }: {
  items: SettingItem[]
  draft: Draft
  setDraft: (fn: (d: Draft) => Draft) => void
}) {
  return (
    <div className="grid gap-5 md:grid-cols-2">
      {items.map((item) => (
        <div key={item.key} className={item.type === 'textarea' ? 'md:col-span-2' : undefined}>
          <SettingField item={item} value={draft[item.key] ?? ''} onChange={(v) => setDraft((d) => ({ ...d, [item.key]: v }))} />
        </div>
      ))}
    </div>
  )
}

/** Same behaviour as the Sozlamalar page group card; saves only this group's changed keys. */
function GroupCard({ group, sections, extras, onDirty }: {
  group: SettingGroup
  sections?: Section[]
  extras?: ReactNode
  onDirty: (id: string, dirty: boolean) => void
}) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Draft>(() => initialDraft(group.items))
  const prevItems = useRef(group.items)
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
      toast.success("Saqlandi va darhol qo'llandi")
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const saveButton = (size: 'sm' | 'md') => (
    <Button size={size} icon={<Save className={size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'} />} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
      Saqlash
    </Button>
  )

  return (
    <Card>
      <CardHeader title={dirty ? `${group.title} •` : group.title} action={saveButton('sm')} />
      <div className="space-y-6 px-5 py-5">
        {extras}
        {splitSections(group.items, sections).map((s) => (
          <section key={s.title ?? 'all'} className="space-y-4">
            {s.title && <h3 className="border-b border-gray-100 pb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{s.title}</h3>}
            <FieldGrid items={s.items} draft={draft} setDraft={setDraft} />
          </section>
        ))}
      </div>
      {dirty && (
        <div className="sticky bottom-0 flex items-center justify-end gap-3 rounded-b-xl border-t border-gray-100 bg-white/95 px-5 py-3 backdrop-blur">
          <span className="text-xs text-amber-600">Saqlanmagan o'zgarishlar bor</span>
          {saveButton('md')}
        </div>
      )}
    </Card>
  )
}

// --- Google Sheets ----------------------------------------------------------------

function SheetExtras() {
  const [result, setResult] = useState<SheetTestResult>()
  const test = useMutation({
    mutationFn: funnelApi.sheetTest,
    onSuccess: setResult,
    onError: (e) => toast.error(errorMessage(e)),
  })
  const resync = useMutation({
    mutationFn: funnelApi.sheetResync,
    onSuccess: (r) => toast.success(`${r.queued} ta yozuv navbatga qo'yildi — bir necha daqiqada jadvalga yoziladi`),
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-emerald-50/40 p-4 ring-1 ring-emerald-100">
      <div className="min-w-0 text-sm">
        {!result && (
          <p className="text-gray-700">Jadvalni xizmat akkauntining email manziliga «Muharrir» sifatida ulashing, so'ng tekshiring.</p>
        )}
        {result?.ok && (
          <p className="flex items-center gap-1.5 text-emerald-700">
            <CheckCircle2 className="h-4 w-4 shrink-0" /> Ulandi{result.title ? `: «${result.title}»` : ''}
          </p>
        )}
        {result && !result.ok && (
          <p className="flex items-center gap-1.5 text-red-700">
            <XCircle className="h-4 w-4 shrink-0" /> {result.error || "Ulanib bo'lmadi"}
          </p>
        )}
        <p className="mt-0.5 text-xs text-gray-500">Sozlamani o'zgartirsangiz, avval «Saqlash»ni bosing.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" icon={<FileSpreadsheet className="h-4 w-4" />} loading={test.isPending} onClick={() => test.mutate()}>
          Google Sheets'ni tekshirish
        </Button>
        <Button
          variant="secondary"
          icon={<RefreshCw className="h-4 w-4" />}
          loading={resync.isPending}
          onClick={() => {
            if (window.confirm("Barcha yozuvlar jadvalga qaytadan yoziladi. Davom etasizmi?")) resync.mutate()
          }}
        >
          Qayta sinxronlash
        </Button>
      </div>
    </div>
  )
}

// --- Test message -------------------------------------------------------------------

const KIND_LABELS: Record<TestMessageKind, string> = {
  confirm: 'Suhbat tasdiqlanishi',
  reminder: 'Suhbat kuni eslatma',
  sales: 'Sotuv xabari',
}

function TestMessageCard({ funnels, initialFunnelId }: { funnels: FunnelTabProps['funnels']; initialFunnelId: string | undefined }) {
  const [chatId, setChatId] = useState('')
  const [kind, setKind] = useState<TestMessageKind>('confirm')
  const [funnelId, setFunnelId] = useState(initialFunnelId ?? funnels.find((f) => f.is_default)?.id ?? '')
  const [messageId, setMessageId] = useState('')
  const [result, setResult] = useState<SendResult>()
  const defaultId = funnels.find((f) => f.is_default)?.id
  // Funnels may arrive after mount: fall back to the default funnel
  useEffect(() => {
    if (!funnelId && defaultId) setFunnelId(defaultId)
  }, [funnelId, defaultId])
  const messages = useQuery({
    queryKey: [...MESSAGES_KEY, funnelId || 'default'],
    queryFn: () => funnelApi.messages(funnelId || undefined),
    enabled: kind === 'sales',
  })
  const list = [...(messages.data ?? [])].sort((a, b) => a.sort_order - b.sort_order)
  const firstId = list[0]?.id

  // Preselect the first sales message (or drop a selection that is not in this funnel)
  useEffect(() => {
    if (kind !== 'sales' || !messages.data) return
    if (!messageId || !messages.data.some((m) => m.id === messageId)) setMessageId(firstId ?? '')
  }, [kind, messageId, firstId, messages.data])

  const chatOk = /^-?\d{3,20}$/.test(chatId.trim())
  const valid = chatOk && (kind !== 'sales' || Boolean(messageId))

  const send = useMutation({
    mutationFn: () => funnelApi.testMessage({
      tg_chat_id: chatId.trim(),
      kind,
      ...(kind === 'sales' ? { message_id: messageId } : {}),
    }),
    onSuccess: (r) => {
      setResult(r)
      if (r.sent) toast.success('Test xabar yuborildi')
      else toast.error(r.error || 'Yuborilmadi')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <Card>
      <CardHeader title="Test xabar" subtitle="Shablon Telegram'da qanday ko'rinishini tekshirish" />
      <div className="space-y-4 px-5 py-4">
        <div>
          <Label>Telegram chat ID</Label>
          <Input value={chatId} inputMode="numeric" onChange={(e) => setChatId(e.target.value)} placeholder="Masalan: 123456789" />
          <p className="mt-1 text-xs text-gray-500">O'z chat ID'ingizni bilish uchun botga /id yozing. Avval botni ishga tushirgan bo'lishingiz kerak.</p>
          {chatId.trim() && !chatOk && <p className="mt-1 text-xs text-red-600">Faqat raqamlar (guruh uchun «-» bilan boshlanadi).</p>}
        </div>
        <div>
          <Label>Qaysi xabar</Label>
          <Select value={kind} onChange={(e) => { setKind(e.target.value as TestMessageKind); setResult(undefined) }}>
            {(Object.keys(KIND_LABELS) as TestMessageKind[]).map((k) => <option key={k} value={k}>{KIND_LABELS[k]}</option>)}
          </Select>
        </div>
        {kind === 'sales' && funnels.length > 1 && (
          <div>
            <Label>Voronka</Label>
            <Select value={funnelId} onChange={(e) => { setFunnelId(e.target.value); setMessageId('') }}>
              {funnels.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </Select>
          </div>
        )}
        {kind === 'sales' && (
          <div>
            <Label>Sotuv xabari</Label>
            {messages.isLoading ? (
              <p className="text-xs text-gray-500">Yuklanmoqda...</p>
            ) : messages.isError ? (
              <p className="text-xs text-red-600">Xabarlar ro'yxatini yuklab bo'lmadi</p>
            ) : list.length === 0 ? (
              <p className="text-xs text-gray-500">Bu voronkada hali sotuv xabari yo'q — «Xabarlar» bo'limida qo'shing.</p>
            ) : (
              <Select value={messageId} onChange={(e) => setMessageId(e.target.value)}>
                {list.map((m, i) => (
                  <option key={m.id} value={m.id}>{i + 1}. {m.text.slice(0, 60)}{m.text.length > 60 ? '…' : ''}</option>
                ))}
              </Select>
            )}
          </div>
        )}
        {result && (
          <p className={result.sent ? 'flex items-center gap-1.5 text-sm text-emerald-700' : 'flex items-center gap-1.5 text-sm text-red-700'}>
            {result.sent ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <XCircle className="h-4 w-4 shrink-0" />}
            {result.sent ? 'Yuborildi — Telegramni tekshiring' : result.error || 'Yuborilmadi'}
          </p>
        )}
        <Button className="w-full" icon={<Send className="h-4 w-4" />} disabled={!valid} loading={send.isPending} onClick={() => send.mutate()}>
          Yuborish
        </Button>
      </div>
    </Card>
  )
}

// --- Tab ------------------------------------------------------------------------------

/** "Umumiy sozlamalar": settings shared by every funnel (SPEC 11.5). */
export function GlobalSettingsTab({ funnel, funnels }: FunnelTabProps) {
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get })
  const dirtyGroups = useRef(new Set<string>())
  const onDirty = useCallback((id: string, dirty: boolean) => {
    if (dirty) dirtyGroups.current.add(id)
    else dirtyGroups.current.delete(id)
  }, [])
  // Warn before closing/reloading the browser tab with unsaved changes
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirtyGroups.current.size) e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  const funnelGroup = data?.groups.find((g) => g.id === 'funnel')
  // Memoized: GroupCard re-syncs its draft whenever `group.items` changes identity
  const shared = useMemo(
    () => (funnelGroup ? { ...funnelGroup, items: funnelGroup.items.filter((i) => !PER_FUNNEL_KEYS.has(i.key)) } : undefined),
    [funnelGroup],
  )
  const gsheet = data?.groups.find((g) => g.id === 'gsheet')

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="min-w-0 space-y-6">
        {isLoading && <Card><Loading /></Card>}
        {isError && <Card><ErrorState error={error} onRetry={() => refetch()} /></Card>}
        {data && !shared && !gsheet && (
          <Card>
            <Empty
              icon={<Settings2 className="h-6 w-6" />}
              title="Voronka sozlamalari topilmadi"
              text="Server hali yangilanmagan bo'lishi mumkin. Administrator bilan bog'laning."
            />
          </Card>
        )}
        {shared && <GroupCard group={shared} sections={FUNNEL_SECTIONS} onDirty={onDirty} />}
        {gsheet && <GroupCard group={gsheet} extras={<SheetExtras />} onDirty={onDirty} />}
      </div>
      <div className="space-y-6 lg:sticky lg:top-6 lg:self-start">
        <Card className="flex gap-3 p-4 text-sm text-gray-600">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
          <p>
            Bu sozlamalar barcha voronkalar uchun umumiy. Kalit so'zlar, matnlar, qo'llanma (PDF) va
            sotuv xabarlari har bir voronkaning o'z «Sozlamalar» va «Xabarlar» bo'limida.
          </p>
        </Card>
        <TestMessageCard funnels={funnels} initialFunnelId={funnel?.id} />
      </div>
    </div>
  )
}
