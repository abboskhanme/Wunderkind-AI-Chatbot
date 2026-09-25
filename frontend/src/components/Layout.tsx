import { useState, type ComponentType } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  BookOpen, Bot, FlaskConical, LayoutDashboard, LogOut, Magnet, Menu, MessagesSquare, Settings, Users, UserSquare2, X,
} from 'lucide-react'
import { isAdmin, useAuth } from '@/lib/auth'
import { USER_ROLE_LABELS } from '@/lib/labels'
import { cn } from '@/lib/cn'

interface NavItem {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
  adminOnly?: boolean
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Bosh sahifa', icon: LayoutDashboard },
  { to: '/inbox', label: 'Suhbatlar', icon: MessagesSquare },
  { to: '/leads', label: 'Leadlar', icon: UserSquare2 },
  { to: '/funnel', label: 'Voronka', icon: Magnet },
  { to: '/knowledge', label: 'Bilim bazasi', icon: BookOpen, adminOnly: true },
  { to: '/bot-menu', label: 'Bot menyusi', icon: Bot, adminOnly: true },
  { to: '/playground', label: 'Sinov', icon: FlaskConical, adminOnly: true },
  { to: '/settings', label: 'Sozlamalar', icon: Settings, adminOnly: true },
  { to: '/users', label: 'Foydalanuvchilar', icon: Users, adminOnly: true },
]

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user, logout } = useAuth()
  const items = NAV_ITEMS.filter((i) => !i.adminOnly || isAdmin(user))
  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white">W</div>
        <div>
          <p className="text-sm font-semibold text-gray-900">Wunderkind</p>
          <p className="text-xs text-gray-500">AI sotuv agenti</p>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 px-3">
        {items.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive ? 'bg-brand-50 text-brand-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900',
              )
            }
          >
            <Icon className="h-[18px] w-[18px]" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-gray-100 p-3">
        <div className="flex items-center gap-3 rounded-lg px-2 py-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-100 text-xs font-semibold text-gray-600">
            {(user?.full_name || user?.username || '?').slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-gray-900">{user?.full_name || user?.username}</p>
            <p className="text-xs text-gray-500">{USER_ROLE_LABELS[user?.role ?? ''] ?? user?.role}</p>
          </div>
          <button onClick={logout} title="Chiqish" className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

export function Layout() {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  const fullBleed = location.pathname.startsWith('/inbox')
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <aside className="hidden w-60 shrink-0 border-r border-gray-200 lg:block">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 flex lg:hidden" onClick={() => setOpen(false)}>
          <div className="w-64 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <Sidebar onNavigate={() => setOpen(false)} />
          </div>
          <div className="flex-1 bg-gray-900/30">
            <button className="m-3 rounded-lg bg-white p-2" onClick={() => setOpen(false)}>
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-3 lg:hidden">
          <button onClick={() => setOpen(true)} className="rounded-lg p-1.5 text-gray-600 hover:bg-gray-100">
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold text-gray-900">Wunderkind AI Agent</span>
        </header>
        <main className={cn('min-h-0 flex-1', fullBleed ? 'overflow-hidden' : 'overflow-y-auto')}>
          {fullBleed ? (
            <Outlet />
          ) : (
            <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
              <Outlet />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
