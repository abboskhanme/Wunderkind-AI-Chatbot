import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'
import type { SettingItem } from '@/api/types'
import { Badge, Input, Label, Select, Textarea } from './ui'

/** Draft value per key. For secrets, '' means "unchanged"; null means "clear". */
export type Draft = Record<string, string | null>

export function initialDraft(items: SettingItem[]): Draft {
  const d: Draft = {}
  for (const i of items) d[i.key] = i.secret ? '' : i.value ?? ''
  return d
}

/**
 * Server data changed (this or another group was saved): adopt new server values
 * only for fields the user has not touched, so unsaved edits survive.
 */
export function mergeDraft(prevItems: SettingItem[], nextItems: SettingItem[], draft: Draft): Draft {
  const before = initialDraft(prevItems)
  const after = initialDraft(nextItems)
  const out: Draft = {}
  for (const i of nextItems) {
    const untouched = !(i.key in draft) || draft[i.key] === before[i.key]
    out[i.key] = untouched ? after[i.key] : draft[i.key]
  }
  return out
}

/** Only keys whose draft differs from the server value are sent. */
export function changedValues(items: SettingItem[], draft: Draft): Record<string, string | null> {
  const out: Record<string, string | null> = {}
  for (const i of items) {
    const v = draft[i.key]
    if (i.secret) {
      if (v === null) out[i.key] = null
      else if (v && v.trim()) out[i.key] = v.trim()
    } else if ((v ?? '') !== (i.value ?? '')) {
      out[i.key] = v === '' ? null : v
    }
  }
  return out
}

function SecretInput({ item, value, onChange }: { item: SettingItem; value: string | null; onChange: (v: string | null) => void }) {
  const [show, setShow] = useState(false)
  const cleared = value === null
  return (
    <div>
      <div className="relative">
        <Input
          type={show ? 'text' : 'password'}
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={cleared ? "Saqlanganda o'chiriladi" : item.is_set ? `${item.masked} (o'zgartirish uchun yangisini kiriting)` : item.placeholder || 'Kiritilmagan'}
          autoComplete="new-password"
          className="pr-10"
        />
        <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-400 hover:text-gray-600">
          {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
      {item.is_set && !item.from_env && (
        <button type="button" onClick={() => onChange(cleared ? '' : null)} className="mt-1 text-xs text-gray-400 hover:text-red-600">
          {cleared ? 'Bekor qilish' : "Qiymatni o'chirish"}
        </button>
      )}
    </div>
  )
}

export function SettingField({ item, value, onChange, rows = 4 }: {
  item: SettingItem
  value: string | null
  onChange: (v: string | null) => void
  rows?: number
}) {
  let control
  if (item.secret) {
    control = <SecretInput item={item} value={value} onChange={onChange} />
  } else if (item.type === 'select') {
    control = (
      <Select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        <option value="">— Standart{item.default ? ` (${item.default})` : ''} —</option>
        {item.options.map((o) => <option key={o} value={o}>{o}</option>)}
      </Select>
    )
  } else if (item.type === 'textarea') {
    control = <Textarea rows={rows} value={value ?? ''} placeholder={item.placeholder} onChange={(e) => onChange(e.target.value)} />
  } else {
    control = (
      <Input
        type={item.type === 'number' ? 'number' : 'text'}
        value={value ?? ''}
        placeholder={item.placeholder || item.default}
        onChange={(e) => onChange(e.target.value)}
      />
    )
  }
  return (
    <div>
      <Label hint={item.from_env ? <Badge className="bg-gray-100 text-gray-500 ring-gray-200">.env dan</Badge> : undefined}>{item.label}</Label>
      {control}
      {item.help && <p className="mt-1 text-xs text-gray-500">{item.help}</p>}
    </div>
  )
}
