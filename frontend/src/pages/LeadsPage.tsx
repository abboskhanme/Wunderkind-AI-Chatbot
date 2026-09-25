import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ChevronLeft, ChevronRight, Download, MessagesSquare, Search, Trash2, UserSquare2 } from 'lucide-react'
import { leadsApi, type LeadFilters } from '@/api/leads'
import { downloadFile, errorMessage } from '@/api/client'
import type { LeadOut } from '@/api/types'
import { Button, Card, Drawer, Empty, Input, Loading, PageHeader, Select } from '@/components/ui'
import { ChannelIcon, ScoreBadge, StatusBadge, leadTitle } from '@/components/LeadBadges'
import { ChatThread } from '@/components/ChatThread'
import { LeadCard } from '@/components/LeadCard'
import { isAdmin, useAuth } from '@/lib/auth'
import { STATUS_LABELS, STATUSES } from '@/lib/labels'
import { fmtDateTime, fmtNumber } from '@/lib/format'

const PAGE_SIZE = 50

function LeadDrawer({ leadId, onClose }: { leadId: string | null; onClose: () => void }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const { data: lead, isLoading } = useQuery({
    queryKey: ['lead', leadId],
    queryFn: () => leadsApi.get(leadId!),
    enabled: Boolean(leadId),
  })
  const remove = useMutation({
    mutationFn: () => leadsApi.remove(leadId!),
    onSuccess: () => {
      toast.success("Lead o'chirildi")
      qc.invalidateQueries({ queryKey: ['leads'] })
      onClose()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <Drawer
      open={Boolean(leadId)}
      onClose={onClose}
      title={lead ? (
        <span className="flex items-center gap-2">
          <ChannelIcon channel={lead.channel} />
          <span className="truncate">{leadTitle(lead)}</span>
        </span>
      ) : 'Lead'}
    >
      {isLoading || !lead ? (
        <Loading />
      ) : (
        <div className="grid gap-0 md:grid-cols-[1fr_280px]">
          <div className="border-b border-gray-100 md:border-b-0 md:border-r">
            <div className="flex items-center justify-between px-4 py-3">
              <p className="text-sm font-semibold text-gray-900">Yozishma</p>
              <Link to={`/inbox/${lead.id}`} className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700">
                <MessagesSquare className="h-3.5 w-3.5" /> Suhbatlarda ochish
              </Link>
            </div>
            <ChatThread messages={lead.messages} className="max-h-[70vh] min-h-40 overflow-y-auto bg-gray-50 px-4 py-4" />
          </div>
          <div className="space-y-4 p-4">
            <LeadCard lead={lead} />
            {isAdmin(user) && (
              <Button
                variant="ghost"
                className="w-full text-red-600 hover:bg-red-50"
                icon={<Trash2 className="h-4 w-4" />}
                loading={remove.isPending}
                onClick={() => {
                  if (window.confirm("Lead va butun yozishma o'chiriladi. Davom etasizmi?")) remove.mutate()
                }}
              >
                Leadni o'chirish
              </Button>
            )}
          </div>
        </div>
      )}
    </Drawer>
  )
}

export default function LeadsPage() {
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [minScore, setMinScore] = useState('')
  const [hasContact, setHasContact] = useState(false)
  const [page, setPage] = useState(1)
  const [openId, setOpenId] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])
  useEffect(() => setPage(1), [status, channel, debounced, minScore, hasContact])

  const filters: LeadFilters = {
    status, channel, search: debounced,
    min_score: minScore ? Number(minScore) : undefined,
    has_contact: hasContact || undefined,
    page, page_size: PAGE_SIZE,
  }
  const { data, isLoading } = useQuery({
    queryKey: ['leads', filters],
    queryFn: () => leadsApi.list(filters),
    placeholderData: (prev) => prev,
  })
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  async function exportCsv() {
    setExporting(true)
    try {
      await downloadFile(leadsApi.exportUrl(filters), `leadlar-${new Date().toISOString().slice(0, 10)}.csv`)
    } catch {
      toast.error("CSV yuklab bo'lmadi")
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Leadlar"
        subtitle={data ? `Jami ${fmtNumber(data.total)} ta` : undefined}
        action={<Button variant="secondary" icon={<Download className="h-4 w-4" />} loading={exporting} onClick={exportCsv}>CSV yuklab olish</Button>}
      />

      <Card className="mb-4 p-3">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <div className="relative lg:col-span-2">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Ism, telefon, @username, kurs..." className="pl-9" />
          </div>
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Barcha holatlar</option>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
          </Select>
          <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">Barcha kanallar</option>
            <option value="instagram">Instagram</option>
            <option value="telegram">Telegram</option>
          </Select>
          <div className="flex items-center gap-2">
            <Select value={minScore} onChange={(e) => setMinScore(e.target.value)}>
              <option value="">Har qanday ball</option>
              <option value="40">40+ (qiziqqan)</option>
              <option value="70">70+ (qaynoq)</option>
            </Select>
            <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs text-gray-600">
              <input type="checkbox" checked={hasContact} onChange={(e) => setHasContact(e.target.checked)} className="rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
              Telefoni bor
            </label>
          </div>
        </div>
      </Card>

      <Card className="overflow-hidden">
        {isLoading && <Loading />}
        {data && data.items.length === 0 && (
          <Empty icon={<UserSquare2 className="h-6 w-6" />} title="Leadlar topilmadi" text="Filtrlarni o'zgartiring yoki mijozlar yozishini kuting." />
        )}
        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3">Mijoz</th>
                  <th className="px-4 py-3">Telefon</th>
                  <th className="px-4 py-3">Kurs</th>
                  <th className="px-4 py-3">Holat</th>
                  <th className="px-4 py-3">Ball</th>
                  <th className="hidden px-4 py-3 lg:table-cell">Mas'ul</th>
                  <th className="hidden px-4 py-3 md:table-cell">Yangilangan</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {data.items.map((l: LeadOut) => (
                  <tr key={l.id} onClick={() => setOpenId(l.id)} className="cursor-pointer hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <ChannelIcon channel={l.channel} />
                        <div className="min-w-0">
                          <p className="truncate font-medium text-gray-900">{leadTitle(l)}</p>
                          {l.username && l.name && <p className="truncate text-xs text-gray-500">@{l.username}</p>}
                        </div>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-gray-700">{l.contact || <span className="text-gray-300">—</span>}</td>
                    <td className="max-w-[180px] truncate px-4 py-3 text-gray-700">{l.course_interest || <span className="text-gray-300">—</span>}</td>
                    <td className="px-4 py-3"><StatusBadge status={l.status} /></td>
                    <td className="px-4 py-3"><ScoreBadge score={l.lead_score} /></td>
                    <td className="hidden px-4 py-3 text-gray-600 lg:table-cell">{l.assigned_to_name || <span className="text-gray-300">—</span>}</td>
                    <td className="hidden whitespace-nowrap px-4 py-3 text-gray-500 md:table-cell">{fmtDateTime(l.updated_at)}</td>
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

      <LeadDrawer leadId={openId} onClose={() => setOpenId(null)} />
    </>
  )
}
