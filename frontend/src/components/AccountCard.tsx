import { useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { BadgeCheck, Copy, ExternalLink, RefreshCw } from 'lucide-react'
import { leadsApi } from '@/api/leads'
import { errorMessage } from '@/api/client'
import type { LeadDetail } from '@/api/types'
import { copyText } from '@/lib/clipboard'
import { fmtDateTime, fmtNumber } from '@/lib/format'

const LANGUAGES: Record<string, string> = { uz: "O'zbek", ru: 'Rus', en: 'Ingliz', kk: 'Qozoq', tg: 'Tojik', ky: "Qirg'iz" }

function profileUrl(channel: string, username: string) {
  return channel === 'telegram' ? `https://t.me/${username}` : `https://instagram.com/${username}`
}

/** Profile photo through the authenticated API; initials when there is none. */
function Avatar({ leadId, name, version }: { leadId: string; name: string; version: number }) {
  const [src, setSrc] = useState<string>()

  useEffect(() => {
    let url: string | undefined
    let cancelled = false
    setSrc(undefined)
    leadsApi
      .avatarBlob(leadId)
      .then((blob) => {
        if (cancelled) return
        url = URL.createObjectURL(blob)
        setSrc(url)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [leadId, version])

  if (src) return <img src={src} alt="" onError={() => setSrc(undefined)} className="h-12 w-12 shrink-0 rounded-full object-cover ring-1 ring-gray-200" />
  // Array.from: an emoji is one character, not two broken halves
  const initials = name.replace(/^@/, '').split(/\s+/).filter(Boolean).map((w) => Array.from(w)[0]).slice(0, 2).join('').toUpperCase() || '?'
  return (
    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gray-100 text-sm font-semibold text-gray-500">
      {initials}
    </div>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-gray-500">{label}</dt>
      <dd className="min-w-0 break-words text-right text-gray-800">{children}</dd>
    </>
  )
}

/** What Telegram / Instagram report about the account itself (SPEC §13). */
export function AccountCard({ lead }: { lead: LeadDetail }) {
  const qc = useQueryClient()
  const [photoVersion, setPhotoVersion] = useState(0)
  const p = lead.profile
  const d = p?.details ?? {}
  const username = p?.username ?? lead.username
  const title = p?.full_name || (username ? `@${username}` : 'Akkaunt')

  const refresh = useMutation({
    mutationFn: () => leadsApi.refreshProfile(lead.id),
    onSuccess: (data) => {
      if (data) toast.success('Profil yangilandi')
      else toast.error(lead.channel === 'instagram'
        ? "Instagram profilni bermadi (mijoz hali DM yozmagan bo'lishi mumkin)"
        : "Telegram profilni bermadi")
      setPhotoVersion((v) => v + 1)
      qc.invalidateQueries({ queryKey: ['lead', lead.id] })
      qc.invalidateQueries({ queryKey: ['inbox'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const flags: string[] = []
  if (d.is_premium) flags.push('Telegram Premium')
  if (d.follows_us === true) flags.push('Bizga obuna')
  if (d.follows_us === false) flags.push('Bizga obuna emas')
  if (d.we_follow) flags.push('Biz obunamiz')

  return (
    <div className="rounded-lg p-3 ring-1 ring-gray-200">
      <div className="flex items-center gap-3">
        <Avatar leadId={lead.id} name={title} version={photoVersion} />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1 truncate text-sm font-semibold text-gray-900">
            <span className="truncate">{title}</span>
            {d.is_verified && <BadgeCheck className="h-4 w-4 shrink-0 text-sky-500" aria-label="Tasdiqlangan" />}
          </p>
          {username ? (
            <a href={profileUrl(lead.channel, username)} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 truncate text-xs text-brand-700 hover:underline">
              @{username} <ExternalLink className="h-3 w-3 shrink-0" />
            </a>
          ) : (
            <p className="text-xs text-gray-400">username yo'q</p>
          )}
        </div>
        <button
          className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          title="Profilni qayta o'qish"
        >
          <RefreshCw className={`h-4 w-4 ${refresh.isPending ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
        {p?.phone && (
          <Row label="Telefon">
            <span className="inline-flex items-center gap-1">
              {p.phone}
              <button onClick={() => copyText(p.phone!)} className="rounded p-0.5 text-gray-400 hover:text-gray-700" title="Nusxa olish">
                <Copy className="h-3 w-3" />
              </button>
            </span>
          </Row>
        )}
        <Row label={lead.channel === 'telegram' ? 'Telegram ID' : 'Instagram ID'}>
          <span className="font-mono text-[11px]">{lead.external_id}</span>
        </Row>
        {d.language_code && <Row label="Til">{LANGUAGES[d.language_code] ?? d.language_code}</Row>}
        {d.followers != null && <Row label="Obunachilar">{fmtNumber(d.followers)}</Row>}
        {d.birthdate && <Row label="Tug'ilgan kun">{d.birthdate}</Row>}
        {d.personal_channel && <Row label="Shaxsiy kanal">{d.personal_channel}</Row>}
        {d.bio && <Row label="Bio"><span className="whitespace-pre-wrap">{d.bio}</span></Row>}
        {p?.fetched_at && <Row label="Yangilangan">{fmtDateTime(p.fetched_at)}</Row>}
      </dl>

      {flags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {flags.map((f) => (
            <span key={f} className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">{f}</span>
          ))}
        </div>
      )}
      {!p && (
        <p className="mt-2 text-[11px] text-gray-400">
          Akkaunt ma'lumoti mijoz keyingi xabar yozganda avtomatik to'ladi yoki ⟳ tugmasini bosing.
        </p>
      )}
    </div>
  )
}
