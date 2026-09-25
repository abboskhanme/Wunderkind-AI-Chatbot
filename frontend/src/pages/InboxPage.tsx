import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ArrowLeft, Bot, Info, MessagesSquare, Search, Send, StickyNote } from 'lucide-react'
import { leadsApi } from '@/api/leads'
import { errorMessage } from '@/api/client'
import type { InboxItem, ReplyWindow } from '@/api/types'
import { Badge, Button, Empty, Input, Loading, Select, Spinner, Textarea, Toggle } from '@/components/ui'
import { ChannelIcon, ScoreBadge, StatusBadge, leadTitle } from '@/components/LeadBadges'
import { ChatThread } from '@/components/ChatThread'
import { LeadCard } from '@/components/LeadCard'
import { ROLE_LABELS, WINDOW_LABELS } from '@/lib/labels'
import { fmtShort } from '@/lib/format'
import { cn } from '@/lib/cn'

const POLL_MS = 5000

/** Fallback when the lead is not in the current (filtered) inbox list. */
function windowFrom(lastCustomerAt: string | null): ReplyWindow {
  if (!lastCustomerAt) return 'closed'
  const hours = (Date.now() - new Date(lastCustomerAt).getTime()) / 3_600_000
  if (hours <= 24) return 'open'
  if (hours <= 24 * 7) return 'human_agent'
  return 'closed'
}

const WINDOW_STYLE: Record<ReplyWindow, string> = {
  open: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  human_agent: 'bg-amber-50 text-amber-700 ring-amber-200',
  closed: 'bg-gray-100 text-gray-500 ring-gray-200',
}

function InboxRow({ item, active }: { item: InboxItem; active: boolean }) {
  return (
    <Link
      to={`/inbox/${item.lead_id}`}
      className={cn('flex gap-3 border-b border-gray-100 px-4 py-3 transition-colors', active ? 'bg-brand-50' : 'hover:bg-gray-50')}
    >
      <ChannelIcon channel={item.channel} className="mt-0.5 h-7 w-7 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className={cn('truncate text-sm', item.unread ? 'font-semibold text-gray-900' : 'font-medium text-gray-800')}>{leadTitle(item)}</p>
          <span className="shrink-0 text-[11px] text-gray-400">{fmtShort(item.last_message_at)}</span>
        </div>
        <div className="mt-0.5 flex items-center justify-between gap-2">
          <p className={cn('truncate text-xs', item.unread ? 'text-gray-800' : 'text-gray-500')}>
            {item.last_message_role && item.last_message_role !== 'user' && (
              <span className="text-gray-400">{ROLE_LABELS[item.last_message_role]}: </span>
            )}
            {item.last_message || '—'}
          </p>
          {item.unread > 0 && (
            <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-brand-600 px-1.5 text-[11px] font-semibold text-white">{item.unread}</span>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          <StatusBadge status={item.status} />
          {item.lead_score >= 70 && <ScoreBadge score={item.lead_score} />}
          {item.window !== 'open' && <Badge className={WINDOW_STYLE[item.window]}>{WINDOW_LABELS[item.window]}</Badge>}
        </div>
      </div>
    </Link>
  )
}

function Conversation({ leadId, window }: { leadId: string; window: ReplyWindow | undefined }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [noteMode, setNoteMode] = useState(false)
  const [showCard, setShowCard] = useState(false)

  const { data: lead, isLoading, isError } = useQuery({
    queryKey: ['lead', leadId],
    queryFn: () => leadsApi.get(leadId),
    refetchInterval: POLL_MS,
  })
  const bot = useQuery({ queryKey: ['lead-bot', leadId], queryFn: () => leadsApi.botState(leadId), refetchInterval: 30_000 })

  // Mark as read on open and whenever new messages arrive while it is open.
  const msgCount = lead?.messages.length ?? 0
  useEffect(() => {
    if (!msgCount) return
    leadsApi.markRead(leadId).then(() => qc.invalidateQueries({ queryKey: ['inbox'] })).catch(() => undefined)
  }, [leadId, msgCount, qc])

  useEffect(() => {
    setText('')
    setNoteMode(false)
  }, [leadId])

  const reply = useMutation({
    mutationFn: (t: string) => leadsApi.reply(leadId, t),
    onSuccess: (res) => {
      if (!res.sent) {
        toast.error(res.error || 'Xabar yuborilmadi')
        return
      }
      setText('')
      toast.success('Yuborildi. AI bu suhbatda vaqtincha jim turadi.')
      qc.invalidateQueries({ queryKey: ['lead', leadId] })
      qc.invalidateQueries({ queryKey: ['lead-bot', leadId] })
      qc.invalidateQueries({ queryKey: ['inbox'] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const note = useMutation({
    mutationFn: (t: string) => leadsApi.addNote(leadId, t),
    onSuccess: () => {
      setText('')
      qc.invalidateQueries({ queryKey: ['lead', leadId] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const toggleBot = useMutation({
    mutationFn: (enabled: boolean) => leadsApi.setBot(leadId, enabled),
    onSuccess: (res) => {
      qc.setQueryData(['lead-bot', leadId], res)
      toast.success(res.paused ? "AI bu suhbatda o'chirildi" : 'AI bu suhbatda yoqildi')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  if (isLoading) return <div className="flex flex-1 items-center justify-center"><Spinner /></div>
  if (isError || !lead) return <div className="flex-1"><Empty title="Suhbat topilmadi" /></div>

  const effectiveWindow: ReplyWindow = lead.channel === 'telegram' ? 'open' : window ?? windowFrom(lead.last_customer_at)
  const replyDisabled = !noteMode && effectiveWindow === 'closed'

  function submit(e: FormEvent) {
    e.preventDefault()
    const t = text.trim()
    if (!t) return
    if (noteMode) note.mutate(t)
    else reply.mutate(t)
  }

  return (
    <>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-3">
          <button className="rounded-lg p-1 text-gray-500 hover:bg-gray-100 md:hidden" onClick={() => navigate('/inbox')}>
            <ArrowLeft className="h-5 w-5" />
          </button>
          <ChannelIcon channel={lead.channel} className="h-8 w-8" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-gray-900">{leadTitle(lead)}</p>
            <p className="truncate text-xs text-gray-500">
              {lead.username ? `@${lead.username}` : lead.external_id}
              {lead.contact ? ` · ${lead.contact}` : ''}
            </p>
          </div>
          <div className="flex items-center gap-2" title="AI shu suhbatda avtomatik javob beradimi">
            <Bot className={cn('h-4 w-4', bot.data?.paused ? 'text-gray-400' : 'text-brand-600')} />
            <span className="hidden text-xs font-medium text-gray-600 sm:inline">AI javob</span>
            <Toggle checked={bot.data ? !bot.data.paused : true} disabled={bot.isLoading || toggleBot.isPending} onChange={(v) => toggleBot.mutate(v)} />
          </div>
          <button className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 xl:hidden" onClick={() => setShowCard(true)} title="Lead ma'lumotlari">
            <Info className="h-5 w-5" />
          </button>
        </div>

        <ChatThread messages={lead.messages} className="flex-1 overflow-y-auto bg-gray-50 px-4 py-4" />

        <form onSubmit={submit} className="border-t border-gray-200 bg-white p-3">
          {replyDisabled && (
            <p className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
              Instagram javob oynasi yopilgan: mijozning oxirgi xabaridan 7 kundan ko'p vaqt o'tgan. Instagram ilovasidan yoki telefon orqali bog'laning. Izoh qoldirishingiz mumkin.
            </p>
          )}
          {!noteMode && effectiveWindow === 'human_agent' && (
            <p className="mb-2 text-xs text-amber-700">24 soat o'tgan — xabar «jonli operator» (HUMAN_AGENT) belgisi bilan yuboriladi.</p>
          )}
          <div className="mb-2 flex gap-1">
            <button type="button" onClick={() => setNoteMode(false)} className={cn('rounded-md px-2.5 py-1 text-xs font-medium', !noteMode ? 'bg-brand-50 text-brand-700' : 'text-gray-500 hover:bg-gray-100')}>
              Javob yozish
            </button>
            <button type="button" onClick={() => setNoteMode(true)} className={cn('inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium', noteMode ? 'bg-amber-50 text-amber-700' : 'text-gray-500 hover:bg-gray-100')}>
              <StickyNote className="h-3 w-3" /> Ichki izoh
            </button>
          </div>
          <div className="flex items-end gap-2">
            <Textarea
              rows={2}
              value={text}
              disabled={replyDisabled}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  submit(e as unknown as FormEvent)
                }
              }}
              placeholder={noteMode ? "Faqat xodimlar ko'radigan izoh..." : 'Mijozga javob... (Enter — yuborish, Shift+Enter — yangi qator)'}
              className={cn('resize-none', noteMode && 'bg-amber-50/50')}
            />
            <Button type="submit" disabled={replyDisabled || !text.trim()} loading={reply.isPending || note.isPending} icon={<Send className="h-4 w-4" />}>
              <span className="hidden sm:inline">{noteMode ? 'Saqlash' : 'Yuborish'}</span>
            </Button>
          </div>
        </form>
      </div>

      <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-gray-200 bg-white p-4 xl:block">
        <LeadCard lead={lead} />
      </aside>
      {showCard && (
        <div className="fixed inset-0 z-50 flex justify-end bg-gray-900/30 xl:hidden" onClick={() => setShowCard(false)}>
          <div className="h-full w-full max-w-sm overflow-y-auto bg-white p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-semibold">Lead ma'lumotlari</p>
              <Button variant="ghost" size="sm" onClick={() => setShowCard(false)}>Yopish</Button>
            </div>
            <LeadCard lead={lead} />
          </div>
        </div>
      )}
    </>
  )
}

export default function InboxPage() {
  const { leadId } = useParams()
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [channel, setChannel] = useState('')
  const [onlyUnread, setOnlyUnread] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  const { data, isLoading } = useQuery({
    queryKey: ['inbox', debounced, channel, onlyUnread],
    queryFn: () => leadsApi.inbox({ search: debounced, channel, only_unread: onlyUnread }),
    refetchInterval: POLL_MS,
  })

  const selected = data?.find((i) => i.lead_id === leadId)

  return (
    <div className="flex h-full">
      <div className={cn('w-full shrink-0 flex-col border-r border-gray-200 bg-white md:flex md:w-80', leadId ? 'hidden' : 'flex')}>
        <div className="space-y-2 border-b border-gray-200 p-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Ism, @username, telefon..." className="pl-9" />
          </div>
          <div className="flex gap-2">
            <Select value={channel} onChange={(e) => setChannel(e.target.value)} className="py-1.5 text-xs">
              <option value="">Barcha kanallar</option>
              <option value="instagram">Instagram</option>
              <option value="telegram">Telegram</option>
            </Select>
            <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs text-gray-600">
              <input type="checkbox" checked={onlyUnread} onChange={(e) => setOnlyUnread(e.target.checked)} className="rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
              O'qilmagan
            </label>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {isLoading && <Loading />}
          {data && data.length === 0 && (
            <Empty icon={<MessagesSquare className="h-6 w-6" />} title="Suhbatlar yo'q" text="Mijozlar Instagram yoki Telegram orqali yozganda shu yerda paydo bo'ladi." />
          )}
          {data?.map((item) => <InboxRow key={item.lead_id} item={item} active={item.lead_id === leadId} />)}
        </div>
      </div>
      <div className={cn('min-w-0 flex-1', leadId ? 'flex' : 'hidden md:flex')}>
        {leadId ? (
          <Conversation key={leadId} leadId={leadId} window={selected?.window} />
        ) : (
          <div className="flex flex-1 items-center justify-center bg-gray-50">
            <Empty icon={<MessagesSquare className="h-6 w-6" />} title="Suhbatni tanlang" text="Chapdagi ro'yxatdan suhbatni oching." />
          </div>
        )}
      </div>
    </div>
  )
}
