import { useState, type Dispatch, type SetStateAction } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { AlertTriangle, Plus, RotateCcw, Save } from 'lucide-react'
import { formsApi } from '@/api/forms'
import { errorMessage } from '@/api/client'
import type { FormOut, LeadField } from '@/api/types'
import { Button, Card, CardHeader, Input, Label, Textarea } from '@/components/ui'
import { FieldCard } from './FieldCard'
import {
  DESCRIPTION_MAX, FORMS_KEY, MAX_FIELDS, TITLE_MAX, blankField, formKey, newFieldId, toQuestionsDraft,
  toQuestionsPayload, validateQuestions, type FieldDraft, type QuestionsDraft,
} from './shared'

export interface QuestionsTabProps {
  form: FormOut
  draft: QuestionsDraft
  setDraft: Dispatch<SetStateAction<QuestionsDraft>>
  dirty: boolean
  reset: () => void
}

export function QuestionsTab({ form, draft, setDraft, dirty, reset }: QuestionsTabProps) {
  const qc = useQueryClient()
  // Errors appear after the first save attempt, then follow the edits live
  const [showErrors, setShowErrors] = useState(false)
  // Id of a question just added — its label input takes focus
  const [focusId, setFocusId] = useState<string | null>(null)

  const errors = validateQuestions(draft)
  const fields = draft.fields
  const full = fields.length >= MAX_FIELDS
  const savedIds = new Set(form.fields.map((f) => f.id))
  const hasPhone = fields.some((f) => f.lead_field === 'phone')

  const save = useMutation({
    mutationFn: () => formsApi.update(form.id, toQuestionsPayload(draft)),
    onSuccess: (updated) => {
      toast.success('Saqlandi')
      qc.setQueryData(formKey(form.id), updated)
      qc.invalidateQueries({ queryKey: FORMS_KEY, exact: true })
      setDraft(toQuestionsDraft(updated))
      setShowErrors(false)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  function trySave() {
    if (errors.total > 0) {
      setShowErrors(true)
      toast.error("Formada xatolar bor — qizil bilan belgilangan joylarni tuzating")
      return
    }
    save.mutate()
  }

  function setFields(fn: (fields: FieldDraft[]) => FieldDraft[]) {
    setDraft((d) => ({ ...d, fields: fn(d.fields) }))
  }

  function patchField(id: string, patch: Partial<FieldDraft>) {
    setFields((list) => list.map((f) => (f.id === id ? { ...f, ...patch } : f)))
  }

  function addField() {
    if (full) return
    const f = blankField(fields.map((x) => x.id))
    setFocusId(f.id)
    setFields((list) => [...list, f])
  }

  function move(index: number, dir: -1 | 1) {
    setFields((list) => {
      const j = index + dir
      if (j < 0 || j >= list.length) return list
      const next = [...list]
      ;[next[index], next[j]] = [next[j], next[index]]
      return next
    })
  }

  function duplicate(index: number) {
    if (full) return
    const src = fields[index]
    // Each lead field may belong to one question only — the copy starts without it
    const copy: FieldDraft = { ...src, id: newFieldId(fields.map((f) => f.id)), options: [...src.options], lead_field: null }
    setFocusId(copy.id)
    setFields((list) => [...list.slice(0, index + 1), copy, ...list.slice(index + 1)])
  }

  function remove(field: FieldDraft) {
    if (savedIds.has(field.id) && form.submissions > 0) {
      const name = field.label.trim() || 'Bu savol'
      const ok = window.confirm(
        `«${name}» o'chirilsinmi?\n\nUnga berilgan eski javoblar «Javoblar» jadvalida va CSV'da ko'rinmay qoladi (lead yozishmasida saqlanib qoladi).`,
      )
      if (!ok) return
    }
    setFields((list) => list.filter((f) => f.id !== field.id))
  }

  function usedBy(except: string): Set<LeadField> {
    const out = new Set<LeadField>()
    for (const f of fields) if (f.id !== except && f.lead_field) out.add(f.lead_field)
    return out
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Card>
        <CardHeader
          title={dirty ? 'Forma •' : 'Forma'}
          subtitle="Sarlavha va tavsif forma sahifasining tepasida ko'rinadi"
          action={
            <Button size="sm" icon={<Save className="h-3.5 w-3.5" />} disabled={!dirty} loading={save.isPending} onClick={trySave}>
              Saqlash
            </Button>
          }
        />
        <div className="space-y-4 px-5 py-4">
          <div>
            <Label hint={`${draft.title.length} / ${TITLE_MAX}`}>Sarlavha</Label>
            <Input
              value={draft.title}
              maxLength={TITLE_MAX}
              onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
              placeholder="Masalan: 2026-yil qabuliga ariza"
              className="text-base font-medium"
            />
            {showErrors && errors.title && <p className="mt-1 text-xs text-red-600">{errors.title}</p>}
          </div>
          <div>
            <Label hint="ixtiyoriy">Tavsif</Label>
            <Textarea
              rows={3}
              maxLength={DESCRIPTION_MAX}
              value={draft.description}
              onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
              placeholder="Masalan: Ma'lumotlaringizni qoldiring — qabul bo'limi 1 ish kuni ichida qo'ng'iroq qiladi."
            />
          </div>
        </div>
      </Card>

      {!hasPhone && fields.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2.5 text-xs text-amber-800 ring-1 ring-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Hech bir savol «Lead maydoni: Telefon» qilib belgilanmagan. Shunda lead telefonsiz tushadi va bir odamning
            takroriy arizalari bitta leadga birlashtirilmaydi.
          </p>
        </div>
      )}

      {fields.map((f, i) => (
        <FieldCard
          key={f.id}
          field={f}
          index={i}
          total={fields.length}
          errors={showErrors ? errors.fields[f.id] : undefined}
          usedLeadFields={usedBy(f.id)}
          canDuplicate={!full}
          autoFocus={f.id === focusId}
          onChange={(patch) => patchField(f.id, patch)}
          onMove={(dir) => move(i, dir)}
          onDuplicate={() => duplicate(i)}
          onRemove={() => remove(f)}
        />
      ))}

      {showErrors && errors.fieldsCount && <p className="text-center text-sm text-red-600">{errors.fieldsCount}</p>}

      <button
        type="button"
        onClick={addField}
        disabled={full}
        className="flex w-full items-center justify-center gap-2 rounded-xl border-2 border-dashed border-gray-300 py-4 text-sm font-medium text-gray-500 transition-colors hover:border-brand-400 hover:text-brand-600 disabled:cursor-not-allowed disabled:hover:border-gray-300 disabled:hover:text-gray-500"
      >
        <Plus className="h-5 w-5" />
        {full ? `Savollar soni ${MAX_FIELDS} tadan oshmaydi` : "Savol qo'shish"}
      </button>

      {dirty && (
        <div className="sticky bottom-0 z-10 -mx-4 flex flex-wrap items-center justify-end gap-2 border-t border-gray-200 bg-white/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-xl sm:border sm:shadow-sm">
          <span className="mr-auto text-xs text-amber-600">
            Saqlanmagan o'zgarishlar bor
            {showErrors && errors.total > 0 && <span className="text-red-600"> · {errors.total} ta xato</span>}
          </span>
          <Button
            variant="ghost"
            size="sm"
            icon={<RotateCcw className="h-3.5 w-3.5" />}
            disabled={save.isPending}
            onClick={() => {
              if (window.confirm("Saqlanmagan o'zgarishlar bekor qilinsinmi?")) {
                reset()
                setShowErrors(false)
              }
            }}
          >
            Bekor qilish
          </Button>
          <Button icon={<Save className="h-4 w-4" />} loading={save.isPending} onClick={trySave}>Saqlash</Button>
        </div>
      )}
    </div>
  )
}
