import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Save } from 'lucide-react'
import { leadsApi } from '@/api/leads'
import { errorMessage } from '@/api/client'
import type { LeadDetail, LeadPatch, LeadStatus } from '@/api/types'
import { Button, Input, Label, Select, Textarea } from './ui'
import { ScoreBadge } from './LeadBadges'
import { SOURCE_LABELS, STAGE_LABELS, STATUS_LABELS, STATUSES } from '@/lib/labels'
import { fmtDateTime } from '@/lib/format'

interface Form {
  status: LeadStatus
  name: string
  contact: string
  course_interest: string
  student_age: string
  preferred_time: string
  note: string
  assigned_to_id: string
}

function toForm(l: LeadDetail): Form {
  return {
    status: l.status,
    name: l.name ?? '',
    contact: l.contact ?? '',
    course_interest: l.course_interest ?? '',
    student_age: l.student_age ?? '',
    preferred_time: l.preferred_time ?? '',
    note: l.note ?? '',
    assigned_to_id: l.assigned_to_id ?? '',
  }
}

const TEXT_FIELDS: { key: keyof Form; label: string; placeholder?: string }[] = [
  { key: 'name', label: 'Ismi' },
  { key: 'contact', label: 'Telefon / kontakt', placeholder: '+998 90 123 45 67' },
  { key: 'course_interest', label: 'Qiziqishi' },
  { key: 'student_age', label: "Farzand yoshi / sinfi" },
  { key: 'preferred_time', label: 'Qulay vaqt / filial' },
]

/** Editable lead details — used in the inbox side panel and the leads drawer. */
export function LeadCard({ lead }: { lead: LeadDetail }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<Form>(() => toForm(lead))
  // Server values the form was last synced to — "dirty" is measured against these
  const [base, setBase] = useState<Form>(() => toForm(lead))
  const { data: assignees } = useQuery({ queryKey: ['assignees'], queryFn: leadsApi.assignees, staleTime: 300_000 })

  // Another lead opened: always reset.
  useEffect(() => {
    setForm(toForm(lead))
    setBase(toForm(lead))
  }, [lead.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Server copy changed (new message, AI filled a field): adopt it only when the
  // operator has no unsaved edits — polling must not wipe what they are typing.
  useEffect(() => {
    const next = toForm(lead)
    setForm((cur) => ((Object.keys(cur) as (keyof Form)[]).every((k) => cur[k] === base[k]) ? next : cur))
    setBase(next)
  }, [lead.updated_at]) // eslint-disable-line react-hooks/exhaustive-deps

  const initial = base
  const dirty = (Object.keys(form) as (keyof Form)[]).filter((k) => form[k] !== initial[k])

  const save = useMutation({
    mutationFn: () => {
      const body: LeadPatch = {}
      for (const k of dirty) {
        const v = form[k]
        if (k === 'status') body.status = v as LeadStatus
        else (body as Record<string, string | null>)[k] = v === '' ? null : v
      }
      return leadsApi.update(lead.id, body)
    },
    onSuccess: () => {
      toast.success('Saqlandi')
      qc.invalidateQueries({ queryKey: ['lead', lead.id] })
      qc.invalidateQueries({ queryKey: ['inbox'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const set = (k: keyof Form) => (v: string) => setForm((f) => ({ ...f, [k]: v }))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <ScoreBadge score={lead.lead_score} />
        {lead.stage && <span className="rounded-full bg-brand-50 px-2 py-0.5 font-medium text-brand-700">{STAGE_LABELS[lead.stage] ?? lead.stage}</span>}
        {lead.language && <span className="rounded-full bg-gray-100 px-2 py-0.5">{lead.language}</span>}
        <span className="rounded-full bg-gray-100 px-2 py-0.5">{SOURCE_LABELS[lead.source] ?? lead.source}</span>
      </div>

      {lead.summary && (
        <div className="rounded-lg bg-brand-50/60 p-3 text-sm text-gray-700 ring-1 ring-brand-100">
          <p className="mb-1 text-xs font-semibold text-brand-700">AI xulosasi</p>
          <p className="whitespace-pre-wrap">{lead.summary}</p>
        </div>
      )}

      <div>
        <Label>Holat</Label>
        <Select value={form.status} onChange={(e) => set('status')(e.target.value)}>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{STATUS_LABELS[s]}</option>
          ))}
        </Select>
      </div>

      {TEXT_FIELDS.map((f) => (
        <div key={f.key}>
          <Label>{f.label}</Label>
          <Input value={form[f.key]} placeholder={f.placeholder} onChange={(e) => set(f.key)(e.target.value)} />
        </div>
      ))}

      <div>
        <Label>Mas'ul xodim</Label>
        <Select value={form.assigned_to_id} onChange={(e) => set('assigned_to_id')(e.target.value)}>
          <option value="">— Biriktirilmagan —</option>
          {assignees?.map((a) => (
            <option key={a.id} value={a.id}>{a.full_name}</option>
          ))}
        </Select>
      </div>

      <div>
        <Label>Xodim izohi</Label>
        <Textarea rows={3} value={form.note} onChange={(e) => set('note')(e.target.value)} placeholder="Masalan: shanba kuni qayta qo'ng'iroq qilish" />
      </div>

      <Button className="w-full" icon={<Save className="h-4 w-4" />} disabled={dirty.length === 0} loading={save.isPending} onClick={() => save.mutate()}>
        Saqlash
      </Button>

      <dl className="grid grid-cols-2 gap-2 border-t border-gray-100 pt-3 text-xs text-gray-500">
        <dt>Yaratilgan</dt>
        <dd className="text-right text-gray-700">{fmtDateTime(lead.created_at)}</dd>
        <dt>Oxirgi mijoz xabari</dt>
        <dd className="text-right text-gray-700">{fmtDateTime(lead.last_customer_at)}</dd>
        <dt>Xabarlar</dt>
        <dd className="text-right text-gray-700">{lead.message_count}</dd>
      </dl>
    </div>
  )
}
