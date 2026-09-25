import type { ComponentType } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BarChart3, CalendarDays, ListChecks, MessageSquareText, Settings2 } from 'lucide-react'
import { PageHeader } from '@/components/ui'
import { isAdmin, useAuth } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { StatsTab } from './funnel/StatsTab'
import { BookingsTab } from './funnel/BookingsTab'
import { EntriesTab } from './funnel/EntriesTab'
import { MessagesTab } from './funnel/MessagesTab'
import { SettingsTab } from './funnel/SettingsTab'

type TabId = 'stats' | 'bookings' | 'entries' | 'messages' | 'settings'

interface Tab {
  id: TabId
  label: string
  icon: ComponentType<{ className?: string }>
  adminOnly?: boolean
  component: ComponentType
}

const TABS: Tab[] = [
  { id: 'stats', label: 'Statistika', icon: BarChart3, component: StatsTab },
  { id: 'bookings', label: 'Suhbatlar', icon: CalendarDays, component: BookingsTab },
  { id: 'entries', label: "Ro'yxat", icon: ListChecks, component: EntriesTab },
  { id: 'messages', label: 'Xabarlar', icon: MessageSquareText, adminOnly: true, component: MessagesTab },
  { id: 'settings', label: 'Sozlamalar', icon: Settings2, adminOnly: true, component: SettingsTab },
]

export default function FunnelPage() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const tabs = TABS.filter((t) => !t.adminOnly || isAdmin(user))
  // Unknown tab or an admin-only tab opened by an operator → first tab
  const active = tabs.find((t) => t.id === params.get('tab')) ?? tabs[0]
  const Active = active.component

  return (
    <>
      <PageHeader
        title="Voronka"
        subtitle="Lead-magnet: izohdagi kalit so'z → Telegram bot → qo'llanma (PDF) → suhbatga yozilish"
      />
      <div className="mb-6 overflow-x-auto border-b border-gray-200">
        <nav className="-mb-px flex gap-1" aria-label="Voronka bo'limlari">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setParams(id === 'stats' ? {} : { tab: id }, { replace: true })}
              className={cn(
                'flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
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
      <Active />
    </>
  )
}
