import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { AlertTriangle, ArrowDown, ArrowUp, Clock, ImagePlus, MessageSquareText, Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import { funnelApi } from '@/api/funnel'
import { errorMessage } from '@/api/client'
import type { FunnelMessageInput, FunnelMessageOut } from '@/api/types'
import { Badge, Button, Card, CardHeader, Empty, Input, Label, Loading, Modal, Select, Textarea, Toggle } from '@/components/ui'
import { AuthImage } from '@/components/AuthImage'
import { fmtMinutes } from '@/lib/format'
import { ErrorState } from './shared'

const MESSAGES_KEY = ['funnel', 'messages'] as const
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

interface FormState {
  text: string
  amount: string
  unit: DelayUnit
  is_active: boolean
}

function MessageModal({ message, open, onClose }: { message: FunnelMessageOut | null; open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<FormState>({ text: '', amount: '1', unit: 'days', is_active: true })
  useEffect(() => {
    if (!open) return
    setForm(message
      ? { text: message.text, ...splitDelay(message.delay_minutes), is_active: message.is_active }
      : { text: '', amount: '1', unit: 'days', is_active: true })
  }, [open, message])

  const amount = Number(form.amount)
  const amountOk = form.amount.trim() !== '' && Number.isInteger(amount) && amount >= 0
  const delayMinutes = amountOk ? amount * UNIT_MINUTES[form.unit] : 0
  const valid = amountOk && form.text.trim().length > 0

  const save = useMutation({
    mutationFn: () => {
      const body: FunnelMessageInput = { text: form.text.trim(), delay_minutes: delayMinutes, is_active: form.is_active }
      return message ? funnelApi.updateMessage(message.id, body) : funnelApi.createMessage(body)
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
      <div className="space-y-4">
        <div>
          <Label hint={`${form.text.length} / 4096`}>Xabar matni</Label>
          <Textarea
            rows={8}
            maxLength={4096}
            value={form.text}
            onChange={(e) => setForm({ ...form, text: e.target.value })}
            placeholder={"Farzandingiz uchun bepul suhbat — o'qituvchimiz bilan tanishing va darajasini bilib oling.\nQulay vaqtni tanlang 👇"}
          />
          <p className="mt-1 text-xs text-gray-500">Xabar ostida har doim «📝 Suhbatga ro'yxatdan o'tish» tugmasi bo'ladi.</p>
        </div>
        <div>
          <Label>Qachon yuboriladi</Label>
          <div className="flex items-center gap-2">
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
            <span className="text-sm text-gray-600">qo'llanma yuborilgandan keyin</span>
          </div>
          {amountOk ? (
            <p className="mt-1 text-xs text-gray-500">= {delayMinutes} daqiqa. Tungi vaqtga to'g'ri kelsa, ertalab 09:00 dan keyin yuboriladi.</p>
          ) : (
            <p className="mt-1 text-xs text-red-600">Butun son kiriting (0 yoki undan katta).</p>
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

export function MessagesTab() {
  const qc = useQueryClient()
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: MESSAGES_KEY, queryFn: funnelApi.messages })
  const [editing, setEditing] = useState<FunnelMessageOut | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  const items = [...(data ?? [])].sort((a, b) => a.sort_order - b.sort_order)
  const active = items.filter((m) => m.is_active)
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
    mutationFn: (ids: string[]) => funnelApi.reorderMessages(ids),
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
          title="Sotuv xabarlari"
          subtitle="Qo'llanma (PDF) olgan mijozga belgilangan vaqtda ketma-ket yuboriladi — faqat 09:00–21:00 oralig'ida. Mijoz suhbatga yozilsa yoki botni to'xtatsa, yuborish to'xtaydi."
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
                <li key={m.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start">
                  <div className="flex shrink-0 items-center gap-1 sm:flex-col">
                    <button type="button" aria-label="Yuqoriga" disabled={i === 0 || reorder.isPending} onClick={() => move(i, -1)} className="rounded p-1 text-gray-400 hover:bg-gray-100 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
                    <span className="w-6 text-center text-xs font-semibold text-gray-400">{i + 1}</span>
                    <button type="button" aria-label="Pastga" disabled={i === items.length - 1 || reorder.isPending} onClick={() => move(i, 1)} className="rounded p-1 text-gray-400 hover:bg-gray-100 disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
                  </div>
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className="bg-brand-50 text-brand-700 ring-brand-200">
                        <Clock className="h-3 w-3" />
                        {m.delay_minutes > 0 ? `${fmtMinutes(m.delay_minutes)}dan keyin` : 'Darhol'}
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
      <MessageModal message={editing} open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  )
}
