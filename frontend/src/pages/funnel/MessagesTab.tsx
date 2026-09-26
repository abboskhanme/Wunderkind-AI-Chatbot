import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { AlertTriangle, ArrowDown, ArrowUp, Clock, CornerDownRight, ImagePlus, Link2, MessageSquareText, MousePointerClick, Pencil, Plus, Save, Send, Trash2, X } from 'lucide-react'
import { funnelApi } from '@/api/funnel'
import { errorMessage } from '@/api/client'
import type { FunnelMessageInput, FunnelMessageOut, FunnelOut, MessageCondition } from '@/api/types'
import { Badge, Button, Card, CardHeader, Empty, Input, Label, Loading, Modal, Select, Textarea, Toggle } from '@/components/ui'
import { AuthImage } from '@/components/AuthImage'
import { cn } from '@/lib/cn'
import { fmtMinutes } from '@/lib/format'
import { ErrorState, type FunnelTabProps } from './shared'

/** Prefix of every funnel's message list query: `[...MESSAGES_KEY, funnelId]`. */
export const MESSAGES_KEY = ['funnel', 'messages'] as const
const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']

type DelayUnit = 'minutes' | 'hours' | 'days'

const UNIT_MINUTES: Record<DelayUnit, number> = { minutes: 1, hours: 60, days: 1440 }
const UNIT_LABELS: Record<DelayUnit, string> = { minutes: 'daqiqa', hours: 'soat', days: 'kun' }

/** Largest unit that represents the stored minutes exactly (1440 → 1 kun, 90 → 90 daqiqa). */
function splitDelay(minutes: number): { amount: string; unit: DelayUnit } {
  if (minutes > 0 && minutes % 1440 === 0) return { amount: String(minutes / 1440), unit: 'days' }
  if (minutes > 0 && minutes % 60 === 0) return { amount: String(minutes / 60), unit: 'hours' }
  return { amount: String(minutes), unit: 'minutes' }
}

/*
 * The image URL is the same after a replacement, and the server may let the browser
 * cache it. Each page load gets a fresh version; an upload bumps that message's version.
 * Module scope so the version survives switching tabs.
 */
const PAGE_LOAD_VERSION = Date.now()
const imageVersions = new Map<string, number>()
const imageVersion = (id: string) => imageVersions.get(id) ?? PAGE_LOAD_VERSION

const MAX_BUTTONS = 8
const URL_RE = /^https?:\/\/\S+$/i

interface ButtonDraft {
  /** React key; stays the same while the row is edited */
  key: string
  /** Saved button id (keeps its clicks) */
  id?: string
  text: string
  url: string
}

interface FormState {
  text: string
  amount: string
  unit: DelayUnit
  is_active: boolean
  buttons: ButtonDraft[]
  show_book_button: boolean
  condition: MessageCondition
  /** "<message id>:<button id>" — empty button id = any button of that message */
  source: string
}

let draftSeq = 0
const newKey = () => `b${++draftSeq}`

const CONDITION_LABELS: Record<MessageCondition, string> = {
  none: 'Hammaga',
  clicked: 'Tugmani bosganlarga',
  not_clicked: 'Tugmani bosmaganlarga',
}

const DELAY_AFTER: Record<MessageCondition, string> = {
  none: "qo'llanma yuborilgandan keyin",
  clicked: 'tugma bosilgandan keyin',
  not_clicked: "o'sha xabar yuborilgandan keyin",
}

function emptyForm(): FormState {
  return { text: '', amount: '1', unit: 'days', is_active: true, buttons: [], show_book_button: true, condition: 'none', source: '' }
}

function formOf(m: FunnelMessageOut): FormState {
  return {
    text: m.text,
    ...splitDelay(m.delay_minutes),
    is_active: m.is_active,
    buttons: m.buttons.map((b) => ({ key: newKey(), id: b.id, text: b.text, url: b.url ?? '' })),
    show_book_button: m.show_book_button,
    condition: m.condition,
    source: m.condition_message_id ? `${m.condition_message_id}:${m.condition_button_id ?? ''}` : '',
  }
}

/** "2-xabar" — position in the list, as the admin sees it. */
function positionLabel(messages: FunnelMessageOut[], id: string | null): string {
  const i = messages.findIndex((m) => m.id === id)
  return i >= 0 ? `${i + 1}-xabar` : "o'chirilgan xabar"
}

/** Short description of whom a conditional message goes to, e.g. «Ha» (2-xabar). */
function sourceLabel(messages: FunnelMessageOut[], m: FunnelMessageOut): string {
  const source = messages.find((x) => x.id === m.condition_message_id)
  const button = source?.buttons.find((b) => b.id === m.condition_button_id)
  const where = positionLabel(messages, m.condition_message_id)
  return button ? `«${button.text}» (${where})` : `${where} tugmalaridan birini`
}

function MessageModal({ funnelId, message, messages, open, onClose }: {
  funnelId: string
  message: FunnelMessageOut | null
  messages: FunnelMessageOut[]
  open: boolean
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState<FormState>(emptyForm)
  useEffect(() => {
    if (!open) return
    setForm(message ? formOf(message) : emptyForm())
  }, [open, message])

  // Messages whose buttons this one may follow (not itself)
  const sources = messages.filter((m) => m.id !== message?.id && m.buttons.length > 0)

  const amount = Number(form.amount)
  const amountOk = form.amount.trim() !== '' && Number.isInteger(amount) && amount >= 0
  const delayMinutes = amountOk ? amount * UNIT_MINUTES[form.unit] : 0
  const buttonsOk = form.buttons.every((b) => b.text.trim() !== '' && (b.url.trim() === '' || URL_RE.test(b.url.trim())))
  const sourceOk = form.condition === 'none' || form.source !== ''
  const waitOk = form.condition !== 'not_clicked' || delayMinutes >= 1
  const valid = amountOk && form.text.trim().length > 0 && buttonsOk && sourceOk && waitOk

  function setCondition(condition: MessageCondition) {
    // Sensible delay for a new message: right after the click / a day to decide
    const delay = message ? {} : condition === 'clicked' ? { amount: '0', unit: 'minutes' as DelayUnit } : { amount: '1', unit: 'days' as DelayUnit }
    setForm({ ...form, condition, ...delay, source: condition === 'none' ? '' : form.source })
  }

  function setButton(key: string, patch: Partial<ButtonDraft>) {
    setForm({ ...form, buttons: form.buttons.map((b) => (b.key === key ? { ...b, ...patch } : b)) })
  }

  function moveButton(index: number, dir: -1 | 1) {
    const list = [...form.buttons]
    const j = index + dir
    if (j < 0 || j >= list.length) return
    ;[list[index], list[j]] = [list[j], list[index]]
    setForm({ ...form, buttons: list })
  }

  const save = useMutation({
    mutationFn: () => {
      const [sourceId, buttonId] = form.source.split(':')
      const body: FunnelMessageInput = {
        text: form.text.trim(),
        delay_minutes: delayMinutes,
        is_active: form.is_active,
        buttons: form.buttons.map((b) => ({ id: b.id, text: b.text.trim(), url: b.url.trim() || null })),
        show_book_button: form.show_book_button,
        condition: form.condition,
        condition_message_id: form.condition === 'none' ? null : sourceId || null,
        condition_button_id: form.condition === 'none' ? null : buttonId || null,
      }
      return message ? funnelApi.updateMessage(message.id, body) : funnelApi.createMessage(body, funnelId)
    },
    onSuccess: () => {
      toast.success('Saqlandi')
      qc.invalidateQueries({ queryKey: MESSAGES_KEY })
      onClose()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={message ? 'Xabarni tahrirlash' : 'Yangi xabar'}
      wide
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Bekor qilish</Button>
          <Button icon={<Save className="h-4 w-4" />} disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>Saqlash</Button>
        </>
      }
    >
      <div className="space-y-5">
        <div>
          <Label>Kimga yuboriladi</Label>
          <div className="grid gap-2 sm:grid-cols-2">
            <Select aria-label="Kimga yuboriladi" value={form.condition} onChange={(e) => setCondition(e.target.value as MessageCondition)}>
              {(Object.keys(CONDITION_LABELS) as MessageCondition[]).map((c) => (
                <option key={c} value={c} disabled={c !== 'none' && sources.length === 0}>{CONDITION_LABELS[c]}</option>
              ))}
            </Select>
            {form.condition !== 'none' && (
              <Select aria-label="Qaysi tugma" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
                <option value="">— Tugmani tanlang —</option>
                {sources.map((m) => (
                  <optgroup key={m.id} label={`${positionLabel(messages, m.id)}: ${m.text.slice(0, 40)}`}>
                    {m.buttons.map((b) => <option key={b.id} value={`${m.id}:${b.id}`}>«{b.text}»</option>)}
                    {m.buttons.length > 1 && <option value={`${m.id}:`}>Istalgan tugmasi</option>}
                  </optgroup>
                ))}
              </Select>
            )}
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {form.condition === 'none' && (sources.length === 0
              ? "Tugmali xabar qo'shsangiz, bosgan va bosmaganlarga alohida xabar yuborish mumkin bo'ladi."
              : "Qo'llanma olgan hammaga yuboriladi.")}
            {form.condition === 'clicked' && 'Faqat shu tugmani bosganlarga yuboriladi.'}
            {form.condition === 'not_clicked' && "O'sha xabarni olgan, lekin belgilangan vaqt ichida tugmani bosmaganlarga yuboriladi."}
          </p>
        </div>
        <div>
          <Label hint={`${form.text.length} / 4096`}>Xabar matni</Label>
          <Textarea
            rows={7}
            maxLength={4096}
            value={form.text}
            onChange={(e) => setForm({ ...form, text: e.target.value })}
            placeholder={"Farzandingiz uchun bepul suhbat — maktabimiz bilan tanishing va savollaringizga javob oling.\nQulay vaqtni tanlang 👇"}
          />
        </div>
        <div>
          <Label hint={`${form.buttons.length} / ${MAX_BUTTONS}`}>Tugmalar</Label>
          {form.buttons.length > 0 && (
            <ul className="mb-2 space-y-2">
              {form.buttons.map((b, i) => {
                const badUrl = b.url.trim() !== '' && !URL_RE.test(b.url.trim())
                return (
                  <li key={b.key} className="flex flex-col gap-2 rounded-lg bg-gray-50 p-2 ring-1 ring-gray-200 sm:flex-row sm:items-start">
                    <div className="sm:w-48 sm:shrink-0">
                      <Input aria-label="Tugma matni" maxLength={64} placeholder="Tugma matni" value={b.text} onChange={(e) => setButton(b.key, { text: e.target.value })} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <Input aria-label="Havola" maxLength={1024} placeholder="https://... (ixtiyoriy)" value={b.url} onChange={(e) => setButton(b.key, { url: e.target.value })} />
                      {badUrl && <p className="mt-1 text-xs text-red-600">Havola http:// yoki https:// bilan boshlansin.</p>}
                    </div>
                    <div className="flex shrink-0 items-center gap-1 self-end sm:self-center">
                      <button type="button" aria-label="Yuqoriga" disabled={i === 0} onClick={() => moveButton(i, -1)} className="rounded p-1 text-gray-400 hover:bg-gray-200 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
                      <button type="button" aria-label="Pastga" disabled={i === form.buttons.length - 1} onClick={() => moveButton(i, 1)} className="rounded p-1 text-gray-400 hover:bg-gray-200 disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
                      <button type="button" aria-label="Tugmani o'chirish" onClick={() => setForm({ ...form, buttons: form.buttons.filter((x) => x.key !== b.key) })} className="rounded p-1 text-red-500 hover:bg-red-50"><X className="h-4 w-4" /></button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus className="h-4 w-4" />}
            disabled={form.buttons.length >= MAX_BUTTONS}
            onClick={() => setForm({ ...form, buttons: [...form.buttons, { key: newKey(), text: '', url: '' }] })}
          >
            Tugma qo'shish
          </Button>
          <p className="mt-1 text-xs text-gray-500">
            Havolasiz tugmani bosganini bot yozib oladi. Havolali tugma saytni ochadi — bosgani ham hisoblanadi.
            Bosgan va bosmaganlarga keyingi xabarni «Kimga yuboriladi» orqali ulang.
          </p>
          <label className="mt-3 flex items-center gap-3">
            <Toggle checked={form.show_book_button} onChange={(v) => setForm({ ...form, show_book_button: v })} />
            <span className="text-sm text-gray-700">«📝 Suhbatga yozilish» tugmasi ham bo'lsin</span>
          </label>
        </div>
        <div>
          <Label>Qachon yuboriladi</Label>
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-24 shrink-0">
              <Input
                type="number"
                min={0}
                step={1}
                aria-label="Kechikish"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
              />
            </div>
            <div className="w-28 shrink-0">
              <Select aria-label="Birlik" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value as DelayUnit })}>
                {(Object.keys(UNIT_LABELS) as DelayUnit[]).map((u) => <option key={u} value={u}>{UNIT_LABELS[u]}</option>)}
              </Select>
            </div>
            <span className="text-sm text-gray-600">{DELAY_AFTER[form.condition]}</span>
          </div>
          {!amountOk ? (
            <p className="mt-1 text-xs text-red-600">Butun son kiriting (0 yoki undan katta).</p>
          ) : !waitOk ? (
            <p className="mt-1 text-xs text-red-600">Bosmaganlar uchun kutish vaqtini kiriting (masalan, 1 kun) — shuncha vaqtda bosmaganlarga boradi.</p>
          ) : form.condition === 'clicked' && delayMinutes === 0 ? (
            <p className="mt-1 text-xs text-gray-500">Tugma bosilishi bilan darhol yuboriladi (tunda ham).</p>
          ) : (
            <p className="mt-1 text-xs text-gray-500">= {delayMinutes} daqiqa. Tungi vaqtga to'g'ri kelsa, ertalab 09:00 dan keyin yuboriladi.</p>
          )}
        </div>
        <label className="flex items-center gap-3">
          <Toggle checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} />
          <span className="text-sm text-gray-700">Faol (mijozlarga yuboriladi)</span>
        </label>
      </div>
    </Modal>
  )
}

function MessageImage({ message }: { message: FunnelMessageOut }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: (file: File) => funnelApi.uploadMessageImage(message.id, file),
    onSuccess: () => {
      imageVersions.set(message.id, Date.now())
      toast.success('Rasm saqlandi')
      qc.invalidateQueries({ queryKey: MESSAGES_KEY })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: () => funnelApi.removeMessageImage(message.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: MESSAGES_KEY }),
    onError: (e) => toast.error(errorMessage(e)),
  })
  const version = imageVersion(message.id)

  return (
    <div className="flex items-center gap-2">
      {message.has_image ? (
        <div className="group relative h-20 w-20 overflow-hidden rounded-lg ring-1 ring-gray-200">
          <AuthImage
            key={version}
            imageId={message.id}
            load={(id) => funnelApi.messageImageBlob(id, version)}
            className="h-full w-full object-cover"
          />
          <button
            type="button"
            onClick={() => { if (window.confirm("Rasm o'chirilsinmi?")) remove.mutate() }}
            disabled={remove.isPending}
            className="absolute right-0.5 top-0.5 rounded-full bg-white/90 p-0.5 text-red-600 shadow sm:hidden sm:group-hover:block"
            title="Rasmni o'chirish"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={upload.isPending}
        className="flex h-20 w-20 flex-col items-center justify-center gap-0.5 rounded-lg border-2 border-dashed border-gray-300 text-gray-400 hover:border-brand-400 hover:text-brand-600"
      >
        <ImagePlus className="h-5 w-5" />
        <span className="text-[10px]">{upload.isPending ? 'Yuklanmoqda...' : message.has_image ? 'Almashtirish' : 'Rasm'}</span>
      </button>
      <input
        ref={input}
        type="file"
        accept={IMAGE_TYPES.join(',')}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (!file) return
          if (!IMAGE_TYPES.includes(file.type)) toast.error('Faqat JPG, PNG yoki WEBP rasm')
          else if (file.size > MAX_IMAGE_BYTES) toast.error(`${file.name}: 5 MB dan katta`)
          else upload.mutate(file)
        }}
      />
    </div>
  )
}

function delayLabel(m: FunnelMessageOut): string {
  if (m.condition === 'clicked') return m.delay_minutes > 0 ? `Bosgandan ${fmtMinutes(m.delay_minutes)} keyin` : 'Bosishi bilan darhol'
  if (m.condition === 'not_clicked') return `${fmtMinutes(m.delay_minutes)} ichida bosmasa`
  return m.delay_minutes > 0 ? `${fmtMinutes(m.delay_minutes)}dan keyin` : 'Darhol'
}

/** The message's buttons as Telegram shows them, with how many pressed each. */
function MessageButtons({ message }: { message: FunnelMessageOut }) {
  if (message.buttons.length === 0 && !message.show_book_button) return null
  const pct = (n: number) => (message.sent_count > 0 ? ` (${Math.round((n / message.sent_count) * 100)}%)` : '')
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {message.buttons.map((b) => (
          <span key={b.id} className="inline-flex max-w-full items-center gap-1 rounded-md bg-white px-2 py-1 text-xs text-gray-700 ring-1 ring-gray-300" title={b.url ?? undefined}>
            {b.url ? <Link2 className="h-3 w-3 shrink-0 text-gray-400" /> : <MousePointerClick className="h-3 w-3 shrink-0 text-gray-400" />}
            <span className="truncate">{b.text}</span>
            <span className="shrink-0 font-semibold text-brand-700">· {b.clicks}{pct(b.clicks)}</span>
          </span>
        ))}
        {message.show_book_button && (
          <span className="inline-flex items-center rounded-md bg-gray-50 px-2 py-1 text-xs text-gray-500 ring-1 ring-gray-200">📝 Suhbatga yozilish</span>
        )}
      </div>
      <p className="flex items-center gap-1 text-xs text-gray-500">
        <Send className="h-3 w-3" /> Yuborildi: {message.sent_count}
      </p>
    </div>
  )
}

export function MessagesTab({ funnel }: FunnelTabProps) {
  // Only offered for a concrete funnel (not "Hammasi")
  if (!funnel) return null
  return <FunnelMessages key={funnel.id} funnel={funnel} />
}

function FunnelMessages({ funnel }: { funnel: FunnelOut }) {
  const qc = useQueryClient()
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: [...MESSAGES_KEY, funnel.id],
    queryFn: () => funnelApi.messages(funnel.id),
  })
  const [editing, setEditing] = useState<FunnelMessageOut | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  const items = [...(data ?? [])].sort((a, b) => a.sort_order - b.sort_order)
  // Only messages timed from the PDF follow one timeline; conditional ones have their own
  const active = items.filter((m) => m.is_active && m.condition === 'none')
  const outOfOrder = active.some((m, i) => i > 0 && m.delay_minutes < active[i - 1].delay_minutes)

  const toggle = useMutation({
    mutationFn: (m: FunnelMessageOut) => funnelApi.updateMessage(m.id, { is_active: !m.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: MESSAGES_KEY }),
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id: string) => funnelApi.removeMessage(id),
    onSuccess: () => {
      toast.success("Xabar o'chirildi")
      qc.invalidateQueries({ queryKey: MESSAGES_KEY })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const reorder = useMutation({
    mutationFn: (ids: string[]) => funnelApi.reorderMessages(ids, funnel.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: MESSAGES_KEY }),
    onError: (e) => toast.error(errorMessage(e)),
  })

  function move(index: number, dir: -1 | 1) {
    const ids = items.map((m) => m.id)
    const j = index + dir
    if (j < 0 || j >= ids.length) return
    ;[ids[index], ids[j]] = [ids[j], ids[index]]
    reorder.mutate(ids)
  }

  function openNew() {
    setEditing(null)
    setModalOpen(true)
  }

  return (
    <>
      <Card>
        <CardHeader
          title={`Sotuv xabarlari — «${funnel.name}»`}
          subtitle="Qo'llanma (PDF) olgan mijozga belgilangan vaqtda ketma-ket yuboriladi — faqat 09:00–21:00 oralig'ida. Xabarga tugma qo'shib, bosgan va bosmaganlarga alohida xabar yuborish mumkin. Mijoz suhbatga yozilsa yoki botni to'xtatsa, yuborish to'xtaydi."
          action={<Button size="sm" className="shrink-0 whitespace-nowrap" icon={<Plus className="h-4 w-4" />} onClick={openNew}>Xabar qo'shish</Button>}
        />
        {isLoading && <Loading />}
        {isError && <ErrorState error={error} onRetry={() => refetch()} />}
        {data && items.length === 0 && (
          <Empty
            icon={<MessageSquareText className="h-6 w-6" />}
            title="Hali sotuv xabari yo'q"
            text="Masalan: 10 daqiqadan keyin — bepul suhbat taklifi, 1 kundan keyin — natijalar va sharhlar, 2 kundan keyin — joylar soni cheklangani haqida."
            action={<Button icon={<Plus className="h-4 w-4" />} onClick={openNew}>Xabar qo'shish</Button>}
          />
        )}
        {items.length > 0 && (
          <>
            {outOfOrder && (
              <div className="flex items-start gap-2 border-b border-amber-100 bg-amber-50 px-5 py-2.5 text-xs text-amber-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                Xabarlar tartib bo'yicha emas, vaqti bo'yicha yuboriladi: kechikishi kichikroq bo'lgan xabar ro'yxatda pastda tursa ham birinchi ketadi.
              </div>
            )}
            <ul className="divide-y divide-gray-100">
              {items.map((m, i) => (
                <li key={m.id} className={cn('flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start', m.condition !== 'none' && 'bg-slate-50/60')}>
                  <div className="flex shrink-0 items-center gap-1 sm:flex-col">
                    <button type="button" aria-label="Yuqoriga" disabled={i === 0 || reorder.isPending} onClick={() => move(i, -1)} className="rounded p-1 text-gray-400 hover:bg-gray-100 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
                    <span className="w-6 text-center text-xs font-semibold text-gray-400">{i + 1}</span>
                    <button type="button" aria-label="Pastga" disabled={i === items.length - 1 || reorder.isPending} onClick={() => move(i, 1)} className="rounded p-1 text-gray-400 hover:bg-gray-100 disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
                  </div>
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      {m.condition !== 'none' && (
                        <Badge className={m.condition === 'clicked' ? 'bg-emerald-50 text-emerald-700 ring-emerald-200' : 'bg-orange-50 text-orange-700 ring-orange-200'}>
                          <CornerDownRight className="h-3 w-3" />
                          {sourceLabel(items, m)} {m.condition === 'clicked' ? 'bosganlarga' : 'bosmaganlarga'}
                        </Badge>
                      )}
                      <Badge className="bg-brand-50 text-brand-700 ring-brand-200">
                        <Clock className="h-3 w-3" />
                        {delayLabel(m)}
                      </Badge>
                      {!m.is_active && <Badge>Nofaol</Badge>}
                      {/\[(raqam|imtiyoz)[^\]]*\]/.test(m.text) && (
                        <Badge className="bg-amber-50 text-amber-800 ring-amber-200">
                          <AlertTriangle className="h-3 w-3" />
                          [raqam] to'ldirilmagan — yuborilmaydi
                        </Badge>
                      )}
                    </div>
                    <p className="line-clamp-4 whitespace-pre-wrap text-sm text-gray-700">{m.text}</p>
                    <MessageButtons message={m} />
                    <MessageImage message={m} />
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Toggle checked={m.is_active} disabled={toggle.isPending} onChange={() => toggle.mutate(m)} />
                    <Button variant="ghost" size="sm" icon={<Pencil className="h-4 w-4" />} onClick={() => { setEditing(m); setModalOpen(true) }}>Tahrirlash</Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="O'chirish"
                      className="text-red-600 hover:bg-red-50"
                      icon={<Trash2 className="h-4 w-4" />}
                      onClick={() => { if (window.confirm(`${i + 1}-xabar o'chirilsinmi?`)) remove.mutate(m.id) }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
      <MessageModal funnelId={funnel.id} message={editing} messages={items} open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  )
}
