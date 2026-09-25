import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { format, parseISO } from 'date-fns'
import { BarChart3 } from 'lucide-react'
import { funnelApi } from '@/api/funnel'
import type { FunnelSource, FunnelStats } from '@/api/types'
import { Card, CardHeader, Empty, Loading, Select } from '@/components/ui'
import { FUNNEL_SOURCE_LABELS, FUNNEL_STAT_LABELS } from '@/lib/labels'
import { fmtNumber } from '@/lib/format'
import { cn } from '@/lib/cn'
import { Bar, ErrorState, type FunnelTabProps } from './shared'

const SOURCE_FILL: Record<FunnelSource, string> = {
  instagram: 'fill-pink-500',
  telegram_channel: 'fill-sky-500',
  telegram_direct: 'fill-brand-500',
}

function Kpi({ label, value, className }: { label: string; value: number; className?: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className={cn('mt-1 text-2xl font-semibold text-gray-900', className)}>{fmtNumber(value)}</p>
    </Card>
  )
}

function pct(part: number, whole: number): string {
  if (whole <= 0) return '—'
  return `${Math.round((part / whole) * 100)}%`
}

function StepFunnel({ steps }: { steps: FunnelStats['steps'] }) {
  const top = steps[0]?.count ?? 0
  const max = Math.max(1, ...steps.map((s) => s.count))
  if (top === 0) {
    return <Empty icon={<BarChart3 className="h-6 w-6" />} title="Bu davrda hali hech kim kirmagan" text="Kalit so'z bilan izoh yozganlar yoki botga kirganlar shu yerda ko'rinadi." />
  }
  return (
    <div className="space-y-4 px-5 py-4">
      {steps.map((s, i) => {
        const prev = i > 0 ? steps[i - 1].count : null
        return (
          <div key={s.key}>
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
              <span className="font-medium text-gray-700">{s.label || FUNNEL_STAT_LABELS[s.key] || s.key}</span>
              <span className="text-gray-500">
                <span className="font-semibold text-gray-900">{fmtNumber(s.count)}</span>
                {i > 0 && (
                  <>
                    {' · '}jamidan {pct(s.count, top)}
                    {prev !== null && <> · oldingidan {pct(s.count, prev)}</>}
                  </>
                )}
              </span>
            </div>
            <Bar value={s.count} max={max} className="fill-brand-500" />
          </div>
        )
      })}
    </div>
  )
}

function BySource({ rows }: { rows: FunnelStats['by_source'] }) {
  const total = rows.reduce((sum, r) => sum + r.count, 0)
  if (total === 0) return <p className="px-5 py-4 text-sm text-gray-500">Hali ma'lumot yo'q</p>
  return (
    <div className="space-y-3 px-5 py-4">
      {rows.map((r) => (
        <div key={r.source}>
          <div className="mb-1 flex justify-between text-xs">
            <span className="font-medium text-gray-700">{FUNNEL_SOURCE_LABELS[r.source] ?? r.source}</span>
            <span className="text-gray-500">{fmtNumber(r.count)} · {pct(r.count, total)}</span>
          </div>
          <Bar value={r.count} max={total} className={SOURCE_FILL[r.source] ?? 'fill-gray-400'} />
        </div>
      ))}
    </div>
  )
}

export function StatsTab({ funnel }: FunnelTabProps) {
  const [days, setDays] = useState(30)
  const funnelId = funnel?.id
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['funnel', 'stats', funnelId ?? 'all', days],
    queryFn: () => funnelApi.stats(days, funnelId),
    refetchInterval: 60_000,
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-gray-500">
          {funnel ? `«${funnel.name}»` : 'Barcha voronkalar'}: izohdan suhbatgacha har bir bosqichga nechta odam yetib keldi
        </p>
        <div className="w-44">
          <Select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>Bugun</option>
            <option value={7}>Oxirgi 7 kun</option>
            <option value={30}>Oxirgi 30 kun</option>
            <option value={90}>Oxirgi 90 kun</option>
          </Select>
        </div>
      </div>

      {isLoading && <Loading />}
      {isError && <Card><ErrorState error={error} onRetry={() => refetch()} /></Card>}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Kpi label="Bugungi suhbatlar" value={data.bookings.today} className="text-brand-700" />
            <Kpi label="Belgilangan" value={data.bookings.scheduled} />
            <Kpi label="Keldi" value={data.bookings.attended} className="text-emerald-700" />
            <Kpi label="Kelmadi" value={data.bookings.no_show} className="text-rose-700" />
            <Kpi label="Bekor qilingan" value={data.bookings.cancelled} className="text-gray-500" />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Voronka bosqichlari" subtitle="Konversiya: jami kirganlardan va oldingi bosqichdan necha foiz" />
              <StepFunnel steps={data.steps} />
            </Card>
            <Card>
              <CardHeader title="Manbalar" subtitle="Voronkaga qayerdan kelishgan" />
              <BySource rows={data.by_source} />
            </Card>
          </div>

          <Card>
            <CardHeader title="Kunlar kesimida" subtitle="Yangi kirganlar, qo'llanma olganlar va suhbatga yozilganlar" />
            <div className="h-72 px-2 py-4 text-xs">
              {data.by_day.length === 0 ? (
                <Empty title="Hali ma'lumot yo'q" />
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data.by_day} margin={{ left: -16, right: 12 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="date" tickFormatter={(d: string) => format(parseISO(d), 'dd.MM')} tick={{ fontSize: 11, fill: '#6b7280' }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#6b7280' }} />
                    <Tooltip labelFormatter={(d) => format(parseISO(String(d)), 'dd.MM.yyyy')} />
                    <Legend />
                    <Area type="monotone" dataKey="entries" name="Kirganlar" stroke="#6366f1" fill="#6366f1" fillOpacity={0.12} strokeWidth={2} />
                    <Area type="monotone" dataKey="pdf" name="Qo'llanma oldi" stroke="#0ea5e9" fill="#0ea5e9" fillOpacity={0.12} strokeWidth={2} />
                    <Area type="monotone" dataKey="bookings" name="Suhbatga yozildi" stroke="#10b981" fill="#10b981" fillOpacity={0.12} strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
