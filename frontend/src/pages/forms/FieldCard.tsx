import { useState, type KeyboardEvent, type ReactNode } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, Circle, Copy, Plus, Square, Trash2, X } from 'lucide-react'
import type { FormFieldType, LeadField } from '@/api/types'
import { Card, Input, Label, Select, Toggle } from '@/components/ui'
import { FORM_FIELD_TYPE_LABELS, FORM_FIELD_TYPES, LEAD_FIELD_LABELS, LEAD_FIELDS } from '@/lib/labels'
import { cn } from '@/lib/cn'
import {
  HELP_MAX, LABEL_MAX, MAX_OPTIONS, OPTION_MAX, PLACEHOLDER_MAX, PLACEHOLDER_TYPES, canMapToLead, isChoice,
  type FieldDraft,
} from './shared'

const PLACEHOLDER_EXAMPLES: Partial<Record<FormFieldType, string>> = {
  short_text: 'Masalan: Aliyev Vali',
  long_text: 'Masalan: savolingizni yozing',
  phone: '+998 90 123 45 67',
  email: 'misol@gmail.com',
  number: 'Masalan: 7',
  dropdown: 'Tanlang',
}

function IconButton({ label, onClick, disabled, danger, children }: {
  label: string
  onClick: () => void
  disabled?: boolean
  danger?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'rounded-lg p-1.5 text-gray-400 transition-colors disabled:cursor-not-allowed disabled:opacity-30',
        danger ? 'hover:bg-red-50 hover:text-red-600' : 'hover:bg-gray-100 hover:text-gray-700',
      )}
    >
      {children}
    </button>
  )
}

function OptionsEditor({ type, options, onChange }: {
  type: FormFieldType
  options: string[]
  onChange: (options: string[]) => void
}) {
  // Index of an option just added with Enter / the button — gets focus when it mounts
  const [focusIndex, setFocusIndex] = useState<number | null>(null)
  const full = options.length >= MAX_OPTIONS

  function set(i: number, value: string) {
    onChange(options.map((o, j) => (j === i ? value : o)))
  }
  function add() {
    if (full) return
    setFocusIndex(options.length)
    onChange([...options, ''])
  }
  function remove(i: number) {
    onChange(options.filter((_, j) => j !== i))
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir
    if (j < 0 || j >= options.length) return
    const next = [...options]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  function onKeyDown(e: KeyboardEvent<HTMLInputElement>, i: number) {
    if (e.key !== 'Enter') return
    e.preventDefault()
    // Enter on the last filled option adds the next one (like Google Forms)
    if (i === options.length - 1 && options[i].trim()) add()
  }

  const marker = (i: number) =>
    type === 'single_choice' ? <Circle className="h-4 w-4 shrink-0 text-gray-300" />
      : type === 'multiple_choice' ? <Square className="h-4 w-4 shrink-0 text-gray-300" />
        : <span className="w-4 shrink-0 text-right text-xs tabular-nums text-gray-400">{i + 1}.</span>

  return (
    <div>
      <Label hint={`${options.length} / ${MAX_OPTIONS}`}>Variantlar</Label>
      <ul className="space-y-2">
        {options.map((o, i) => (
          <li key={i} className="flex items-center gap-2">
            {marker(i)}
            <Input
              value={o}
              maxLength={OPTION_MAX}
              autoFocus={i === focusIndex}
              onChange={(e) => set(i, e.target.value)}
              onKeyDown={(e) => onKeyDown(e, i)}
              placeholder={`${i + 1}-variant`}
              className="py-1.5"
              aria-label={`${i + 1}-variant`}
            />
            <div className="flex shrink-0">
              <IconButton label="Yuqoriga" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp className="h-4 w-4" /></IconButton>
              <IconButton label="Pastga" disabled={i === options.length - 1} onClick={() => move(i, 1)}><ArrowDown className="h-4 w-4" /></IconButton>
              <IconButton label="Variantni o'chirish" danger onClick={() => remove(i)}><X className="h-4 w-4" /></IconButton>
            </div>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={add}
        disabled={full}
        className="mt-2 inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-medium text-brand-600 hover:bg-brand-50 disabled:cursor-not-allowed disabled:text-gray-400 disabled:hover:bg-transparent"
      >
        <Plus className="h-4 w-4" /> Variant qo'shish
      </button>
    </div>
  )
}

export interface FieldCardProps {
  field: FieldDraft
  index: number
  total: number
  /** Shown only after a save attempt */
  errors: string[] | undefined
  /** Lead fields taken by the other fields of the form */
  usedLeadFields: ReadonlySet<LeadField>
  canDuplicate: boolean
  autoFocus: boolean
  onChange: (patch: Partial<FieldDraft>) => void
  onMove: (dir: -1 | 1) => void
  onDuplicate: () => void
  onRemove: () => void
}

export function FieldCard({
  field, index, total, errors, usedLeadFields, canDuplicate, autoFocus, onChange, onMove, onDuplicate, onRemove,
}: FieldCardProps) {
  const [showExtra, setShowExtra] = useState(Boolean(field.placeholder || field.help))
  const hasErrors = Boolean(errors?.length)
  const withPlaceholder = PLACEHOLDER_TYPES.includes(field.type)

  function changeType(type: FormFieldType) {
    const patch: Partial<FieldDraft> = { type }
    // A new choice question starts with one empty option to type into
    if (isChoice(type) && field.options.length === 0) patch.options = ['']
    // A phone question most likely is the lead's contact
    if (type === 'phone' && !field.lead_field && !usedLeadFields.has('phone')) patch.lead_field = 'phone'
    // Several ticked values cannot fill one lead column
    if (!canMapToLead(type)) patch.lead_field = null
    onChange(patch)
  }

  return (
    <Card className={cn('overflow-hidden', hasErrors && 'ring-2 ring-red-300')}>
      <div className="space-y-4 p-4 sm:p-5">
        <div className="grid gap-3 sm:grid-cols-[1fr_220px]">
          <div className="flex items-start gap-3">
            <span className="mt-2 flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 px-1.5 text-xs font-semibold text-brand-700">
              {index + 1}
            </span>
            <Input
              value={field.label}
              maxLength={LABEL_MAX}
              autoFocus={autoFocus}
              onChange={(e) => onChange({ label: e.target.value })}
              placeholder="Savol matni"
              aria-label={`${index + 1}-savol matni`}
              className="font-medium"
            />
          </div>
          <Select value={field.type} onChange={(e) => changeType(e.target.value as FormFieldType)} aria-label="Javob turi">
            {FORM_FIELD_TYPES.map((t) => <option key={t} value={t}>{FORM_FIELD_TYPE_LABELS[t]}</option>)}
          </Select>
        </div>

        {isChoice(field.type) && (
          <div className="sm:pl-9">
            <OptionsEditor type={field.type} options={field.options} onChange={(options) => onChange({ options })} />
          </div>
        )}

        <div className="sm:pl-9">
          {showExtra ? (
            <div className={cn('grid gap-3', withPlaceholder && 'sm:grid-cols-2')}>
              {withPlaceholder && (
                <div>
                  <Label hint="ixtiyoriy">{field.type === 'dropdown' ? "Tanlanmagan holatdagi matn" : 'Namuna matn (maydon ichida)'}</Label>
                  <Input
                    value={field.placeholder}
                    maxLength={PLACEHOLDER_MAX}
                    onChange={(e) => onChange({ placeholder: e.target.value })}
                    placeholder={PLACEHOLDER_EXAMPLES[field.type]}
                  />
                </div>
              )}
              <div>
                <Label hint="ixtiyoriy">Izoh (savol ostida)</Label>
                <Input
                  value={field.help}
                  maxLength={HELP_MAX}
                  onChange={(e) => onChange({ help: e.target.value })}
                  placeholder="Masalan: farzandingiz hozir o'qiyotgan sinf"
                />
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowExtra(true)}
              className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-800"
            >
              <ChevronDown className="h-3.5 w-3.5" /> Namuna matn va izoh qo'shish
            </button>
          )}
        </div>

        {hasErrors && (
          <ul className="space-y-0.5 text-xs text-red-600 sm:pl-9">
            {errors!.map((e) => <li key={e}>{e}</li>)}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-3 border-t border-gray-100 bg-gray-50/60 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <label className="flex min-w-0 items-center gap-2 text-sm text-gray-600">
          <span
            className="shrink-0"
            title={canMapToLead(field.type) ? 'Javob leadning shu maydoniga yoziladi' : "Bir nechta tanlovli savolni lead maydoniga bog'lab bo'lmaydi"}
          >
            Lead maydoni
          </span>
          <Select
            value={field.lead_field ?? ''}
            disabled={!canMapToLead(field.type)}
            onChange={(e) => onChange({ lead_field: (e.target.value || null) as LeadField | null })}
            className="py-1.5 sm:w-44"
          >
            <option value="">—</option>
            {LEAD_FIELDS.map((lf) => (
              <option key={lf} value={lf} disabled={usedLeadFields.has(lf)}>
                {LEAD_FIELD_LABELS[lf]}{usedLeadFields.has(lf) ? ' (band)' : ''}
              </option>
            ))}
          </Select>
        </label>
        <div className="flex items-center justify-between gap-3 sm:justify-end">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <Toggle checked={field.required} onChange={(v) => onChange({ required: v })} />
            Majburiy
          </label>
          <div className="flex items-center border-l border-gray-200 pl-2">
            <IconButton label="Yuqoriga" disabled={index === 0} onClick={() => onMove(-1)}><ArrowUp className="h-4 w-4" /></IconButton>
            <IconButton label="Pastga" disabled={index === total - 1} onClick={() => onMove(1)}><ArrowDown className="h-4 w-4" /></IconButton>
            <IconButton label="Nusxasini yaratish" disabled={!canDuplicate} onClick={onDuplicate}><Copy className="h-4 w-4" /></IconButton>
            <IconButton label="Savolni o'chirish" danger onClick={onRemove}><Trash2 className="h-4 w-4" /></IconButton>
          </div>
        </div>
      </div>
    </Card>
  )
}
