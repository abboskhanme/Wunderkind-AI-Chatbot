import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { ChevronLeft, ChevronRight, ListChecks, Search } from 'lucide-react'
import { funnelApi, type FunnelEntryFilters } from '@/api/funnel'
import type { FunnelEntryOut, FunnelSource, FunnelStep } from '@/api/types'
import { Badge, Button, Card, Empty, Input, Loading, Select } from '@/components/ui'
import { FUNNEL_SOURCE_LABELS, FUNNEL_SOURCES, FUNNEL_STEP_LABELS, FUNNEL_STEPS, gradeLabel } from '@/lib/labels'
import { fmtNumber } from '@/lib/format'
import { BookingStatusBadge, ErrorState, FunnelBadge, LeadLink, SourceBadge, StepBadge, type FunnelTabProps } from './shared'

const PAGE_SIZE = 50

function Dash() {
  return <span className="text-gray-300">—</span>
}

function Person({ e }: { e: FunnelEntryOut }) {
  const handles = [
    e.tg_username ? `TG @${e.tg_username}` : null,
    e.ig_username ? `IG @${e.ig_username}` : null,
  ].filter(Boolean)
  return (
    <div className="min-w-0">
      <p className="truncate font-medium text-gray-900">{e.full_name || (e.ig_username ? `@${e.ig_username}` : e.tg_username ? `@${e.tg_username}` : 'Nomsiz')}</p>
      {handles.length > 0 && <p className="truncate text-xs text-gray-500">{handles.join(' · ')}</p>}
      <LeadLink leadId={e.lead_id} className="mt-0.5" />
    </div>
  )
}

export function EntriesTab({ funnel }: FunnelTabProps) {
  const funnelId = funnel?.id
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [source, setSource] = useState<FunnelSource | ''>('')
  const [step, setStep] = useState<FunnelStep | ''>('')
  const [page, setPage] = useState(1)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])
  useEffect(() => setPage(1), [debounced, source, step, funnelId])

  const filters: FunnelEntryFilters = { funnel_id: funnelId, source, step, search: debounced, page, page_size: PAGE_SIZE }
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['funnel', 'entries', filters],
    queryFn: () => funnelApi.entries(filters),
    placeholderData: (prev) => prev,
  })
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  const filtered = Boolean(debounced || source || step)

  return (
    <div className="space-y-4">
      <Card className="p-3">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div className="relative lg:col-span-2">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Ism, telefon, @username..." className="pl-9" />
          </div>
          <Select value={source} onChange={(e) => setSource(e.target.value as FunnelSource | '')}>
            <option value="">Barcha manbalar</option>
            {FUNNEL_SOURCES.map((s) => <option key={s} value={s}>{FUNNEL_SOURCE_LABELS[s]}</option>)}
          </Select>
          <Select value={step} onChange={(e) => setStep(e.target.value as FunnelStep | '')}>
            <option value="">Barcha bosqichlar</option>
            {FUNNEL_STEPS.map((s) => <option key={s} value={s}>{FUNNEL_STEP_LABELS[s]}</option>)}
          </Select>
        </div>
      </Card>

      <Card className="overflow-hidden">
        {data && (
          <div className="border-b border-gray-100 px-4 py-2.5 text-xs text-gray-500">Jami {fmtNumber(data.total)} ta</div>
        )}
        {isLoading && <Loading />}
        {isError && !data && <ErrorState error={error} onRetry={() => refetch()} />}
        {data && data.items.length === 0 && (
          <Empty
            icon={<ListChecks className="h-6 w-6" />}
            title={filtered ? 'Hech narsa topilmadi' : "Hali voronkaga hech kim kirmagan"}
            text={filtered ? "Filtrlarni o'zgartiring." : "Kalit so'z bilan izoh yozgan yoki botni ishga tushirgan har bir odam shu ro'yxatga tushadi."}
          />
        )}
        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3">Ism-familiya</th>
                  <th className="px-4 py-3">Telefon</th>
                  <th className="px-4 py-3">Sinf</th>
                  <th className="px-4 py-3">{funnel ? 'Manba' : 'Manba / voronka'}</th>
                  <th className="px-4 py-3">Bosqich</th>
                  <th className="px-4 py-3">Suhbat</th>
                  <th className="hidden px-4 py-3 lg:table-cell" title="Yuborilgan sotuv xabarlari">Xabarlar</th>
                  <th className="hidden px-4 py-3 md:table-cell">Kirgan</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {data.items.map((e) => (
                  <tr key={e.id} className="hover:bg-gray-50">
                    <td className="max-w-[220px] px-4 py-3"><Person e={e} /></td>
                    <td className="whitespace-nowrap px-4 py-3 text-gray-700">
                      {e.phone ? <a href={`tel:${e.phone}`} className="hover:text-brand-700">{e.phone}</a> : <Dash />}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-gray-700">{gradeLabel(e.grade) ?? <Dash />}</td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="flex flex-col items-start gap-1">
                        <SourceBadge source={e.source} />
                        {!funnel && <FunnelBadge name={e.funnel_name} />}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="flex flex-col items-start gap-1">
                        <StepBadge step={e.step} />
                        {e.opted_out && <Badge className="bg-rose-50 text-rose-700 ring-rose-200">Botni to'xtatgan</Badge>}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {e.booking ? (
                        <div className="space-y-1">
                          <p className="text-gray-700">{format(parseISO(e.booking.starts_at), 'dd.MM HH:mm')}</p>
                          <BookingStatusBadge status={e.booking.status} />
                        </div>
                      ) : <Dash />}
                    </td>
                    <td className="hidden whitespace-nowrap px-4 py-3 text-gray-700 lg:table-cell">{fmtNumber(e.messages_sent)}</td>
                    <td className="hidden whitespace-nowrap px-4 py-3 text-gray-500 md:table-cell">{format(parseISO(e.created_at), 'dd.MM.yy HH:mm')}</td>
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
    </div>
  )
}
