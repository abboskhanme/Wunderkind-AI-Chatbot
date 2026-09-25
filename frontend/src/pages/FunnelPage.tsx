import type { ComponentType } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, CalendarDays, Globe2, ListChecks, MessageSquareText, Settings2 } from 'lucide-react'
import { funnelApi } from '@/api/funnel'
import type { FunnelOut } from '@/api/types'
import { Loading, PageHeader } from '@/components/ui'
import { isAdmin, useAuth } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { FUNNELS_KEY, type FunnelTabProps } from './funnel/shared'
import { FunnelSwitcher } from './funnel/FunnelSwitcher'
import { StatsTab } from './funnel/StatsTab'
import { BookingsTab } from './funnel/BookingsTab'
import { EntriesTab } from './funnel/EntriesTab'
import { MessagesTab } from './funnel/MessagesTab'
import { FunnelSettingsTab } from './funnel/FunnelSettingsTab'
import { GlobalSettingsTab } from './funnel/SettingsTab'

type TabId = 'stats' | 'entries' | 'bookings' | 'messages' | 'settings' | 'global'

interface Tab {
  id: TabId
  label: string
  icon: ComponentType<{ className?: string }>
  adminOnly?: boolean
  /** Needs a concrete funnel (hidden for "Hammasi") */
  perFunnel?: boolean
  component: ComponentType<FunnelTabProps>
}

// Operators: Statistika, Ro'yxat, Suhbatlar (SPEC 11.5)
const TABS: Tab[] = [
  { id: 'stats', label: 'Statistika', icon: BarChart3, component: StatsTab },
  { id: 'entries', label: "Ro'yxat", icon: ListChecks, component: EntriesTab },
  { id: 'bookings', label: 'Suhbatlar', icon: CalendarDays, component: BookingsTab },
  { id: 'messages', label: 'Xabarlar', icon: MessageSquareText, adminOnly: true, perFunnel: true, component: MessagesTab },
  { id: 'settings', label: 'Sozlamalar', icon: Settings2, adminOnly: true, perFunnel: true, component: FunnelSettingsTab },
  { id: 'global', label: 'Umumiy sozlamalar', icon: Globe2, adminOnly: true, component: GlobalSettingsTab },
]

export default function FunnelPage() {
  const { user } = useAuth()
  const admin = isAdmin(user)
  const [params, setParams] = useSearchParams()
  const funnelsQuery = useQuery({
    queryKey: FUNNELS_KEY,
    queryFn: funnelApi.funnels,
    refetchInterval: 60_000,
  })
  const funnels = [...(funnelsQuery.data ?? [])].sort((a, b) => a.sort_order - b.sort_order)

  // ?funnel=<id>; absent or unknown → "Hammasi"
  const funnelParam = params.get('funnel')
  const funnel: FunnelOut | null = funnels.find((f) => f.id === funnelParam) ?? null
  const waitingForFunnel = Boolean(funnelParam) && funnelsQuery.isLoading

  const tabs = TABS.filter((t) => (!t.adminOnly || admin) && (!t.perFunnel || funnel))
  // Unknown tab, an admin-only tab opened by an operator, or a per-funnel tab on "Hammasi" → first tab
  const active = tabs.find((t) => t.id === params.get('tab')) ?? tabs[0]
  const Active = active.component

  function update(funnelId: string | null, tab: TabId) {
    const next: Record<string, string> = {}
    if (funnelId) next.funnel = funnelId
    if (tab !== 'stats') next.tab = tab
    setParams(next, { replace: true })
  }

  function selectFunnel(id: string | null) {
    // Keep the current tab unless it needs a funnel and "Hammasi" was chosen
    update(id, !id && active.perFunnel ? 'stats' : active.id)
  }

  return (
    <>
      <PageHeader
        title="Voronka"
        subtitle="Lead-magnet: izohdagi kalit so'z → Telegram bot → qo'llanma (PDF) → suhbatga yozilish"
      />
      <FunnelSwitcher
        funnels={funnels}
        selectedId={funnel?.id ?? null}
        loading={funnelsQuery.isLoading}
        error={funnelsQuery.isError ? funnelsQuery.error : null}
        onRetry={() => funnelsQuery.refetch()}
        canCreate={admin}
        onSelect={selectFunnel}
        onCreated={(f) => update(f.id, 'settings')}
      />
      <div className="mb-6 overflow-x-auto border-b border-gray-200">
        <nav className="-mb-px flex gap-1" aria-label="Voronka bo'limlari">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => update(funnel?.id ?? null, id)}
              className={cn(
                'flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                id === 'global' && 'sm:ml-auto',
                id === active.id
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-800',
              )}
              aria-current={id === active.id ? 'page' : undefined}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </nav>
      </div>
      {waitingForFunnel ? (
        <Loading />
      ) : (
        // Not keyed by funnel: tabs keep their own filters (dates, search) across funnel switches
        <Active funnel={funnel} funnels={funnels} selectFunnel={selectFunnel} />
      )}
    </>
  )
}
