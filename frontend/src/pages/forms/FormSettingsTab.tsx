import type { Dispatch, SetStateAction } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import toast from 'react-hot-toast'
import { Info, RotateCcw, Save, Trash2 } from 'lucide-react'
import { formsApi } from '@/api/forms'
import { errorMessage } from '@/api/client'
import type { FormOut } from '@/api/types'
import { Button, Card, CardHeader, Input, Label, Textarea, Toggle } from '@/components/ui'
import { fmtNumber } from '@/lib/format'
import {
  FORMS_KEY, LinkRow, SLUG_MAX, SUBMIT_LABEL_MAX, SUCCESS_MESSAGE_MAX, formKey, settingsPatch, toSettingsDraft, urlForSlug,
  validateSettings, type SettingsDraft,
} from './shared'

export interface FormSettingsTabProps {
  form: FormOut
  draft: SettingsDraft
  setDraft: Dispatch<SetStateAction<SettingsDraft>>
  dirty: boolean
  reset: () => void
}

function ToggleRow({ checked, onChange, title, text }: { checked: boolean; onChange: (v: boolean) => void; title: string; text: string }) {
  return (
    <label className="flex items-start gap-3">
      <Toggle checked={checked} onChange={onChange} />
      <span className="text-sm text-gray-700">
        {title}
        <span className="block text-xs text-gray-500">{text}</span>
      </span>
    </label>
  )
}

export function FormSettingsTab({ form, draft, setDraft, dirty, reset }: FormSettingsTabProps) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const base = toSettingsDraft(form)
  const errors = validateSettings(draft)
  const valid = Object.keys(errors).length === 0
  const slugChanged = draft.slug !== base.slug
  const relativeUrl = form.url.startsWith('/')

  const set = <K extends keyof SettingsDraft>(k: K, v: SettingsDraft[K]) => setDraft((d) => ({ ...d, [k]: v }))

  const save = useMutation({
    mutationFn: () => formsApi.update(form.id, settingsPatch(draft, base)),
    onSuccess: (updated) => {
      toast.success('Saqlandi')
      qc.setQueryData(formKey(form.id), updated)
      qc.invalidateQueries({ queryKey: FORMS_KEY, exact: true })
      setDraft(toSettingsDraft(updated))
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const deactivate = useMutation({
    mutationFn: () => formsApi.update(form.id, { is_active: false }),
    onSuccess: (updated) => {
      toast.success('Forma nofaol qilindi — havola endi ochilmaydi')
      qc.setQueryData(formKey(form.id), updated)
      qc.invalidateQueries({ queryKey: FORMS_KEY, exact: true })
      setDraft((d) => ({ ...d, is_active: false }))
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const remove = useMutation({
    mutationFn: () => formsApi.remove(form.id),
    onSuccess: () => {
      toast.success("Forma o'chirildi")
      qc.removeQueries({ queryKey: formKey(form.id) })
      qc.invalidateQueries({ queryKey: FORMS_KEY, exact: true })
      navigate('/forms', { replace: true })
    },
    onError: (e) => {
      if (axios.isAxiosError(e) && e.response?.status === 409) {
        const why = errorMessage(e, "Formada javoblar bor — o'chirib bo'lmaydi. Uni nofaol qiling.")
        if (form.is_active) {
          if (window.confirm(`${why}\n\nForma hozir nofaol qilinsinmi? Havola ochilmay qoladi, javoblar va leadlar saqlanadi.`)) {
            deactivate.mutate()
          }
        } else {
          toast.error(why)
        }
        return
      }
      toast.error(errorMessage(e))
    },
  })

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <Card className="min-w-0 self-start">
        <CardHeader
          title={dirty ? 'Sozlamalar •' : 'Sozlamalar'}
          action={
            <div className="flex gap-1">
              {dirty && (
                <Button variant="ghost" size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} disabled={save.isPending} onClick={reset}>
                  Bekor qilish
                </Button>
              )}
              <Button size="sm" icon={<Save className="h-3.5 w-3.5" />} disabled={!dirty || !valid} loading={save.isPending} onClick={() => save.mutate()}>
                Saqlash
              </Button>
            </div>
          }
        />
        <div className="space-y-5 px-5 py-5">
          <div>
            <Label hint="a-z, 0-9, «-»">Havola manzili</Label>
            <Input
              value={draft.slug}
              maxLength={SLUG_MAX}
              onChange={(e) => set('slug', e.target.value.toLowerCase().replace(/[\s_]+/g, '-'))}
              placeholder="qabul-2026"
              spellCheck={false}
            />
            {errors.slug ? (
              <p className="mt-1 text-xs text-red-600">{errors.slug}</p>
            ) : (
              <p className="mt-1 break-all text-xs text-gray-500">{urlForSlug(form, draft.slug)}</p>
            )}
            {slugChanged && !errors.slug && (
              <p className="mt-1 text-xs text-amber-600">O'zgartirilsa, avval tarqatilgan havola ishlamay qoladi.</p>
            )}
          </div>

          <ToggleRow
            checked={draft.is_active}
            onChange={(v) => set('is_active', v)}
            title="Faol"
            text="Nofaol formaning havolasi «Forma topilmadi yoki yopilgan» sahifasini ko'rsatadi."
          />

          <div>
            <Label hint={`${draft.submit_label.length} / ${SUBMIT_LABEL_MAX}`}>Yuborish tugmasi matni</Label>
            <Input
              value={draft.submit_label}
              maxLength={SUBMIT_LABEL_MAX}
              onChange={(e) => set('submit_label', e.target.value)}
              placeholder="Yuborish"
            />
            {errors.submit_label && <p className="mt-1 text-xs text-red-600">{errors.submit_label}</p>}
          </div>

          <div>
            <Label>Yuborilgandan keyingi xabar</Label>
            <Textarea
              rows={4}
              maxLength={SUCCESS_MESSAGE_MAX}
              value={draft.success_message}
              onChange={(e) => set('success_message', e.target.value)}
              placeholder="Rahmat! Arizangiz qabul qilindi. Tez orada siz bilan bog'lanamiz."
            />
            <p className="mt-1 text-xs text-gray-500">Forma yuborilgach, shu matn ko'rsatiladi.</p>
          </div>

          <ToggleRow
            checked={draft.notify}
            onChange={(v) => set('notify', v)}
            title="Telegram'ga xabar yuborish"
            text="Har bir yangi javob xodimlarning Telegram chatiga yuboriladi (Sozlamalar → Telegram)."
          />
        </div>
      </Card>

      <div className="space-y-6 lg:sticky lg:top-6 lg:self-start">
        <Card>
          <CardHeader title="Joriy havola" subtitle={form.is_active ? 'Shu havolani tarqating' : "Forma nofaol — havola ochilmaydi"} />
          <div className="space-y-3 px-5 py-4">
            <LinkRow url={form.url} />
            {relativeUrl && (
              <p className="flex items-start gap-1.5 text-xs text-amber-700">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                PUBLIC_URL sozlanmagan — havola panel manzilidan olindi.
              </p>
            )}
            <p className="text-xs text-gray-500">
              Reklama uchun oxiriga <code className="rounded bg-gray-100 px-1">?utm_source=instagram</code> kabi belgi qo'shsangiz,
              u javob bilan birga saqlanadi.
            </p>
          </div>
        </Card>

        <Card>
          <CardHeader title="Formani o'chirish" />
          <div className="space-y-3 px-5 py-4">
            <p className="text-xs text-gray-500">
              {form.submissions > 0
                ? `Formada ${fmtNumber(form.submissions)} ta javob bor — uni o'chirib bo'lmaydi, faqat nofaol qilish mumkin.`
                : "Javobi yo'q formani butunlay o'chirish mumkin."}
            </p>
            <Button
              variant="ghost"
              size="sm"
              className="text-red-600 hover:bg-red-50"
              icon={<Trash2 className="h-4 w-4" />}
              loading={remove.isPending || deactivate.isPending}
              onClick={() => { if (window.confirm(`«${form.title}» formasi o'chirilsinmi?`)) remove.mutate() }}
            >
              Formani o'chirish
            </Button>
          </div>
        </Card>
      </div>
    </div>
  )
}
