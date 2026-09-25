import { useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { AlertTriangle, Layers, Plus, RefreshCw, Save } from 'lucide-react'
import { funnelApi } from '@/api/funnel'
import { errorMessage } from '@/api/client'
import type { FunnelCreate, FunnelOut } from '@/api/types'
import { Badge, Button, Input, Label, Modal, Select, Toggle } from '@/components/ui'
import { fmtNumber } from '@/lib/format'
import { cn } from '@/lib/cn'
import { FUNNELS_KEY } from './shared'
import { SLUG_RE } from './FunnelSettingsTab'

function Counts({ entries, pdf, booked }: { entries: number; pdf: number; booked: number }) {
  return (
    <div className="mt-auto grid grid-cols-3 gap-1 pt-3 text-center">
      {[
        ['Kirdi', entries],
        ['PDF', pdf],
        ['Yozildi', booked],
      ].map(([label, n]) => (
        <div key={label} className="rounded-md bg-gray-50 px-1 py-1">
          <p className="text-sm font-semibold tabular-nums text-gray-900">{fmtNumber(Number(n))}</p>
          <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
        </div>
      ))}
    </div>
  )
}

function SwitcherCard({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'flex w-64 shrink-0 flex-col rounded-xl bg-white p-3 text-left shadow-sm ring-1 transition-colors',
        active ? 'ring-2 ring-brand-500' : 'ring-gray-200 hover:ring-gray-300',
      )}
    >
      {children}
    </button>
  )
}

function CreateModal({ open, onClose, funnels, onCreated }: {
  open: boolean
  onClose: () => void
  funnels: FunnelOut[]
  onCreated: (f: FunnelOut) => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ name: '', slug: '', keywords: '', copyFrom: '', isActive: true })
  useEffect(() => {
    if (open) setForm({ name: '', slug: '', keywords: '', copyFrom: '', isActive: true })
  }, [open])

  const slug = form.slug.trim()
  const slugOk = !slug || SLUG_RE.test(slug)
  const valid = form.name.trim().length > 0 && slugOk

  const create = useMutation({
    mutationFn: () => {
      const body: FunnelCreate = {
        name: form.name.trim(),
        keywords: form.keywords.trim(),
        is_active: form.isActive,
        ...(slug ? { slug } : {}),
        ...(form.copyFrom ? { copy_from_id: form.copyFrom } : {}),
      }
      return funnelApi.createFunnel(body)
    },
    onSuccess: (f) => {
      toast.success('Voronka yaratildi')
      qc.invalidateQueries({ queryKey: FUNNELS_KEY })
      onCreated(f)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Yangi voronka"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Bekor qilish</Button>
          <Button icon={<Save className="h-4 w-4" />} disabled={!valid} loading={create.isPending} onClick={() => create.mutate()}>Yaratish</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <Label>Nomi</Label>
          <Input autoFocus value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Masalan: 1-sinfga qabul" />
        </div>
        <div>
          <Label hint="ixtiyoriy">Qisqa nom (havola uchun)</Label>
          <Input
            value={form.slug}
            maxLength={32}
            onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase().replace(/\s+/g, '_') })}
            placeholder="Bo'sh bo'lsa, nomidan avtomatik"
          />
          {!slugOk && <p className="mt-1 text-xs text-red-600">Faqat kichik lotin harflari, raqam va «_» (32 tagacha).</p>}
        </div>
        <div>
          <Label hint="vergul bilan">Kalit so'zlar</Label>
          <Input value={form.keywords} onChange={(e) => setForm({ ...form, keywords: e.target.value })} placeholder="Masalan: qabul, 1-sinf" />
          <p className="mt-1 text-xs text-gray-500">Bo'sh bo'lsa, odam faqat voronka havolasi orqali kiradi.</p>
        </div>
        <div>
          <Label>Nusxa olish</Label>
          <Select value={form.copyFrom} onChange={(e) => setForm({ ...form, copyFrom: e.target.value })}>
            <option value="">— Bo'sh voronka —</option>
            {funnels.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </Select>
          <p className="mt-1 text-xs text-gray-500">Tanlangan voronkaning matnlari, sotuv xabarlari va qo'llanmasi (PDF) ko'chiriladi.</p>
        </div>
        <label className="flex items-center gap-3">
          <Toggle checked={form.isActive} onChange={(v) => setForm({ ...form, isActive: v })} />
          <span className="text-sm text-gray-700">Darhol faol</span>
        </label>
      </div>
    </Modal>
  )
}

export function FunnelSwitcher({ funnels, selectedId, loading, error, onRetry, canCreate, onSelect, onCreated }: {
  funnels: FunnelOut[]
  selectedId: string | null
  loading: boolean
  error: unknown
  onRetry: () => void
  canCreate: boolean
  onSelect: (id: string | null) => void
  onCreated: (f: FunnelOut) => void
}) {
  const [creating, setCreating] = useState(false)
  const total = funnels.reduce(
    (acc, f) => ({
      entries: acc.entries + (f.stats?.entries ?? 0),
      pdf: acc.pdf + (f.stats?.pdf_sent ?? 0),
      booked: acc.booked + (f.stats?.booked ?? 0),
    }),
    { entries: 0, pdf: 0, booked: 0 },
  )

  return (
    <div className="mb-6">
      <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2 pt-1">
        <SwitcherCard active={selectedId === null} onClick={() => onSelect(null)}>
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-brand-600" />
            <p className="font-medium text-gray-900">Hammasi</p>
          </div>
          <p className="mt-1 truncate text-xs text-gray-500">
            {funnels.length ? `${funnels.length} ta voronka birgalikda` : 'Barcha voronkalar'}
          </p>
          <Counts entries={total.entries} pdf={total.pdf} booked={total.booked} />
        </SwitcherCard>

        {loading && [0, 1].map((i) => <div key={i} className="h-28 w-64 shrink-0 animate-pulse rounded-xl bg-gray-100" />)}

        {funnels.map((f) => (
          <SwitcherCard key={f.id} active={selectedId === f.id} onClick={() => onSelect(f.id)}>
            <div className="flex items-center justify-between gap-2">
              <p className="truncate font-medium text-gray-900" title={f.name}>{f.name}</p>
              <div className="flex shrink-0 gap-1">
                {f.is_default && <Badge className="bg-brand-50 text-brand-700 ring-brand-200">Asosiy</Badge>}
                {f.is_active
                  ? <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-200">Faol</Badge>
                  : <Badge>Nofaol</Badge>}
              </div>
            </div>
            <p className="mt-1 truncate text-xs text-gray-500" title={f.keywords || undefined}>
              {f.keywords?.trim() ? f.keywords : f.is_default ? "Umumiy kalit so'zlar" : "Kalit so'z yo'q — faqat havola"}
            </p>
            {!f.has_pdf && (
              <p className="mt-1 flex items-center gap-1 text-[11px] text-amber-700">
                <AlertTriangle className="h-3 w-3" /> PDF yuklanmagan
              </p>
            )}
            <Counts entries={f.stats?.entries ?? 0} pdf={f.stats?.pdf_sent ?? 0} booked={f.stats?.booked ?? 0} />
          </SwitcherCard>
        ))}

        {canCreate && !loading && !error && (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="flex w-44 shrink-0 flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-gray-300 text-sm font-medium text-gray-500 hover:border-brand-400 hover:text-brand-600"
          >
            <Plus className="h-5 w-5" />
            Yangi voronka
          </button>
        )}
      </div>
      {Boolean(error) && (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
          <span className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Voronkalar ro'yxatini yuklab bo'lmadi: {errorMessage(error)}
          </span>
          <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onRetry}>Qayta urinish</Button>
        </div>
      )}
      <CreateModal
        open={creating}
        onClose={() => setCreating(false)}
        funnels={funnels}
        onCreated={(f) => { setCreating(false); onCreated(f) }}
      />
    </div>
  )
}
