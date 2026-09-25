import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { addDays, format, isToday, parseISO } from 'date-fns'
import { BellRing, CalendarDays, Pencil, Phone, StickyNote } from 'lucide-react'
import { funnelApi, type BookingFilters } from '@/api/funnel'
import { errorMessage } from '@/api/client'
import type { BookingOut, BookingPatch, BookingStatus } from '@/api/types'
import { Badge, Button, Card, Empty, Input, Label, Loading, Select, Textarea } from '@/components/ui'
import { BOOKING_STATUS_LABELS, BOOKING_STATUSES, gradeLabel } from '@/lib/labels'
import { fmtDateTime, fmtDayTitle } from '@/lib/format'
import { cn } from '@/lib/cn'
import { ErrorState, LeadLink } from './shared'

const ymd = (d: Date) => format(d, 'yyyy-MM-dd')

/** Status dot next to the time (the select itself stays neutral). */
const STATUS_DOT: Record<BookingStatus, string> = {
  scheduled: 'bg-sky-500',
  attended: 'bg-emerald-500',
  no_show: 'bg-rose-500',
  cancelled: 'bg-gray-300',
}

function NoteEditor({ booking, saving, onSave }: {
  booking: BookingOut
  saving: boolean
  onSave: (note: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => { setText(booking.note ?? ''); setEditing(true) }}
        className="group flex max-w-full items-start gap-1.5 text-left text-xs text-gray-500 hover:text-gray-800"
      >
        <StickyNote className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {booking.note ? (
          <span className="whitespace-pre-wrap text-gray-700">{booking.note}</span>
        ) : (
          <span>Izoh qo'shish</span>
        )}
        {booking.note && <Pencil className="mt-0.5 hidden h-3 w-3 shrink-0 group-hover:block" />}
      </button>
    )
  }
  return (
    <div className="space-y-2">
      <Textarea
        rows={2}
        autoFocus
        maxLength={2000}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Masalan: ota-onasi bilan keladi, ingliz tiliga qiziqadi"
      />
      <div className="flex gap-2">
        <Button
          size="sm"
          loading={saving}
          disabled={text.trim() === (booking.note ?? '').trim()}
          onClick={() => onSave(text.trim())}
        >
          Saqlash
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Bekor qilish</Button>
      </div>
    </div>
  )
}

function BookingRow({ booking }: { booking: BookingOut }) {
  const qc = useQueryClient()
  const update = useMutation({
    mutationFn: (body: BookingPatch) => funnelApi.updateBooking(booking.id, body),
    onSuccess: (fresh) => {
      qc.setQueriesData<BookingOut[]>({ queryKey: ['funnel', 'bookings'] }, (old) =>
        old?.map((b) => (b.id === fresh.id ? fresh : b)))
      qc.invalidateQueries({ queryKey: ['funnel', 'stats'] })
      qc.invalidateQueries({ queryKey: ['funnel', 'entries'] })
      toast.success('Saqlandi')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const grade = gradeLabel(booking.grade)

  return (
    <li className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start">
      <div className="flex w-20 shrink-0 items-center gap-2" title={BOOKING_STATUS_LABELS[booking.status]}>
        <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', STATUS_DOT[booking.status])} />
        <p className={cn('text-lg font-semibold tabular-nums', booking.status === 'cancelled' ? 'text-gray-400 line-through' : 'text-gray-900')}>
          {format(parseISO(booking.starts_at), 'HH:mm')}
        </p>
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="font-medium text-gray-900">{booking.full_name || 'Ismi kiritilmagan'}</p>
          {grade && <Badge>{grade}</Badge>}
          {booking.reminder_sent_at && (
            <span className="inline-flex items-center gap-1 text-xs text-gray-400" title={`Eslatma yuborilgan: ${fmtDateTime(booking.reminder_sent_at)}`}>
              <BellRing className="h-3.5 w-3.5" /> Eslatildi
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {booking.phone ? (
            <a href={`tel:${booking.phone}`} className="inline-flex items-center gap-1 text-gray-700 hover:text-brand-700">
              <Phone className="h-3.5 w-3.5 text-gray-400" /> {booking.phone}
            </a>
          ) : (
            <span className="text-gray-300">Telefon yo'q</span>
          )}
          <LeadLink leadId={booking.lead_id} />
        </div>
        <NoteEditor
          key={booking.note ?? ''}
          booking={booking}
          saving={update.isPending && update.variables?.note !== undefined}
          onSave={(note) => update.mutate({ note })}
        />
      </div>
      <div className="shrink-0 sm:w-44">
        <Select
          aria-label="Suhbat holati"
          value={booking.status}
          disabled={update.isPending}
          onChange={(e) => update.mutate({ status: e.target.value as BookingStatus })}
        >
          {BOOKING_STATUSES.map((s) => (
            <option key={s} value={s} disabled={s === 'scheduled' && booking.status !== 'scheduled'}>{BOOKING_STATUS_LABELS[s]}</option>
          ))}
        </Select>
      </div>
    </li>
  )
}

export function BookingsTab() {
  const [dateFrom, setDateFrom] = useState(() => ymd(new Date()))
  const [dateTo, setDateTo] = useState(() => ymd(addDays(new Date(), 7)))
  const [status, setStatus] = useState<BookingStatus | ''>('')
  const rangeOk = Boolean(dateFrom && dateTo && dateFrom <= dateTo)

  const filters: BookingFilters = { date_from: dateFrom, date_to: dateTo, status }
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['funnel', 'bookings', filters],
    queryFn: () => funnelApi.bookings(filters),
    enabled: rangeOk,
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
  })

  const days = useMemo(() => {
    const groups = new Map<string, BookingOut[]>()
    const sorted = [...(data ?? [])].sort((a, b) => parseISO(a.starts_at).getTime() - parseISO(b.starts_at).getTime())
    for (const b of sorted) {
      const key = ymd(parseISO(b.starts_at))
      const list = groups.get(key)
      if (list) list.push(b)
      else groups.set(key, [b])
    }
    return Array.from(groups.entries())
  }, [data])

  function resetRange() {
    setDateFrom(ymd(new Date()))
    setDateTo(ymd(addDays(new Date(), 7)))
  }

  return (
    <div className="space-y-4">
      <Card className="p-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_auto] lg:items-end">
          <div>
            <Label>Sanadan</Label>
            <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div>
            <Label>Sanagacha</Label>
            <Input type="date" value={dateTo} min={dateFrom} onChange={(e) => setDateTo(e.target.value)} />
          </div>
          <div>
            <Label>Holat</Label>
            <Select value={status} onChange={(e) => setStatus(e.target.value as BookingStatus | '')}>
              <option value="">Barcha holatlar</option>
              {BOOKING_STATUSES.map((s) => <option key={s} value={s}>{BOOKING_STATUS_LABELS[s]}</option>)}
            </Select>
          </div>
          <Button variant="secondary" onClick={resetRange}>Bugundan 7 kun</Button>
        </div>
        {!rangeOk && <p className="mt-2 text-xs text-red-600">Boshlanish sanasi tugash sanasidan keyin bo'lmasligi kerak.</p>}
      </Card>

      {rangeOk && isLoading && <Card><Loading /></Card>}
      {rangeOk && isError && <Card><ErrorState error={error} onRetry={() => refetch()} /></Card>}
      {rangeOk && data && days.length === 0 && (
        <Card>
          <Empty
            icon={<CalendarDays className="h-6 w-6" />}
            title="Bu oraliqda suhbat yo'q"
            text="Mijozlar botdagi «Suhbatga ro'yxatdan o'tish» tugmasi orqali yoziladi. Boshqa sana yoki holatni tanlab ko'ring."
          />
        </Card>
      )}
      {rangeOk && days.map(([day, list]) => (
        <Card key={day} className="overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-gray-100 bg-gray-50 px-5 py-3">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
              {fmtDayTitle(day)}
              {isToday(parseISO(day)) && <Badge className="bg-brand-50 text-brand-700 ring-brand-200">Bugun</Badge>}
            </h3>
            <span className="text-xs text-gray-500">{list.length} ta</span>
          </div>
          <ul className="divide-y divide-gray-100">
            {list.map((b) => <BookingRow key={b.id} booking={b} />)}
          </ul>
        </Card>
      ))}
    </div>
  )
}
