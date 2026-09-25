import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { format, parseISO } from 'date-fns'
import { dashboardApi } from '@/api/dashboard'
import { Card, CardHeader, Empty, Loading, PageHeader, Select } from '@/components/ui'
import { StatusCard } from '@/components/StatusCard'
import { isAdmin, useAuth } from '@/lib/auth'
import { CHANNEL_LABELS, STATUS_LABELS, STATUSES } from '@/lib/labels'
import { fmtNumber } from '@/lib/format'
import type { LeadStatus } from '@/api/types'

function Kpi({ label, value, hint, accent }: { label: string; value: number; hint?: ReactNode; accent?: boolean }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className={accent ? 'mt-1 text-2xl font-semibold text-brand-700' : 'mt-1 text-2xl font-semibold text-gray-900'}>{fmtNumber(value)}</p>
      {hint && <p className="mt-0.5 text-xs text-gray-400">{hint}</p>}
    </Card>
  )
}

const FUNNEL_COLORS: Record<LeadStatus, string> = {
  new: 'bg-sky-500',
  contacted: 'bg-amber-500',
  trial: 'bg-violet-500',
  enrolled: 'bg-emerald-500',
  lost: 'bg-gray-400',
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [days, setDays] = useState(7)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['dashboard', days],
    queryFn: () => dashboardApi.get(days),
    refetchInterval: 60_000,
  })

  return (
    <>
      <PageHeader
        title="Bosh sahifa"
        subtitle="AI agent natijalari va sotuv voronkasi"
        action={
          <Select value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-40">
            <option value={1}>Bugun</option>
            <option value={7}>Oxirgi 7 kun</option>
            <option value={30}>Oxirgi 30 kun</option>
            <option value={90}>Oxirgi 90 kun</option>
          </Select>
        }
      />
      {isLoading && <Loading />}
      {isError && <Empty title="Ma'lumotni yuklab bo'lmadi" text="Server bilan aloqani tekshiring." />}
      {data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Bugungi suhbatlar" value={data.today.conversations} hint={`${fmtNumber(data.today.messages_in)} ta xabar`} />
            <Kpi label="Bugungi yangi leadlar" value={data.today.new_leads} />
            <Kpi label="Bugun qaynoq" value={data.today.hot} accent />
            <Kpi label="Kontakt qoldirganlar" value={data.totals.leads_with_contact} hint="tanlangan davrda" />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi label="Suhbatlar" value={data.totals.conversations} />
            <Kpi label="Kiruvchi xabarlar" value={data.totals.messages_in} />
            <Kpi label="AI javoblari" value={data.totals.ai_replies} />
            <Kpi label="Qaynoq leadlar" value={data.totals.hot} />
            <Kpi label="Sinov darsiga" value={data.totals.trial} />
            <Kpi label="O'qishga yozildi" value={data.totals.enrolled} accent />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Kunlar kesimida" subtitle="Suhbatlar va yangi leadlar" />
              <div className="h-72 px-2 py-4">
                {data.by_day.length === 0 ? (
                  <Empty title="Hali ma'lumot yo'q" />
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data.by_day} margin={{ left: -16, right: 12 }}>
                      <defs>
                        <linearGradient id="gConv" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#6366f1" stopOpacity={0.3} />
                          <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="gLead" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                          <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis dataKey="date" tickFormatter={(d: string) => format(parseISO(d), 'dd.MM')} tick={{ fontSize: 11, fill: '#6b7280' }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#6b7280' }} />
                      <Tooltip labelFormatter={(d) => format(parseISO(String(d)), 'dd.MM.yyyy')} />
                      <Area type="monotone" dataKey="conversations" name="Suhbatlar" stroke="#6366f1" fill="url(#gConv)" strokeWidth={2} />
                      <Area type="monotone" dataKey="leads" name="Leadlar" stroke="#10b981" fill="url(#gLead)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </Card>
            <StatusCard status={data.status} canEdit={isAdmin(user)} />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card>
              <CardHeader title="Sotuv voronkasi" subtitle="Leadlar holati bo'yicha" />
              <div className="space-y-3 px-5 py-4">
                {(() => {
                  const map = new Map(data.by_status.map((s) => [s.status, s.count]))
                  const max = Math.max(1, ...data.by_status.map((s) => s.count))
                  return STATUSES.map((st) => {
                    const count = map.get(st) ?? 0
                    return (
                      <div key={st}>
                        <div className="mb-1 flex justify-between text-xs">
                          <span className="font-medium text-gray-700">{STATUS_LABELS[st]}</span>
                          <span className="text-gray-500">{fmtNumber(count)}</span>
                        </div>
                        <div className="h-2 rounded-full bg-gray-100">
                          <div className={`h-2 rounded-full ${FUNNEL_COLORS[st]}`} style={{ width: `${(count / max) * 100}%` }} />
                        </div>
                      </div>
                    )
                  })
                })()}
              </div>
            </Card>
            <Card>
              <CardHeader title="Kanallar" subtitle="Suhbatlar soni" />
              <div className="space-y-3 px-5 py-4">
                {data.by_channel.length === 0 && <p className="text-sm text-gray-500">Hali suhbat yo'q</p>}
                {data.by_channel.map((c) => {
                  const total = Math.max(1, data.by_channel.reduce((s, x) => s + x.conversations, 0))
                  const pct = Math.round((c.conversations / total) * 100)
                  return (
                    <div key={c.channel}>
                      <div className="mb-1 flex justify-between text-xs">
                        <span className="font-medium text-gray-700">{CHANNEL_LABELS[c.channel] ?? c.channel}</span>
                        <span className="text-gray-500">{fmtNumber(c.conversations)} · {pct}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-gray-100">
                        <div className={c.channel === 'telegram' ? 'h-2 rounded-full bg-sky-500' : 'h-2 rounded-full bg-pink-500'} style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>
            <Card>
              <CardHeader title="Ommabop kurslar" subtitle="Mijozlar qiziqqan kurslar" />
              <div className="px-5 py-3">
                {data.top_courses.length === 0 ? (
                  <p className="py-2 text-sm text-gray-500">Hali ma'lumot yo'q</p>
                ) : (
                  <ul className="divide-y divide-gray-100">
                    {data.top_courses.map((c, i) => (
                      <li key={c.course} className="flex items-center justify-between py-2 text-sm">
                        <span className="flex items-center gap-2 text-gray-700">
                          <span className="w-4 text-xs text-gray-400">{i + 1}</span>
                          {c.course}
                        </span>
                        <span className="font-medium text-gray-900">{fmtNumber(c.count)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}
    </>
  )
}
