import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { FlaskConical, RotateCcw, Send } from 'lucide-react'
import { playgroundApi } from '@/api/playground'
import { errorMessage } from '@/api/client'
import type { AgentOutput, Channel, ChatTurn } from '@/api/types'
import { Badge, Button, Card, CardHeader, Empty, Select, Textarea, Toggle } from '@/components/ui'
import { ScoreBadge } from '@/components/LeadBadges'
import { STAGE_LABELS } from '@/lib/labels'
import { cn } from '@/lib/cn'

const SAMPLES = [
  'Assalomu alaykum, 1-sinfga qabul bormi?',
  'Narxi qancha?',
  "Qimmat ekan, chegirma yo'qmi?",
  "Бола 10 ёшда, математикага бермоқчиман",
  'Сколько стоит обучение в 5 классе?',
]

interface Turn extends ChatTurn {
  output?: AgentOutput
}

function OutputBadges({ o }: { o: AgentOutput }) {
  const lead = Object.entries(o.lead).filter(([, v]) => v)
  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex flex-wrap gap-1">
        <ScoreBadge score={o.lead_score} />
        <Badge className="bg-brand-50 text-brand-700 ring-brand-200">{STAGE_LABELS[o.stage] ?? o.stage}</Badge>
        <Badge>{o.intent}</Badge>
        <Badge>{o.language}</Badge>
        {o.is_hot_lead && <Badge className="bg-rose-50 text-rose-700 ring-rose-200">Qaynoq</Badge>}
        {o.move_to_dm && <Badge className="bg-pink-50 text-pink-700 ring-pink-200">DM'ga</Badge>}
        {o.escalate_to_human && <Badge className="bg-amber-50 text-amber-700 ring-amber-200">Operatorga</Badge>}
      </div>
      {lead.length > 0 && (
        <div className="rounded-md bg-gray-50 px-2 py-1.5 text-[11px] text-gray-600 ring-1 ring-gray-200">
          {lead.map(([k, v]) => (
            <div key={k}><span className="text-gray-400">{k}:</span> {String(v)}</div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function PlaygroundPage() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const [channel, setChannel] = useState<Channel>('instagram')
  const [isComment, setIsComment] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => endRef.current?.scrollIntoView({ block: 'end' }), [turns.length])

  const run = useMutation({
    mutationFn: (history: Turn[]) =>
      playgroundApi.run(history.slice(-40).map(({ role, content }) => ({ role, content })), channel, isComment),
    onSuccess: (o) => setTurns((t) => [...t, { role: 'assistant', content: o.reply, output: o }]),
    onError: (e) => toast.error(errorMessage(e, "AI javob bermadi. Sozlamalarda API kalitini tekshiring.")),
  })

  function send(e?: FormEvent, preset?: string) {
    e?.preventDefault()
    const t = (preset ?? text).trim()
    if (!t || run.isPending) return
    const next = [...turns, { role: 'user' as const, content: t }]
    setTurns(next)
    setText('')
    run.mutate(next)
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <Card className="flex h-[calc(100vh-7rem)] flex-col">
        <CardHeader
          title="Sinov suhbati"
          subtitle="Haqiqiy AI va joriy bilim bazasi bilan. Hech kimga yuborilmaydi va saqlanmaydi."
          action={<Button variant="secondary" size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => setTurns([])} disabled={!turns.length}>Tozalash</Button>}
        />
        <div className="flex-1 space-y-3 overflow-y-auto bg-gray-50 px-4 py-4">
          {turns.length === 0 && (
            <Empty icon={<FlaskConical className="h-6 w-6" />} title="Mijoz sifatida yozib ko'ring" text="Bilim bazasini o'zgartirgach, agent qanday javob berishini shu yerda tekshiring." />
          )}
          {turns.map((t, i) => (
            <div key={i} className={cn('flex', t.role === 'user' ? 'justify-start' : 'justify-end')}>
              <div className="max-w-[80%]">
                <div className={cn('rounded-2xl px-3.5 py-2 text-sm shadow-sm', t.role === 'user' ? 'rounded-bl-md bg-white ring-1 ring-gray-200' : 'rounded-br-md bg-brand-600 text-white')}>
                  <p className="whitespace-pre-wrap break-words">{t.content}</p>
                </div>
                {t.output && <OutputBadges o={t.output} />}
              </div>
            </div>
          ))}
          {run.isPending && (
            <div className="flex justify-end">
              <div className="rounded-2xl rounded-br-md bg-brand-100 px-4 py-2.5 text-sm text-brand-700">AI yozmoqda...</div>
            </div>
          )}
          <div ref={endRef} />
        </div>
        <form onSubmit={send} className="flex items-end gap-2 border-t border-gray-200 p-3">
          <Textarea
            rows={2}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
            placeholder="Mijoz xabari..."
            className="resize-none"
          />
          <Button type="submit" disabled={!text.trim()} loading={run.isPending} icon={<Send className="h-4 w-4" />}>
            <span className="hidden sm:inline">Yuborish</span>
          </Button>
        </form>
      </Card>

      <div className="space-y-4">
        <Card className="space-y-4 p-4">
          <div>
            <p className="mb-1.5 text-sm font-medium text-gray-700">Kanal</p>
            <Select value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
              <option value="instagram">Instagram</option>
              <option value="telegram">Telegram</option>
            </Select>
          </div>
          {channel === 'instagram' && (
            <label className="flex items-center justify-between gap-3">
              <span className="text-sm text-gray-700">Ochiq izoh (comment)</span>
              <Toggle checked={isComment} onChange={setIsComment} />
            </label>
          )}
        </Card>
        <Card className="p-4">
          <p className="mb-2 text-sm font-medium text-gray-700">Tayyor misollar</p>
          <div className="flex flex-col gap-1.5">
            {SAMPLES.map((s) => (
              <button key={s} onClick={() => send(undefined, s)} disabled={run.isPending} className="rounded-lg px-3 py-2 text-left text-sm text-gray-700 ring-1 ring-gray-200 hover:bg-brand-50 hover:ring-brand-200 disabled:opacity-50">
                {s}
              </button>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
