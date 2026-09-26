import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { Copy, ExternalLink } from 'lucide-react'
import type { FormField, FormFieldType, FormInput, FormOut, LeadField } from '@/api/types'
import { LEAD_FIELD_LABELS } from '@/lib/labels'
import { copyText } from '@/lib/clipboard'
import { cn } from '@/lib/cn'

// --- Query keys -------------------------------------------------------------------------

/** Prefix of every forms query: invalidating it refreshes the list, details and answers. */
export const FORMS_KEY = ['forms'] as const
export const formKey = (id: string) => ['forms', id] as const
export const submissionsKey = (id: string, page: number) => ['forms', id, 'submissions', page] as const

// --- Limits (docs/SPEC.md 15.1) -----------------------------------------------------------

export const MAX_FIELDS = 40
export const MAX_OPTIONS = 30
export const TITLE_MAX = 200
export const LABEL_MAX = 300
export const PLACEHOLDER_MAX = 120
export const HELP_MAX = 500
export const OPTION_MAX = 200
export const SUBMIT_LABEL_MAX = 60
export const DESCRIPTION_MAX = 5000
export const SUCCESS_MESSAGE_MAX = 2000
export const SLUG_MAX = 40
export const FORM_SLUG_RE = /^[a-z0-9][a-z0-9-]{0,39}$/

export const CHOICE_TYPES: readonly FormFieldType[] = ['single_choice', 'multiple_choice', 'dropdown']
/** A checkbox list has several values — the server refuses to map it to a lead column. */
export const canMapToLead = (t: FormFieldType) => t !== 'multiple_choice'

/** Types whose input shows a placeholder on the public page (radios / checkboxes / date do not). */
export const PLACEHOLDER_TYPES: readonly FormFieldType[] = ['short_text', 'long_text', 'phone', 'email', 'number', 'dropdown']

export const isChoice = (t: FormFieldType) => CHOICE_TYPES.includes(t)

// --- Public link ------------------------------------------------------------------------------

/** `url` is relative (/f/<slug>) when PUBLIC_URL is not set — resolve it against the panel origin. */
export function absoluteUrl(url: string): string {
  try {
    return new URL(url, window.location.origin).href
  } catch {
    return url
  }
}

/** Link preview for a slug being edited, on the same origin as the server's `url`. */
export function urlForSlug(form: Pick<FormOut, 'url'>, slug: string): string {
  const m = form.url.match(/^(.*)\/f\/[^/]*$/)
  return absoluteUrl(`${m ? m[1] : ''}/f/${slug}`)
}

export function LinkRow({ url, className }: { url: string; className?: string }) {
  const href = absoluteUrl(url)
  return (
    <div className={cn('flex items-center gap-1 rounded-lg bg-gray-50 py-1 pl-3 pr-1 ring-1 ring-gray-200', className)}>
      <code className="min-w-0 flex-1 truncate text-xs text-gray-800" title={href}>{href}</code>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); void copyText(href) }}
        className="rounded p-1.5 text-gray-400 hover:bg-white hover:text-gray-700"
        title="Nusxa olish"
        aria-label="Havoladan nusxa olish"
      >
        <Copy className="h-3.5 w-3.5" />
      </button>
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="rounded p-1.5 text-gray-400 hover:bg-white hover:text-gray-700"
        title="Yangi oynada ochish"
        aria-label="Formani yangi oynada ochish"
      >
        <ExternalLink className="h-3.5 w-3.5" />
      </a>
    </div>
  )
}

// --- Editable drafts ----------------------------------------------------------------------------

/** A field as edited: every optional key present, so inputs stay controlled. */
export interface FieldDraft {
  id: string
  type: FormFieldType
  label: string
  required: boolean
  placeholder: string
  help: string
  /** Kept when switching to a non-choice type (switching back restores them); sent only for choice types */
  options: string[]
  lead_field: LeadField | null
}

export interface QuestionsDraft {
  title: string
  description: string
  fields: FieldDraft[]
}

export interface SettingsDraft {
  slug: string
  is_active: boolean
  submit_label: string
  success_message: string
  notify: boolean
}

export function toFieldDraft(f: FormField): FieldDraft {
  return {
    id: f.id,
    type: f.type,
    label: f.label ?? '',
    required: Boolean(f.required),
    placeholder: f.placeholder ?? '',
    help: f.help ?? '',
    options: f.options ?? [],
    lead_field: f.lead_field ?? null,
  }
}

export function toQuestionsDraft(form: FormOut): QuestionsDraft {
  return { title: form.title, description: form.description ?? '', fields: (form.fields ?? []).map(toFieldDraft) }
}

export function toSettingsDraft(form: FormOut): SettingsDraft {
  return {
    slug: form.slug,
    is_active: form.is_active,
    submit_label: form.submit_label,
    success_message: form.success_message ?? '',
    notify: form.notify,
  }
}

/** The API shape of a field: optional keys only when they carry a value; empty options dropped. */
export function toFieldPayload(d: FieldDraft): FormField {
  const out: FormField = { id: d.id, type: d.type, label: d.label.trim(), required: d.required }
  const placeholder = d.placeholder.trim()
  const help = d.help.trim()
  if (placeholder && PLACEHOLDER_TYPES.includes(d.type)) out.placeholder = placeholder
  if (help) out.help = help
  if (isChoice(d.type)) out.options = d.options.map((o) => o.trim()).filter(Boolean)
  if (d.lead_field) out.lead_field = d.lead_field
  return out
}

export function toQuestionsPayload(d: QuestionsDraft): Pick<FormInput, 'title' | 'description' | 'fields'> {
  return { title: d.title.trim(), description: d.description.trim(), fields: d.fields.map(toFieldPayload) }
}

/**
 * Local draft of server data. While untouched it follows the server (refetches, the other
 * tab saving); once edited it is kept until saved or reset.
 */
export function useDraft<T>(server: T): [T, Dispatch<SetStateAction<T>>, () => void] {
  const [draft, setDraft] = useState<T>(server)
  const prev = useRef(server)
  const serialized = JSON.stringify(server)
  useEffect(() => {
    const before = prev.current
    const beforeSerialized = JSON.stringify(before)
    if (beforeSerialized === serialized) return
    const next = JSON.parse(serialized) as T
    setDraft((d) => (JSON.stringify(d) === beforeSerialized ? next : d))
    prev.current = next
  }, [serialized])
  const reset = () => setDraft(JSON.parse(serialized) as T)
  return [draft, setDraft, reset]
}

// --- Field ids --------------------------------------------------------------------------------

const ID_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789'

/** Random [a-z0-9]{8}, unique within the form. */
export function newFieldId(taken: Iterable<string>): string {
  const used = new Set(taken)
  for (;;) {
    const bytes = crypto.getRandomValues(new Uint8Array(8))
    const id = Array.from(bytes, (b) => ID_ALPHABET[b % ID_ALPHABET.length]).join('')
    if (!used.has(id)) return id
  }
}

export function blankField(taken: Iterable<string>): FieldDraft {
  return {
    id: newFieldId(taken),
    type: 'short_text',
    label: '',
    required: false,
    placeholder: '',
    help: '',
    options: [],
    lead_field: null,
  }
}

// --- Validation (mirrors docs/SPEC.md 15.1; the server re-checks) -------------------------------

export interface QuestionsErrors {
  title?: string
  /** Form-level: number of fields */
  fieldsCount?: string
  /** Per field id */
  fields: Record<string, string[]>
  total: number
}

export function validateQuestions(d: QuestionsDraft): QuestionsErrors {
  const errors: QuestionsErrors = { fields: {}, total: 0 }
  const title = d.title.trim()
  if (!title) errors.title = 'Forma sarlavhasini kiriting.'
  else if (title.length > TITLE_MAX) errors.title = `Sarlavha ${TITLE_MAX} belgidan oshmasin.`
  if (errors.title) errors.total++

  if (d.fields.length === 0) errors.fieldsCount = "Kamida bitta savol qo'shing."
  else if (d.fields.length > MAX_FIELDS) errors.fieldsCount = `Ko'pi bilan ${MAX_FIELDS} ta savol bo'lishi mumkin.`
  if (errors.fieldsCount) errors.total++

  const leadOwners = new Map<LeadField, string>()
  for (const f of d.fields) {
    const list: string[] = []
    const label = f.label.trim()
    if (!label) list.push('Savol matnini kiriting.')
    else if (label.length > LABEL_MAX) list.push(`Savol matni ${LABEL_MAX} belgidan oshmasin.`)
    if (f.placeholder.trim().length > PLACEHOLDER_MAX) list.push(`Namuna matn ${PLACEHOLDER_MAX} belgidan oshmasin.`)
    if (f.help.trim().length > HELP_MAX) list.push(`Izoh ${HELP_MAX} belgidan oshmasin.`)
    if (isChoice(f.type)) {
      const options = f.options.map((o) => o.trim()).filter(Boolean)
      if (options.length === 0) list.push('Kamida bitta variant kiriting.')
      else if (options.length > MAX_OPTIONS) list.push(`Ko'pi bilan ${MAX_OPTIONS} ta variant bo'lishi mumkin.`)
      if (options.some((o) => o.length > OPTION_MAX)) list.push(`Variant ${OPTION_MAX} belgidan oshmasin.`)
      if (new Set(options).size !== options.length) list.push('Variantlar takrorlanmasin.')
    }
    if (f.lead_field) {
      if (!canMapToLead(f.type)) list.push("Bir nechta tanlovli savolni lead maydoniga bog'lab bo'lmaydi.")
      else if (leadOwners.has(f.lead_field)) list.push(`«${LEAD_FIELD_LABELS[f.lead_field]}» lead maydoni faqat bitta savolga biriktiriladi.`)
      else leadOwners.set(f.lead_field, f.id)
    }
    if (list.length) {
      errors.fields[f.id] = list
      errors.total += list.length
    }
  }
  return errors
}

/** Only the settings that differ from the server copy (PATCH body). */
export function settingsPatch(draft: SettingsDraft, base: SettingsDraft): Partial<FormInput> {
  const patch: Partial<FormInput> = {}
  if (draft.slug !== base.slug) patch.slug = draft.slug
  if (draft.is_active !== base.is_active) patch.is_active = draft.is_active
  if (draft.submit_label.trim() !== base.submit_label.trim()) patch.submit_label = draft.submit_label.trim()
  if (draft.success_message.trim() !== base.success_message.trim()) patch.success_message = draft.success_message.trim()
  if (draft.notify !== base.notify) patch.notify = draft.notify
  return patch
}

export function validateSettings(d: SettingsDraft): { slug?: string; submit_label?: string } {
  const out: { slug?: string; submit_label?: string } = {}
  if (!FORM_SLUG_RE.test(d.slug)) {
    out.slug = `Faqat kichik lotin harflari, raqam va «-» (${SLUG_MAX} tagacha); birinchi belgi harf yoki raqam.`
  }
  const label = d.submit_label.trim()
  if (!label) out.submit_label = 'Tugma matnini kiriting.'
  else if (label.length > SUBMIT_LABEL_MAX) out.submit_label = `Tugma matni ${SUBMIT_LABEL_MAX} belgidan oshmasin.`
  return out
}

/** Warns before closing the tab / reloading while there are unsaved edits. */
export function useUnsavedGuard(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return
    const handler = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])
}
