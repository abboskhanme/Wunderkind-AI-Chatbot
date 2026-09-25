import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import toast from 'react-hot-toast'
import { ChevronLeft, ChevronRight, Download, FileText, Link2, RotateCcw, Save, Trash2, Upload } from 'lucide-react'
import { settingsApi } from '@/api/settings'
import { funnelApi, FUNNEL_TEXT_KEYS, leadMagnetDownloadUrl } from '@/api/funnel'
import { downloadFile, errorMessage } from '@/api/client'
import type { FunnelOut, FunnelPatch, SettingItem } from '@/api/types'
import { Badge, Button, Card, CardHeader, Empty, Input, Label, Loading, Textarea, Toggle } from '@/components/ui'
import { fmtBytes, fmtDateTime } from '@/lib/format'
import { CopyRow, ErrorState, FUNNELS_KEY, type FunnelTabProps } from './shared'

const MAX_PDF_BYTES = 20 * 1024 * 1024
export const SLUG_RE = /^[a-z0-9_]{1,32}$/

interface MainForm {
  name: string
  slug: string
  is_active: boolean
  keywords: string
  ig_media_ids: string
}

function toForm(f: FunnelOut): MainForm {
  return {
    name: f.name,
    slug: f.slug,
    is_active: f.is_active,
    keywords: f.keywords ?? '',
    ig_media_ids: f.ig_media_ids ?? '',
  }
}

/** Fields the user has not touched adopt fresh server values; edits survive a refetch. */
function mergeForm<T extends object>(before: T, after: T, form: T): T {
  const out = { ...after }
  for (const k of Object.keys(after) as (keyof T)[]) {
    if (form[k] !== before[k]) out[k] = form[k]
  }
  return out
}

/** Keeps a form in sync with server data without losing unsaved edits. */
function useSyncedForm<T extends object>(base: T): [T, (fn: (f: T) => T) => void] {
  const [form, setForm] = useState<T>(base)
  const prev = useRef(base)
  const serialized = JSON.stringify(base)
  useEffect(() => {
    const before = prev.current
    if (JSON.stringify(before) === serialized) return
    const next = JSON.parse(serialized) as T
    setForm((f) => mergeForm(before, next, f))
    prev.current = next
  }, [serialized])
  return [form, setForm]
}

// --- Name, slug, active, keywords, post filter, order, delete -------------------------

function MainCard({ funnel, funnels, globalKeywords, selectFunnel }: {
  funnel: FunnelOut
  funnels: FunnelOut[]
  globalKeywords: string | undefined
  selectFunnel: (id: string | null) => void
}) {
  const qc = useQueryClient()
  const base = toForm(funnel)
  const [form, setForm] = useSyncedForm(base)

  const patch: FunnelPatch = {}
  if (form.name.trim() !== base.name) patch.name = form.name.trim()
  if (form.slug.trim() !== base.slug) patch.slug = form.slug.trim()
  if (form.is_active !== base.is_active) patch.is_active = form.is_active
  if (form.keywords.trim() !== base.keywords.trim()) patch.keywords = form.keywords.trim()
  if (form.ig_media_ids.trim() !== base.ig_media_ids.trim()) patch.ig_media_ids = form.ig_media_ids.trim()
  const dirty = Object.keys(patch).length > 0
  const nameOk = form.name.trim().length > 0 && form.name.trim().length <= 120
  const slugOk = SLUG_RE.test(form.slug.trim())

  const save = useMutation({
    mutationFn: () => funnelApi.updateFunnel(funnel.id, patch),
    onSuccess: () => {
      toast.success('Saqlandi')
      qc.invalidateQueries({ queryKey: FUNNELS_KEY })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const sorted = [...funnels].sort((a, b) => a.sort_order - b.sort_order)
  const index = sorted.findIndex((f) => f.id === funnel.id)
  const reorder = useMutation({
    mutationFn: (ids: string[]) => funnelApi.reorderFunnels(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: FUNNELS_KEY }),
    onError: (e) => toast.error(errorMessage(e)),
  })
  function move(dir: -1 | 1) {
    const ids = sorted.map((f) => f.id)
    const j = index + dir
    if (index < 0 || j < 0 || j >= ids.length) return
    ;[ids[index], ids[j]] = [ids[j], ids[index]]
    reorder.mutate(ids)
  }

  const archive = useMutation({
    mutationFn: () => funnelApi.updateFunnel(funnel.id, { is_active: false }),
    onSuccess: () => {
      toast.success('Voronka arxivlandi (nofaol)')
      qc.invalidateQueries({ queryKey: FUNNELS_KEY })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: () => funnelApi.removeFunnel(funnel.id),
    onSuccess: () => {
      toast.success("Voronka o'chirildi")
      selectFunnel(null)
      qc.invalidateQueries({ queryKey: FUNNELS_KEY })
    },
    onError: (e) => {
      if (axios.isAxiosError(e) && e.response?.status === 409) {
        const why = errorMessage(e, "Voronkada yozuvlar bor, uni o'chirib bo'lmaydi.")
        if (funnel.is_active && window.confirm(`${why}\n\nO'rniga voronka nofaol qilinsinmi (arxiv)? Yangi odamlar kirmaydi, boshlaganlar oxirigacha o'tadi.`)) {
          archive.mutate()
        } else if (!funnel.is_active) {
          toast.error(why)
        }
        return
      }
      toast.error(errorMessage(e))
    },
  })

  return (
    <Card>
      <CardHeader
        title={dirty ? 'Voronka •' : 'Voronka'}
        subtitle={funnel.is_default ? 'Asosiy voronka: boshqa voronkaga mos kelmagan izoh va oddiy /start shu yerga tushadi' : undefined}
        action={
          <Button size="sm" icon={<Save className="h-3.5 w-3.5" />} disabled={!dirty || !nameOk || !slugOk} loading={save.isPending} onClick={() => save.mutate()}>
            Saqlash
          </Button>
        }
      />
      <div className="space-y-5 px-5 py-5">
        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <Label>Nomi</Label>
            <Input value={form.name} maxLength={120} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Masalan: 1-sinfga qabul" />
            {!nameOk && <p className="mt-1 text-xs text-red-600">Nomini kiriting.</p>}
          </div>
          <div>
            <Label hint="a-z, 0-9, _">Qisqa nom (havola uchun)</Label>
            <Input
              value={form.slug}
              maxLength={32}
              onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value.toLowerCase().replace(/\s+/g, '_') }))}
            />
            {!slugOk && <p className="mt-1 text-xs text-red-600">Faqat kichik lotin harflari, raqam va «_» (32 tagacha).</p>}
            {slugOk && form.slug.trim() !== base.slug && (
              <p className="mt-1 text-xs text-amber-600">O'zgartirilsa, eski Telegram havolalari ishlamay qoladi.</p>
            )}
          </div>
        </div>
        <div>
          <Label hint="vergul bilan">Kalit so'zlar</Label>
          <Input
            value={form.keywords}
            onChange={(e) => setForm((f) => ({ ...f, keywords: e.target.value }))}
            placeholder={funnel.is_default ? globalKeywords || 'wunderkind, вундеркинд' : 'Masalan: qabul, 1-sinf'}
          />
          <p className="mt-1 text-xs text-gray-500">
            {funnel.is_default
              ? `Bo'sh bo'lsa, umumiy kalit so'zlar ishlatiladi${globalKeywords ? `: ${globalKeywords}` : ''}.`
              : "Izoh yoki Direct'da shu so'zlardan biri bo'lsa, odam shu voronkaga tushadi. Bo'sh bo'lsa — faqat havolalar orqali."}
          </p>
        </div>
        <div>
          <Label>Instagram post filtri</Label>
          <Textarea
            rows={2}
            value={form.ig_media_ids}
            onChange={(e) => setForm((f) => ({ ...f, ig_media_ids: e.target.value }))}
            placeholder="Masalan: https://www.instagram.com/p/C8xYz12AbCd/, 17912345678901234"
          />
          <p className="mt-1 text-xs text-gray-500">
            Bo'sh — istalgan post. Post havolasi, qisqa kodi yoki media ID, vergul bilan. Filtrli voronkalar birinchi tekshiriladi.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-gray-100 pt-4">
          <label className="flex items-center gap-3">
            <Toggle
              checked={form.is_active}
              disabled={funnel.is_default}
              onChange={(v) => setForm((f) => ({ ...f, is_active: v }))}
            />
            <span className="text-sm text-gray-700">
              Faol
              <span className="block text-xs text-gray-500">
                {funnel.is_default
                  ? "Asosiy voronkani o'chirib bo'lmaydi (butun tizim: Umumiy sozlamalar → «Voronka yoqilgan»)"
                  : "Nofaol voronkaga yangi odam kirmaydi; boshlaganlar oxirigacha o'tadi"}
              </span>
            </span>
          </label>
          {sorted.length > 1 && index >= 0 && (
            <div className="flex items-center gap-2 text-sm text-gray-600" title="Kalit so'z bir nechta voronkaga mos kelsa, tartibda oldingisi tanlanadi">
              <span>Tekshirish tartibi: {index + 1} / {sorted.length}</span>
              <Button variant="secondary" size="sm" aria-label="Oldinga" disabled={index === 0 || reorder.isPending} onClick={() => move(-1)} icon={<ChevronLeft className="h-4 w-4" />} />
              <Button variant="secondary" size="sm" aria-label="Orqaga" disabled={index === sorted.length - 1 || reorder.isPending} onClick={() => move(1)} icon={<ChevronRight className="h-4 w-4" />} />
            </div>
          )}
        </div>
        {!funnel.is_default && (
          <div className="flex justify-end border-t border-gray-100 pt-4">
            <Button
              variant="ghost"
              size="sm"
              className="text-red-600 hover:bg-red-50"
              icon={<Trash2 className="h-4 w-4" />}
              loading={remove.isPending || archive.isPending}
              onClick={() => { if (window.confirm(`«${funnel.name}» voronkasi o'chirilsinmi?`)) remove.mutate() }}
            >
              Voronkani o'chirish
            </Button>
          </div>
        )}
      </div>
    </Card>
  )
}

// --- Deep links ----------------------------------------------------------------------

function LinksCard({ funnel }: { funnel: FunnelOut }) {
  return (
    <Card>
      <CardHeader title="Havolalar" subtitle="Bosgan odam botga kiradi va shu voronkadan o'tadi" />
      <div className="space-y-4 px-5 py-4">
        <CopyRow label="Telegram kanal uchun" value={funnel.links?.telegram_channel ?? null} hint="Kanal postiga qo'ying (kanalga a'zolik tekshiriladi)." />
        <CopyRow label="Reklama, bio va boshqa joylar uchun" value={funnel.links?.telegram_direct ?? null} hint="To'g'ridan-to'g'ri botga kirish havolasi." />
        <p className="flex items-start gap-2 text-xs text-gray-500">
          <Link2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Instagram'da kalit so'z yozganlarga havola avtomatik yuboriladi.
        </p>
      </div>
    </Card>
  )
}

// --- Lead magnet PDF (one per funnel) --------------------------------------------------

function LeadMagnetCard({ funnel }: { funnel: FunnelOut }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [downloading, setDownloading] = useState(false)
  const key = ['funnel', 'lead-magnet', funnel.id]
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: key,
    queryFn: () => funnelApi.leadMagnet(funnel.id),
  })
  const upload = useMutation({
    mutationFn: (file: File) => funnelApi.uploadLeadMagnet(file, funnel.id),
    onSuccess: () => {
      toast.success("Qo'llanma yuklandi")
      qc.invalidateQueries({ queryKey: key })
      qc.invalidateQueries({ queryKey: FUNNELS_KEY })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  function pick() {
    if (data && !window.confirm("Yangi fayl hozirgisining o'rnini egallaydi. Davom etasizmi?")) return
    input.current?.click()
  }

  async function download() {
    if (!data) return
    setDownloading(true)
    try {
      await downloadFile(leadMagnetDownloadUrl(funnel.id), data.filename)
    } catch {
      toast.error("Yuklab bo'lmadi")
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Card>
      <CardHeader title="Qo'llanma (PDF)" subtitle="Ma'lumot to'ldirgan odamga shu voronka yuboradigan fayl" />
      {isLoading && <Loading />}
      {isError && <ErrorState error={error} onRetry={() => refetch()} />}
      {!isLoading && !isError && data === null && (
        <Empty
          icon={<FileText className="h-6 w-6" />}
          title="Qo'llanma yuklanmagan"
          text="Yuklanmaguncha bot «tez orada yuboramiz» deydi va xodimlarga xabar beradi."
          action={<Button icon={<Upload className="h-4 w-4" />} loading={upload.isPending} onClick={pick}>PDF yuklash</Button>}
        />
      )}
      {data && (
        <div className="space-y-4 px-5 py-4">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-red-50 p-2 text-red-600"><FileText className="h-5 w-5" /></div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-gray-900" title={data.filename}>{data.filename}</p>
              <p className="text-xs text-gray-500">{fmtBytes(data.size_bytes)} · {fmtDateTime(data.updated_at)}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" icon={<Download className="h-3.5 w-3.5" />} loading={downloading} onClick={download}>Yuklab olish</Button>
            <Button variant="secondary" size="sm" icon={<Upload className="h-3.5 w-3.5" />} loading={upload.isPending} onClick={pick}>Almashtirish</Button>
          </div>
        </div>
      )}
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (!file) return
          const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
          if (!isPdf) toast.error('Faqat PDF fayl yuklash mumkin')
          else if (file.size > MAX_PDF_BYTES) toast.error(`${file.name}: 20 MB dan katta`)
          else upload.mutate(file)
        }}
      />
    </Card>
  )
}

// --- Per-funnel text overrides ----------------------------------------------------------

type TextKey = (typeof FUNNEL_TEXT_KEYS)[number]
type Texts = Record<TextKey, string>

const TEXT_SECTIONS: { title: string; keys: TextKey[] }[] = [
  { title: 'Instagram', keys: ['FUNNEL_IG_COMMENT_REPLY', 'FUNNEL_IG_DM_WELCOME', 'FUNNEL_IG_NOT_FOLLOWING', 'FUNNEL_IG_LINK_MESSAGE'] },
  { title: 'Telegram kanal', keys: ['FUNNEL_TG_COMMENT_REPLY'] },
  {
    title: "Bot suhbati va qo'llanma",
    keys: ['FUNNEL_BOT_WELCOME', 'FUNNEL_ASK_NAME', 'FUNNEL_ASK_PHONE', 'FUNNEL_ASK_GRADE', 'FUNNEL_GRADES', 'FUNNEL_PDF_CAPTION', 'FUNNEL_BOOK_BUTTON'],
  },
]

function toTexts(f: FunnelOut): Texts {
  const out = {} as Texts
  for (const k of FUNNEL_TEXT_KEYS) out[k] = f.texts?.[k] ?? ''
  return out
}

function TextField({ item, textKey, value, onChange }: {
  item: SettingItem | undefined
  textKey: TextKey
  value: string
  onChange: (v: string) => void
}) {
  const global = item?.value ?? ''
  const overridden = value.trim().length > 0
  const multiline = !item || item.type === 'textarea'
  return (
    <div className={multiline ? 'md:col-span-2' : undefined}>
      <Label
        hint={overridden
          ? <Badge className="bg-brand-50 text-brand-700 ring-brand-200">shu voronka uchun</Badge>
          : <Badge className="bg-gray-100 text-gray-500 ring-gray-200">umumiy matn</Badge>}
      >
        {item?.label ?? textKey}
      </Label>
      {multiline ? (
        <Textarea rows={4} value={value} placeholder={global} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <Input value={value} placeholder={global} onChange={(e) => onChange(e.target.value)} />
      )}
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="text-gray-500">{item?.help}</span>
        {overridden ? (
          <button type="button" onClick={() => onChange('')} className="inline-flex items-center gap-1 text-gray-400 hover:text-red-600">
            <RotateCcw className="h-3 w-3" /> Umumiy matnga qaytarish
          </button>
        ) : global ? (
          <button type="button" onClick={() => onChange(global)} className="text-brand-600 hover:text-brand-700">
            Umumiy matnni tahrirlash uchun ko'chirish
          </button>
        ) : null}
      </div>
    </div>
  )
}

function TextsCard({ funnel, items, loading, error, onRetry }: {
  funnel: FunnelOut
  items: SettingItem[]
  loading: boolean
  error: unknown
  onRetry: () => void
}) {
  const qc = useQueryClient()
  const base = toTexts(funnel)
  const [draft, setDraft] = useSyncedForm(base)
  const changed = FUNNEL_TEXT_KEYS.some((k) => draft[k].trim() !== base[k].trim())

  const save = useMutation({
    // Every whitelisted key is sent ("" = use the global text) so both merge and
    // replace semantics on the server clear an override correctly.
    mutationFn: () => {
      const texts: Record<string, string> = { ...(funnel.texts ?? {}) }
      for (const k of FUNNEL_TEXT_KEYS) texts[k] = draft[k].trim() ? draft[k] : ''
      return funnelApi.updateFunnel(funnel.id, { texts })
    },
    onSuccess: () => {
      toast.success("Matnlar saqlandi")
      qc.invalidateQueries({ queryKey: FUNNELS_KEY })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  useEffect(() => {
    if (!changed) return
    const handler = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [changed])

  const byKey = new Map(items.map((i) => [i.key, i]))
  const overrides = FUNNEL_TEXT_KEYS.filter((k) => base[k].trim()).length

  return (
    <Card>
      <CardHeader
        title={changed ? 'Matnlar •' : 'Matnlar'}
        subtitle={`Bo'sh maydon — umumiy matn (xira ko'rinib turgani) ishlatiladi. Shu voronkada o'zgartirilgan: ${overrides} ta`}
        action={<Button size="sm" icon={<Save className="h-3.5 w-3.5" />} disabled={!changed} loading={save.isPending} onClick={() => save.mutate()}>Saqlash</Button>}
      />
      {loading && <Loading />}
      {Boolean(error) && <ErrorState error={error} onRetry={onRetry} />}
      {!loading && !error && (
        <div className="space-y-6 px-5 py-5">
          {TEXT_SECTIONS.map((s) => (
            <section key={s.title} className="space-y-4">
              <h3 className="border-b border-gray-100 pb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{s.title}</h3>
              <div className="grid gap-5 md:grid-cols-2">
                {s.keys.map((k) => (
                  <TextField key={k} item={byKey.get(k)} textKey={k} value={draft[k]} onChange={(v) => setDraft((d) => ({ ...d, [k]: v }))} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
      {changed && (
        <div className="sticky bottom-0 flex items-center justify-end gap-3 rounded-b-xl border-t border-gray-100 bg-white/95 px-5 py-3 backdrop-blur">
          <span className="text-xs text-amber-600">Saqlanmagan o'zgarishlar bor</span>
          <Button icon={<Save className="h-4 w-4" />} loading={save.isPending} onClick={() => save.mutate()}>Saqlash</Button>
        </div>
      )}
    </Card>
  )
}

// --- Tab ----------------------------------------------------------------------------------

/** Per-funnel "Sozlamalar" (admin). Remounted per funnel so forms never leak between funnels. */
export function FunnelSettingsTab({ funnel, funnels, selectFunnel }: FunnelTabProps) {
  const settings = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get })
  if (!funnel) return null
  const group = settings.data?.groups.find((g) => g.id === 'funnel')
  const items = group?.items ?? []
  const globalKeywords = items.find((i) => i.key === 'FUNNEL_KEYWORDS')?.value

  return (
    <div key={funnel.id} className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="min-w-0 space-y-6">
        <MainCard funnel={funnel} funnels={funnels} globalKeywords={globalKeywords} selectFunnel={selectFunnel} />
        <TextsCard
          funnel={funnel}
          items={items}
          loading={settings.isLoading}
          error={settings.isError ? settings.error : null}
          onRetry={() => settings.refetch()}
        />
      </div>
      <div className="space-y-6 lg:sticky lg:top-6 lg:self-start">
        <LinksCard funnel={funnel} />
        <LeadMagnetCard funnel={funnel} />
      </div>
    </div>
  )
}
