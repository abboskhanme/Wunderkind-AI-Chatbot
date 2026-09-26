import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ClipboardList, Inbox, Pencil, Plus } from 'lucide-react'
import { formsApi } from '@/api/forms'
import { errorMessage } from '@/api/client'
import type { FormOut } from '@/api/types'
import { Badge, Button, Card, Empty, Input, Label, Loading, Modal, PageHeader } from '@/components/ui'
import { ErrorState } from '@/pages/funnel/shared'
import { fmtAgo, fmtNumber } from '@/lib/format'
import { FORMS_KEY, LinkRow, TITLE_MAX, formKey } from './forms/shared'

function CreateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  useEffect(() => {
    if (open) setTitle('')
  }, [open])

  const create = useMutation({
    // Fields are left out: the server adds «Ism-familiya» and «Telefon raqam» (SPEC 15.4)
    mutationFn: () => formsApi.create({ title: title.trim() }),
    onSuccess: (form) => {
      toast.success('Forma yaratildi')
      qc.setQueryData(formKey(form.id), form)
      qc.invalidateQueries({ queryKey: FORMS_KEY, exact: true })
      onClose()
      navigate(`/forms/${form.id}`)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const valid = title.trim().length > 0
  function submit(e: FormEvent) {
    e.preventDefault()
    if (valid && !create.isPending) create.mutate()
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Yangi forma"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Bekor qilish</Button>
          <Button type="submit" form="create-form" icon={<Plus className="h-4 w-4" />} disabled={!valid} loading={create.isPending}>
            Yaratish
          </Button>
        </>
      }
    >
      <form id="create-form" onSubmit={submit} className="space-y-2">
        <Label>Sarlavha</Label>
        <Input
          autoFocus
          value={title}
          maxLength={TITLE_MAX}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Masalan: 2026-yil qabuliga ariza"
        />
        <p className="text-xs text-gray-500">
          Forma «Ism-familiya» va «Telefon raqam» savollari bilan yaratiladi — keyin istalgancha savol qo'shasiz.
        </p>
      </form>
    </Modal>
  )
}

function FormCard({ form }: { form: FormOut }) {
  const navigate = useNavigate()
  return (
    <Card className="flex flex-col">
      <div className="flex-1 space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <Link to={`/forms/${form.id}`} className="min-w-0 font-medium text-gray-900 hover:text-brand-700">
            <span className="line-clamp-2 break-words">{form.title}</span>
          </Link>
          {form.is_active
            ? <Badge className="shrink-0 bg-emerald-50 text-emerald-700 ring-emerald-200">Faol</Badge>
            : <Badge className="shrink-0 bg-gray-100 text-gray-600 ring-gray-200">Nofaol</Badge>}
        </div>
        {form.description && <p className="line-clamp-2 text-sm text-gray-500">{form.description}</p>}
        <dl className="grid grid-cols-2 gap-2">
          <div className="rounded-lg bg-gray-50 px-3 py-2">
            <dt className="text-[11px] uppercase tracking-wide text-gray-500">Javoblar</dt>
            <dd className="text-lg font-semibold tabular-nums text-gray-900">{fmtNumber(form.submissions)}</dd>
          </div>
          <div className="rounded-lg bg-gray-50 px-3 py-2">
            <dt className="text-[11px] uppercase tracking-wide text-gray-500">Oxirgi javob</dt>
            <dd className="truncate pt-1 text-sm text-gray-800">{form.last_submission_at ? fmtAgo(form.last_submission_at) : '—'}</dd>
          </div>
        </dl>
        <div>
          <LinkRow url={form.url} />
          {!form.is_active && <p className="mt-1 text-xs text-gray-500">Nofaol — havola ochilmaydi.</p>}
        </div>
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-gray-100 px-4 py-2.5">
        <span className="text-xs text-gray-500">{form.fields.length} ta savol</span>
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" icon={<Inbox className="h-3.5 w-3.5" />} onClick={() => navigate(`/forms/${form.id}?tab=answers`)}>
            Javoblar
          </Button>
          <Button variant="secondary" size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => navigate(`/forms/${form.id}`)}>
            Tahrirlash
          </Button>
        </div>
      </div>
    </Card>
  )
}

export default function FormsPage() {
  const [creating, setCreating] = useState(false)
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: FORMS_KEY, queryFn: formsApi.list })
  const openCreate = () => setCreating(true)

  return (
    <>
      <PageHeader
        title="Formalar"
        subtitle="Havola orqali to'ldiriladigan anketalar. Har bir javob «Leadlar»ga forma nomi bilan tushadi."
        action={<Button icon={<Plus className="h-4 w-4" />} onClick={openCreate}>Yangi forma</Button>}
      />

      {isLoading && <Card><Loading /></Card>}
      {isError && !data && <Card><ErrorState error={error} onRetry={() => refetch()} /></Card>}
      {data && data.length === 0 && (
        <Card>
          <Empty
            icon={<ClipboardList className="h-6 w-6" />}
            title="Hali forma yo'q"
            text="Masalan: «Qabulga ariza», «Ochiq eshiklar kuniga yozilish». Havolasini Instagram bio, reklama yoki Telegram kanalga qo'ying."
            action={<Button icon={<Plus className="h-4 w-4" />} onClick={openCreate}>Yangi forma</Button>}
          />
        </Card>
      )}
      {data && data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((f) => <FormCard key={f.id} form={f} />)}
        </div>
      )}

      <CreateModal open={creating} onClose={() => setCreating(false)} />
    </>
  )
}
