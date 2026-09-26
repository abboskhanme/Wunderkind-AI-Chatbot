import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ChevronLeft, ChevronRight, Copy, Download, Inbox, Trash2, UserSquare2 } from 'lucide-react'
import { formsApi } from '@/api/forms'
import { errorMessage } from '@/api/client'
import type { FormOut, SubmissionOut } from '@/api/types'
import { Button, Card, Empty, Loading } from '@/components/ui'
import { ErrorState } from '@/pages/funnel/shared'
import { copyText } from '@/lib/clipboard'
import { fmtDateTime, fmtNumber } from '@/lib/format'
import { absoluteUrl, formKey, submissionsKey } from './shared'

const PAGE_SIZE = 50

function Dash() {
  return <span className="text-gray-300">—</span>
}

/** Answer to a current field (matched by field id); lists are joined with ", ". */
function answerText(s: SubmissionOut, fieldId: string): string {
  const a = s.answers.find((x) => x.field_id === fieldId)
  if (!a) return ''
  return Array.isArray(a.value) ? a.value.join(', ') : a.value
}

function utmText(utm: Record<string, string>): string {
  return Object.entries(utm)
    .filter(([, v]) => v)
    .map(([k, v]) => `${k.replace(/^utm_/, '')}: ${v}`)
    .join(' · ')
}

export function ResponsesTab({ form }: { form: FormOut }) {
  const [page, setPage] = useState(1)
  const [downloading, setDownloading] = useState(false)
  const { data, isLoading, isError, error, refetch, isPlaceholderData } = useQuery({
    queryKey: submissionsKey(form.id, page),
    queryFn: () => formsApi.submissions(form.id, page, PAGE_SIZE),
    placeholderData: (prev) => prev,
  })
  const qc = useQueryClient()
  // A person's data-deletion request: the answer goes, the lead stays
  const remove = useMutation({
    mutationFn: (id: string) => formsApi.removeSubmission(form.id, id),
    onSuccess: () => {
      toast.success("Javob o'chirildi")
      qc.invalidateQueries({ queryKey: formKey(form.id) })
      qc.invalidateQueries({ queryKey: ['forms'], exact: true })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  const withUtm = Boolean(data?.items.some((s) => utmText(s.utm ?? {})))

  async function downloadCsv() {
    setDownloading(true)
    try {
      await formsApi.downloadSubmissionsCsv(form)
    } catch {
      toast.error("CSV yuklab bo'lmadi")
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-gray-900">Javoblar</p>
          <p className="text-xs text-gray-500">
            {data ? `Jami ${fmtNumber(data.total)} ta` : "Ustunlar — formaning hozirgi savollari"}
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<Download className="h-3.5 w-3.5" />}
          loading={downloading}
          disabled={!data || data.total === 0}
          onClick={downloadCsv}
        >
          CSV yuklab olish
        </Button>
      </div>

      {isLoading && <Loading />}
      {isError && !data && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.items.length === 0 && (
        <Empty
          icon={<Inbox className="h-6 w-6" />}
          title="Hali javob yo'q"
          text="Forma havolasini tarqating — to'ldirilgan har bir javob shu yerda va «Leadlar» bo'limida paydo bo'ladi."
          action={
            <Button variant="secondary" icon={<Copy className="h-4 w-4" />} onClick={() => copyText(absoluteUrl(form.url))}>
              Havoladan nusxa olish
            </Button>
          }
        />
      )}
      {data && data.items.length > 0 && (
        <div className={isPlaceholderData ? 'overflow-x-auto opacity-60 transition-opacity' : 'overflow-x-auto'}>
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              <tr>
                <th className="whitespace-nowrap px-4 py-3">Sana</th>
                <th className="px-4 py-3">Lead</th>
                {form.fields.map((f) => (
                  <th key={f.id} className="min-w-[140px] max-w-[260px] px-4 py-3 normal-case tracking-normal" title={f.label}>
                    <span className="line-clamp-2">{f.label}</span>
                  </th>
                ))}
                {withUtm && <th className="px-4 py-3">UTM</th>}
                <th className="px-4 py-3"><span className="sr-only">Amallar</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {data.items.map((s) => (
                <tr key={s.id} className="align-top hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-3 text-gray-500">{fmtDateTime(s.created_at)}</td>
                  <td className="px-4 py-3">
                    {s.lead_id ? (
                      <Link
                        to={`/leads?lead=${s.lead_id}`}
                        className="group inline-flex max-w-[200px] items-start gap-1.5 text-gray-900"
                        title="Leadni ochish"
                      >
                        <UserSquare2 className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                        <span className="min-w-0">
                          <span className="block truncate font-medium group-hover:text-brand-700">{s.lead_name || 'Lead'}</span>
                          {s.lead_contact && <span className="block truncate text-xs text-gray-500">{s.lead_contact}</span>}
                        </span>
                      </Link>
                    ) : (
                      <span className="text-xs text-gray-400" title="Lead o'chirilgan">—</span>
                    )}
                  </td>
                  {form.fields.map((f) => {
                    const v = answerText(s, f.id)
                    return (
                      <td key={f.id} className="max-w-[260px] px-4 py-3 text-gray-700">
                        {v ? <span className="line-clamp-3 whitespace-pre-wrap break-words" title={v}>{v}</span> : <Dash />}
                      </td>
                    )
                  })}
                  {withUtm && (
                    <td className="max-w-[220px] px-4 py-3 text-xs text-gray-500">
                      {utmText(s.utm ?? {}) || <Dash />}
                    </td>
                  )}
                  <td className="px-2 py-2 text-right">
                    <button
                      type="button"
                      aria-label="Javobni o'chirish"
                      title="Javobni o'chirish"
                      disabled={remove.isPending}
                      onClick={() => { if (window.confirm("Bu javob butunlay o'chirilsinmi? Lead o'z joyida qoladi.")) remove.mutate(s.id) }}
                      className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && pages > 1 && (
        <div className="flex items-center justify-between border-t border-gray-100 px-4 py-3 text-sm text-gray-600">
          <span>{page} / {pages} sahifa</span>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} icon={<ChevronLeft className="h-4 w-4" />}>Oldingi</Button>
            <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Keyingi <ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>
      )}
    </Card>
  )
}
